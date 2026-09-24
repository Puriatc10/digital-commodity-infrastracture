from unittest.mock import patch
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile

from execution.enums import (
    ExecutionDocumentCategory,
    IssueSeverity,
    IssueStatus,
    IssueType,
)
from execution.models import (
    ExecutionInspection,
    ExecutionLogistics,
    ExecutionPayment,
)
from execution.services import (
    create_or_get_execution_for_deal,
    open_issue,
    publish_version,
    resolve_issue,
    upload_execution_document,
)
from execution.tests.base import BaseExecutionTestCase


class IssueAggregateIndependenceTests(BaseExecutionTestCase):
    """
    Verifies Aggregate Independence (Epic 10 Contract §70, §76):
    An ExecutionIssue does NOT automatically mutate, overwrite, or corrupt other sub-aggregates:
    - QUALITY issue does not alter ExecutionInspection status or notes.
    - PAYMENT issue does not alter ExecutionPayment status or expected amount.
    - QUANTITY issue does not alter Deal commercial quantity, unit price, or total amount.
    - LOGISTICS issue does not alter ExecutionLogistics state or carrier/mode.
    - DOCUMENT issue does not alter or delete existing ExecutionDocument evidence.
    - CONTRACT issue does not alter Deal contract terms or counterparties.
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code=f"indep_test_{uuid.uuid4().hex[:6]}")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        self.inspection = ExecutionInspection.objects.get(execution=self.execution)
        self.payment = ExecutionPayment.objects.get(execution=self.execution)
        self.logistics = ExecutionLogistics.objects.get(execution=self.execution)

    def test_quality_issue_does_not_mutate_inspection(self):
        """QUALITY issue does not mutate ExecutionInspection state or notes."""
        initial_status = self.inspection.status
        initial_version = self.inspection.version
        initial_agency = self.inspection.agency
        initial_notes = self.inspection.notes

        issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Batch penetration grade out of spec",
            severity=IssueSeverity.HIGH,
            actor=self.buyer_owner,
        )
        self.assertEqual(issue.status, IssueStatus.OPEN)

        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, initial_status)
        self.assertEqual(self.inspection.version, initial_version)
        self.assertEqual(self.inspection.agency, initial_agency)
        self.assertEqual(self.inspection.notes, initial_notes)

        resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Commercial discount accepted for out-of-spec batch.",
            actor=self.operator_user,
        )

        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, initial_status)
        self.assertEqual(self.inspection.version, initial_version)

    def test_payment_issue_does_not_mutate_payment(self):
        """PAYMENT issue does not mutate ExecutionPayment state or expected amount."""
        initial_status = self.payment.status
        initial_version = self.payment.version
        initial_expected_amount = self.payment.expected_amount

        issue = open_issue(
            self.execution.id,
            type=IssueType.PAYMENT,
            title="Disputed bank fee deduction",
            severity=IssueSeverity.MEDIUM,
            actor=self.supplier_user,
        )

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, initial_status)
        self.assertEqual(self.payment.version, initial_version)
        self.assertEqual(self.payment.expected_amount, initial_expected_amount)

        resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Fee reimbursed by buyer.",
            actor=self.buyer_owner,
        )

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, initial_status)
        self.assertEqual(self.payment.version, initial_version)

    def test_quantity_issue_does_not_mutate_deal_commercial_terms(self):
        """QUANTITY issue does not mutate Deal quantity, price, or terms snapshot."""
        initial_deal_quantity = self.deal.terms_snapshot.quantity
        initial_deal_price = self.deal.terms_snapshot.unit_price
        initial_deal_total = self.deal.terms_snapshot.product_cost_snapshot

        open_issue(
            self.execution.id,
            type=IssueType.QUANTITY,
            title="Shortage of 15 MT upon unloading",
            severity=IssueSeverity.HIGH,
            actor=self.buyer_owner,
        )

        self.deal.refresh_from_db()
        self.deal.terms_snapshot.refresh_from_db()
        self.assertEqual(self.deal.terms_snapshot.quantity, initial_deal_quantity)
        self.assertEqual(self.deal.terms_snapshot.unit_price, initial_deal_price)
        self.assertEqual(self.deal.terms_snapshot.product_cost_snapshot, initial_deal_total)

    def test_logistics_issue_does_not_mutate_logistics(self):
        """LOGISTICS issue does not mutate ExecutionLogistics state or transport mode."""
        initial_version = self.logistics.version
        initial_carrier_name = self.logistics.carrier_name
        initial_transport_mode = self.logistics.transport_mode

        open_issue(
            self.execution.id,
            type=IssueType.LOGISTICS,
            title="Vessel delayed at port",
            severity=IssueSeverity.MEDIUM,
            actor=self.buyer_owner,
        )

        self.logistics.refresh_from_db()
        self.assertEqual(self.logistics.version, initial_version)
        self.assertEqual(self.logistics.carrier_name, initial_carrier_name)
        self.assertEqual(self.logistics.transport_mode, initial_transport_mode)

    @patch("execution.services.document_service.upload_document")
    def test_document_issue_does_not_alter_existing_documents(self, mock_upload):
        """DOCUMENT issue does not mutate or invalidate existing ExecutionDocument records."""
        mock_upload.return_value = "s3://bucket/test_doc.pdf"
        dummy_file = SimpleUploadedFile("bol.pdf", b"%PDF-1.4 test document content", content_type="application/pdf")

        doc = upload_execution_document(
            self.execution.id,
            file_obj=dummy_file,
            category=ExecutionDocumentCategory.LOADING_DOCUMENT,
            actor=self.supplier_user,
        )
        initial_doc_id = doc.id
        initial_doc_file_name = doc.file_name
        initial_doc_key = doc.object_key

        open_issue(
            self.execution.id,
            type=IssueType.DOCUMENT,
            title="BOL endorsement missing signature",
            severity=IssueSeverity.HIGH,
            actor=self.buyer_owner,
        )

        doc.refresh_from_db()
        self.assertEqual(doc.id, initial_doc_id)
        self.assertEqual(doc.file_name, initial_doc_file_name)
        self.assertEqual(doc.object_key, initial_doc_key)

    def test_contract_issue_does_not_mutate_deal_contract_integrity(self):
        """CONTRACT issue does not alter contract or deal counterparties."""
        buyer_org_id = self.deal.buyer_organization_id
        seller_org_id = self.deal.seller_organization_id

        open_issue(
            self.execution.id,
            type=IssueType.CONTRACT,
            title="Clause 14 interpretation disagreement",
            severity=IssueSeverity.LOW,
            actor=self.supplier_user,
        )

        self.deal.refresh_from_db()
        self.assertEqual(self.deal.buyer_organization_id, buyer_org_id)
        self.assertEqual(self.deal.seller_organization_id, seller_org_id)
