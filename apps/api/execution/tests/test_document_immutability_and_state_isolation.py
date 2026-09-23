from io import BytesIO
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status

from execution.enums import ExecutionDocumentCategory, MilestoneStatus, PaymentStatus
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    get_or_create_execution_inspection,
    get_or_create_execution_payment,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionDocumentImmutabilityAndStateIsolationTests(BaseExecutionTestCase):
    """
    Tests ensuring document evidence never mutates domain execution aggregates or Deal snapshots (T1007).
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
        self.payment = get_or_create_execution_payment(self.execution.id, actor=self.operator_user)

        self.upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution.id})

    def _make_dummy_pdf(self, filename="doc.pdf"):
        f = BytesIO(b"%PDF-1.4 dummy valid pdf content")
        f.name = filename
        f.content_type = "application/pdf"
        return f

    @patch("execution.services.document_service.upload_document")
    def test_payment_proof_upload_does_not_mutate_payment_state(self, mock_upload):
        """Uploading PAYMENT_PROOF does not change ExecutionPayment.status from EXPECTED to REPORTED."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)

        self.assertEqual(self.payment.status, PaymentStatus.EXPECTED)

        resp = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("payment_slip.pdf"), "category": ExecutionDocumentCategory.PAYMENT_PROOF},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.EXPECTED, "PAYMENT_PROOF upload must not mutate payment state!")

    @patch("execution.services.document_service.upload_document")
    def test_inspection_report_upload_does_not_mutate_inspection_state(self, mock_upload):
        """Uploading INSPECTION_REPORT does not change ExecutionInspection.status to COMPLETED."""
        mock_upload.return_value = None
        self.client.force_login(self.supplier_user)

        initial_status = self.inspection.status

        resp = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("inspection_sgs.pdf"), "category": ExecutionDocumentCategory.INSPECTION_REPORT},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, initial_status, "INSPECTION_REPORT upload must not complete inspection!")

    @patch("execution.services.document_service.upload_document")
    def test_delivery_proof_upload_does_not_complete_milestone(self, mock_upload):
        """Uploading DELIVERY_PROOF does not mark the DELIVERED milestone as COMPLETED."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)

        delivered_ms = self.execution.milestones.filter(definition__code="DELIVERED").first()
        if delivered_ms:
            self.assertEqual(delivered_ms.status, MilestoneStatus.PENDING)

        resp = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("delivery_receipt.pdf"), "category": ExecutionDocumentCategory.DELIVERY_PROOF},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        if delivered_ms:
            delivered_ms.refresh_from_db()
            self.assertEqual(delivered_ms.status, MilestoneStatus.PENDING, "DELIVERY_PROOF must not complete milestone!")

    @patch("execution.services.document_service.upload_document")
    def test_deal_commercial_snapshot_remains_strictly_immutable(self, mock_upload):
        """Assert Deal terms, parties, and specifications snapshots are unchanged after document upload."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)

        initial_terms = self.deal.terms_snapshot
        initial_quantity = initial_terms.quantity
        initial_specs = dict(initial_terms.specifications)

        resp = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("signed_contract.pdf"), "category": ExecutionDocumentCategory.CONTRACT},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.deal.refresh_from_db()
        terms = self.deal.terms_snapshot
        self.assertEqual(terms.quantity, initial_quantity)
        self.assertEqual(terms.specifications, initial_specs)

    @patch("execution.services.document_service.upload_document")
    def test_append_only_evidence_new_record_created_no_in_place_overwrite(self, mock_upload):
        """Consecutive uploads of the same category create new distinct records with distinct storage identities."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)

        resp1 = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("contract_v1.pdf"), "category": ExecutionDocumentCategory.CONTRACT},
            format="multipart",
        )
        resp2 = self.client.post(
            self.upload_url,
            {"file": self._make_dummy_pdf("contract_v2.pdf"), "category": ExecutionDocumentCategory.CONTRACT},
            format="multipart",
        )

        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(resp1.data["id"], resp2.data["id"])

        docs = ExecutionDocument.objects.filter(execution=self.execution, category=ExecutionDocumentCategory.CONTRACT)
        self.assertEqual(docs.count(), 2)

    def test_no_put_patch_delete_endpoints_for_documents(self):
        """Verify no PUT, PATCH, or DELETE HTTP methods are exposed on document endpoints."""
        self.client.force_login(self.buyer_user)
        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="existing.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/existing.pdf",
            uploaded_by=self.buyer_user,
        )
        detail_url = reverse(
            "execution-document-detail",
            kwargs={"execution_id": self.execution.id, "document_id": doc.id},
        )

        resp_put = self.client.put(detail_url, {"file_name": "hacked.pdf"})
        self.assertEqual(resp_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        resp_patch = self.client.patch(detail_url, {"file_name": "hacked.pdf"})
        self.assertEqual(resp_patch.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        resp_delete = self.client.delete(detail_url)
        self.assertEqual(resp_delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
