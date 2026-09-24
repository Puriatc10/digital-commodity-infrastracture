import uuid
from django.urls import reverse
from rest_framework import status

from execution.enums import ExecutionDocumentCategory, TimelineEventType
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    get_or_create_execution_inspection,
    project_execution_timeline,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionDocumentTimelineTests(BaseExecutionTestCase):
    """
    Tests for Execution Document integration with the deterministic Execution Timeline (Epic 10 Contract §32–§34, §60–§64, T1007).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.inspection = get_or_create_execution_inspection(self.execution.id, actor=self.operator_user)
        self.milestone = self.execution.milestones.filter(definition__code="CONTRACT_SIGNED").first()

    def test_timeline_projects_document_uploaded_events(self):
        """Timeline includes DOCUMENT_UPLOADED events with safe metadata."""
        doc1 = ExecutionDocument.objects.create(
            execution=self.execution,
            milestone=self.milestone,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="signed_deal_contract.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-contract.pdf",
            uploaded_by=self.buyer_user,
        )

        doc2 = ExecutionDocument.objects.create(
            execution=self.execution,
            inspection=self.inspection,
            category=ExecutionDocumentCategory.INSPECTION_REPORT,
            file_name="quality_sgs.pdf",
            content_type="application/pdf",
            size_bytes=4096,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-sgs.pdf",
            uploaded_by=self.supplier_user,
        )

        events = project_execution_timeline(self.execution.id, actor=self.operator_user)

        doc_events = [e for e in events if e["event_type"] == TimelineEventType.DOCUMENT_UPLOADED]
        self.assertEqual(len(doc_events), 2)

        # First document event check
        ev1 = next(e for e in doc_events if e["event_id"] == f"document-{doc1.id}-uploaded")
        self.assertEqual(ev1["type_priority"], 28)
        self.assertEqual(ev1["actor_id"], str(self.buyer_user.id))
        self.assertEqual(ev1["actor_email"], self.buyer_user.email)
        self.assertEqual(ev1["milestone_code"], "CONTRACT_SIGNED")
        self.assertIn("Contract: signed_deal_contract.pdf", ev1["notes"])
        self.assertEqual(ev1["metadata"]["category"], ExecutionDocumentCategory.CONTRACT)
        self.assertEqual(ev1["metadata"]["file_name"], "signed_deal_contract.pdf")
        self.assertEqual(ev1["metadata"]["size_bytes"], 2048)
        self.assertEqual(ev1["metadata"]["milestone_id"], str(self.milestone.id))

        # Second document event check
        ev2 = next(e for e in doc_events if e["event_id"] == f"document-{doc2.id}-uploaded")
        self.assertEqual(ev2["actor_id"], str(self.supplier_user.id))
        self.assertEqual(ev2["metadata"]["category"], ExecutionDocumentCategory.INSPECTION_REPORT)
        self.assertEqual(ev2["metadata"]["inspection_id"], str(self.inspection.id))

    def test_timeline_never_leaks_storage_internals(self):
        """Timeline events must strictly NEVER expose bucket name, raw object key, or storage URL."""
        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.PAYMENT_PROOF,
            file_name="swift_slip.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-internal-key.pdf",
            uploaded_by=self.buyer_user,
        )

        events = project_execution_timeline(self.execution.id, actor=self.buyer_user)
        doc_ev = next(e for e in events if e["event_id"] == f"document-{doc.id}-uploaded")

        # Check top-level event fields
        for field in ["object_key", "bucket", "url", "storage_key"]:
            self.assertNotIn(field, doc_ev)

        # Check metadata dictionary
        for field in ["object_key", "bucket", "url", "storage_key"]:
            self.assertNotIn(field, doc_ev["metadata"])

        # Check serialized string
        serialized_str = str(doc_ev)
        self.assertNotIn("internal-key", serialized_str)
        self.assertNotIn("minio", serialized_str.lower())

    def test_timeline_api_endpoint_projection(self):
        """Timeline HTTP API endpoint projects document uploaded events."""
        self.client.force_login(self.buyer_user)

        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.ACCEPTANCE_DOCUMENT,
            file_name="acceptance_cert.pdf",
            content_type="application/pdf",
            size_bytes=3072,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-acceptance.pdf",
            uploaded_by=self.buyer_user,
        )

        timeline_url = reverse("execution-timeline", kwargs={"execution_id": self.execution.id})
        resp = self.client.get(timeline_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        events = resp.data
        doc_events = [e for e in events if e["event_type"] == TimelineEventType.DOCUMENT_UPLOADED]
        self.assertEqual(len(doc_events), 1)
        self.assertEqual(doc_events[0]["event_id"], f"document-{doc.id}-uploaded")
        self.assertEqual(doc_events[0]["metadata"]["category"], ExecutionDocumentCategory.ACCEPTANCE_DOCUMENT)
