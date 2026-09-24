from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionDocumentCategory, IssueSeverity, IssueType
from execution.exceptions import CrossObjectIntegrityError
from execution.models import ExecutionDocument
from execution.services import (
    create_or_get_execution_for_deal,
    get_execution_documents,
    open_issue,
    publish_version,
    upload_execution_document,
)
from execution.tests.base import BaseExecutionTestCase


class IssueDocumentIntegrationTests(BaseExecutionTestCase):
    """
    Verifies Issue-to-Document integration invariants (Epic 10 Contract §62, §71, T1008):
    - Optional association of ExecutionDocument to ExecutionIssue via nullable FK.
    - Same-Execution Guard: Document execution and Issue execution MUST match identically.
    - Filtering documents by issue_id via service and API.
    - Existing documents without issue remain unaffected.
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code=f"doc_issue_{uuid.uuid4().hex[:6]}")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        self.issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Lab certificate test failure",
            severity=IssueSeverity.HIGH,
            actor=self.buyer_owner,
        )

        self.client = APIClient()

    def _dummy_file(self, name="report.pdf"):
        return SimpleUploadedFile(
            name,
            b"%PDF-1.4 test document binary content",
            content_type="application/pdf",
        )

    @patch("execution.services.document_service.upload_document")
    def test_upload_document_linked_to_issue_via_service(self, mock_upload):
        """Upload document with issue_id links to issue correctly."""
        mock_upload.return_value = "s3://bucket/test_report.pdf"

        doc = upload_execution_document(
            self.execution.id,
            file_obj=self._dummy_file(),
            category=ExecutionDocumentCategory.OTHER,
            actor=self.buyer_owner,
            issue_id=self.issue.id,
        )

        self.assertEqual(doc.issue_id, self.issue.id)
        self.assertEqual(doc.issue, self.issue)
        self.assertIn(doc, self.issue.documents.all())

        # Filter by issue_id in get_execution_documents service
        issue_docs = get_execution_documents(
            self.execution.id,
            issue_id=self.issue.id,
            actor=self.buyer_owner,
        )
        self.assertEqual(len(issue_docs), 1)
        self.assertEqual(issue_docs[0].id, doc.id)

    @patch("execution.services.document_service.upload_document")
    def test_upload_document_linked_to_issue_via_api(self, mock_upload):
        """Upload document with issue_id via REST API."""
        mock_upload.return_value = "s3://bucket/test_report_api.pdf"
        self.client.force_authenticate(user=self.buyer_owner)

        upload_url = f"/api/execution/{self.execution.id}/documents/upload/"
        resp = self.client.post(
            upload_url,
            {
                "file": self._dummy_file("evidence.pdf"),
                "category": ExecutionDocumentCategory.OTHER,
                "issue_id": str(self.issue.id),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["issue_id"], str(self.issue.id))

        # Query GET documents with ?issue_id= filter
        list_url = f"/api/execution/{self.execution.id}/documents/"
        get_resp = self.client.get(f"{list_url}?issue_id={self.issue.id}")
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_resp.data), 1)
        self.assertEqual(get_resp.data[0]["issue_id"], str(self.issue.id))

    @patch("execution.services.document_service.upload_document")
    def test_cross_execution_document_attachment_rejected(self, mock_upload):
        """Document upload referencing an issue belonging to a different execution is strictly rejected."""
        mock_upload.return_value = "s3://bucket/test_other.pdf"

        # Create a second execution
        deal2 = self.create_sample_deal()
        execution2 = create_or_get_execution_for_deal(
            deal_id=deal2.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        # Attempt to upload document to execution2 with issue from execution1
        with self.assertRaises(CrossObjectIntegrityError):
            upload_execution_document(
                execution2.id,
                file_obj=self._dummy_file(),
                category=ExecutionDocumentCategory.OTHER,
                actor=self.buyer_owner,
                issue_id=self.issue.id,  # belongs to self.execution, not execution2
            )

        # Via API: returns HTTP 400
        self.client.force_authenticate(user=self.buyer_owner)
        upload_url = f"/api/execution/{execution2.id}/documents/upload/"
        resp = self.client.post(
            upload_url,
            {
                "file": self._dummy_file(),
                "category": ExecutionDocumentCategory.OTHER,
                "issue_id": str(self.issue.id),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_model_level_same_execution_guard(self):
        """ExecutionDocument.clean() enforces that doc.issue.execution_id == doc.execution_id."""
        deal2 = self.create_sample_deal()
        execution2 = create_or_get_execution_for_deal(
            deal_id=deal2.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        mismatched_doc = ExecutionDocument(
            execution=execution2,
            issue=self.issue,  # from self.execution
            category=ExecutionDocumentCategory.OTHER,
            file_name="mismatch.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key="s3://bucket/mismatch.pdf",
            uploaded_by=self.buyer_owner,
        )
        with self.assertRaises(ValidationError) as cm:
            mismatched_doc.full_clean()
        self.assertIn("issue", cm.exception.message_dict)

    @patch("execution.services.document_service.upload_document")
    def test_existing_documents_without_issue_unaffected(self, mock_upload):
        """Documents uploaded without issue_id remain issue=None."""
        mock_upload.return_value = "s3://bucket/test_no_issue.pdf"

        doc = upload_execution_document(
            self.execution.id,
            file_obj=self._dummy_file(),
            category=ExecutionDocumentCategory.CONTRACT,
            actor=self.buyer_owner,
        )
        self.assertIsNone(doc.issue_id)
        self.assertIsNone(doc.issue)
