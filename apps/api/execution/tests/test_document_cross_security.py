from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status

from execution.enums import ExecutionDocumentCategory
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    get_or_create_execution_inspection,
)
from execution.tests.base import BaseExecutionTestCase
from organizations.models import Organization, OrganizationMembership

User = get_user_model()


class ExecutionDocumentCrossSecurityTests(BaseExecutionTestCase):
    """
    IDOR, cross-execution integrity, and storage security attack tests (Epic 10 Contract §62, §63, T1007).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)

        # Deal 1 & Execution 1 (Party: self.buyer_org and self.supplier_org)
        self.deal_1 = self.create_sample_deal()
        self.execution_1 = create_or_get_execution_for_deal(
            deal_id=self.deal_1.id,
            actor=self.operator_user,
        )
        self.doc_1 = ExecutionDocument.objects.create(
            execution=self.execution_1,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="deal_1_contract.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution_1.id}/secret-deal-1.pdf",
            uploaded_by=self.buyer_user,
        )

        # Deal 2 & Execution 2
        self.deal_2 = self.create_sample_deal()
        self.execution_2 = create_or_get_execution_for_deal(
            deal_id=self.deal_2.id,
            actor=self.operator_user,
        )
        self.doc_2 = ExecutionDocument.objects.create(
            execution=self.execution_2,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="deal_2_contract.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            object_key=f"execution-documents/{self.execution_2.id}/secret-deal-2.pdf",
            uploaded_by=self.operator_user,
        )

        # Foreign actor completely unrelated to Deal 1 or Execution 1
        self.foreign_org = Organization.objects.create(name="Foreign Org", country="AE", is_active=True)
        self.foreign_user = User.objects.create_user(
            email="foreign_security@ae.com", password="password123"
        )
        OrganizationMembership.objects.create(
            user=self.foreign_user,
            organization=self.foreign_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

    def _make_dummy_pdf(self, filename="doc.pdf"):
        f = BytesIO(b"%PDF-1.4 dummy valid pdf content")
        f.name = filename
        f.content_type = "application/pdf"
        return f

    def test_cross_execution_list_idor_rejected(self):
        """Foreign actor cannot list documents for Execution 1."""
        self.client.force_login(self.foreign_user)
        url_1 = reverse("execution-document-list", kwargs={"execution_id": self.execution_1.id})
        resp = self.client.get(url_1)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_execution_detail_idor_rejected(self):
        """Foreign actor cannot view document metadata from Execution 1."""
        self.client.force_login(self.foreign_user)
        url_1 = reverse(
            "execution-document-detail",
            kwargs={"execution_id": self.execution_1.id, "document_id": self.doc_1.id},
        )
        resp = self.client.get(url_1)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_execution_download_idor_rejected(self):
        """Foreign actor cannot download document bytes from Execution 1."""
        self.client.force_login(self.foreign_user)
        url_1 = reverse(
            "execution-document-download",
            kwargs={"execution_id": self.execution_1.id, "document_id": self.doc_1.id},
        )
        resp = self.client.get(url_1)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_substitute_document_id_under_own_execution_rejected(self):
        """Querying Execution 1 endpoint with document_id belonging to Execution 2 returns 404."""
        self.client.force_login(self.buyer_user)
        # Attempting to fetch doc_2 under execution_1 URL
        url = reverse(
            "execution-document-detail",
            kwargs={"execution_id": self.execution_1.id, "document_id": self.doc_2.id},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # Attempting to download doc_2 under execution_1 URL
        dl_url = reverse(
            "execution-document-download",
            kwargs={"execution_id": self.execution_1.id, "document_id": self.doc_2.id},
        )
        resp = self.client.get(dl_url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @patch("execution.services.document_service.upload_document")
    def test_cross_execution_milestone_attachment_attack_rejected(self, mock_upload):
        """Attempting to upload a document to Execution 1 referencing Execution 2's milestone is rejected."""
        self.client.force_login(self.buyer_user)
        foreign_milestone = self.execution_2.milestones.first()
        self.assertIsNotNone(foreign_milestone)

        upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution_1.id})
        f = self._make_dummy_pdf()

        resp = self.client.post(
            upload_url,
            {
                "file": f,
                "category": ExecutionDocumentCategory.CONTRACT,
                "milestone_id": str(foreign_milestone.id),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("belongs to execution", str(resp.data))
        mock_upload.assert_not_called()

    @patch("execution.services.document_service.upload_document")
    def test_cross_execution_inspection_attachment_attack_rejected(self, mock_upload):
        """Attempting to upload a document to Execution 1 referencing Execution 2's inspection is rejected."""
        self.client.force_login(self.operator_user)
        foreign_inspection = get_or_create_execution_inspection(self.execution_2.id, actor=self.operator_user)

        upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution_1.id})
        f = self._make_dummy_pdf()

        resp = self.client.post(
            upload_url,
            {
                "file": f,
                "category": ExecutionDocumentCategory.INSPECTION_REPORT,
                "inspection_id": str(foreign_inspection.id),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("belongs to execution", str(resp.data))
        mock_upload.assert_not_called()

    @patch("execution.services.document_service.upload_document")
    def test_object_key_substitution_rejected(self, mock_upload):
        """Client supplying object_key or storage reference in request is ignored; server derives UUID key."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)
        upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution_1.id})
        f = self._make_dummy_pdf("legit.pdf")

        malicious_key = "execution-documents/hacked-object-key.pdf"
        resp = self.client.post(
            upload_url,
            {
                "file": f,
                "category": ExecutionDocumentCategory.CONTRACT,
                "object_key": malicious_key,
                "storage_key": malicious_key,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        doc = ExecutionDocument.objects.get(id=resp.data["id"])
        self.assertNotEqual(doc.object_key, malicious_key)
        self.assertTrue(doc.object_key.startswith(f"execution-documents/{self.execution_1.id}/"))

    def test_raw_storage_key_never_exposed_in_api_responses(self):
        """Assert object_key and bucket never leak in document list or detail responses."""
        self.client.force_login(self.buyer_user)

        # List endpoint
        list_url = reverse("execution-document-list", kwargs={"execution_id": self.execution_1.id})
        resp = self.client.get(list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        for item in resp.data:
            self.assertNotIn("object_key", item)
            self.assertNotIn("storage_key", item)
            self.assertNotIn("bucket", item)

        # Detail endpoint
        detail_url = reverse(
            "execution-document-detail",
            kwargs={"execution_id": self.execution_1.id, "document_id": self.doc_1.id},
        )
        resp = self.client.get(detail_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn("object_key", resp.data)
        self.assertNotIn("storage_key", resp.data)
        self.assertNotIn("bucket", resp.data)
