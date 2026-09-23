import uuid
from django.core.exceptions import ValidationError

from execution.enums import ExecutionDocumentCategory
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal, get_or_create_execution_inspection
from execution.tests.base import BaseExecutionTestCase


class ExecutionDocumentModelTests(BaseExecutionTestCase):
    """Unit tests for ExecutionDocument model, invariants, and constraints."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

    def test_create_valid_execution_document(self):
        """Verify successful creation of an ExecutionDocument with valid metadata."""
        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="sales_contract_v1.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-sales_contract_v1.pdf",
            uploaded_by=self.buyer_user,
        )
        self.assertIsNotNone(doc.id)
        self.assertEqual(doc.execution, self.execution)
        self.assertEqual(doc.category, ExecutionDocumentCategory.CONTRACT)
        self.assertEqual(doc.file_name, "sales_contract_v1.pdf")
        self.assertEqual(doc.size_bytes, 1024)
        self.assertIn("ExecutionDocument", str(doc))

    def test_empty_file_name_rejected(self):
        """Verify empty or blank filename is rejected by model validation."""
        doc = ExecutionDocument(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="   ",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-doc.pdf",
            uploaded_by=self.buyer_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.save()
        self.assertIn("file_name", ctx.exception.message_dict)

    def test_non_positive_size_rejected(self):
        """Verify zero or negative size is rejected by model validation and check constraint."""
        doc = ExecutionDocument(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="valid.pdf",
            content_type="application/pdf",
            size_bytes=0,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-valid.pdf",
            uploaded_by=self.buyer_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.save()
        self.assertIn("size_bytes", ctx.exception.message_dict)

    def test_same_execution_guard_milestone_valid(self):
        """Verify associating a milestone belonging to the same execution succeeds."""
        milestone = self.execution.milestones.first()
        self.assertIsNotNone(milestone)

        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            milestone=milestone,
            category=ExecutionDocumentCategory.LOADING_DOCUMENT,
            file_name="loading_ticket.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-loading.pdf",
            uploaded_by=self.supplier_user,
        )
        self.assertEqual(doc.milestone, milestone)
        self.assertEqual(doc.execution, milestone.execution)

    def test_same_execution_guard_foreign_milestone_rejected(self):
        """Verify associating a milestone from a foreign execution is strictly rejected (Same-Execution Guard)."""
        other_deal = self.create_sample_deal()
        other_exec = create_or_get_execution_for_deal(
            deal_id=other_deal.id,
            actor=self.operator_user,
        )
        foreign_milestone = other_exec.milestones.first()

        doc = ExecutionDocument(
            execution=self.execution,
            milestone=foreign_milestone,
            category=ExecutionDocumentCategory.LOADING_DOCUMENT,
            file_name="foreign_loading.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-foreign.pdf",
            uploaded_by=self.supplier_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.save()
        self.assertIn("milestone", ctx.exception.message_dict)

    def test_same_execution_guard_inspection_valid(self):
        """Verify associating an inspection belonging to the same execution succeeds."""
        inspection = get_or_create_execution_inspection(self.execution.id, actor=self.operator_user)

        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            inspection=inspection,
            category=ExecutionDocumentCategory.INSPECTION_REPORT,
            file_name="sgs_report.pdf",
            content_type="application/pdf",
            size_bytes=4096,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-sgs.pdf",
            uploaded_by=self.supplier_user,
        )
        self.assertEqual(doc.inspection, inspection)
        self.assertEqual(doc.execution, inspection.execution)

    def test_same_execution_guard_foreign_inspection_rejected(self):
        """Verify associating an inspection from a foreign execution is strictly rejected (Same-Execution Guard)."""
        other_deal = self.create_sample_deal()
        other_exec = create_or_get_execution_for_deal(
            deal_id=other_deal.id,
            actor=self.operator_user,
        )
        foreign_inspection = get_or_create_execution_inspection(other_exec.id, actor=self.operator_user)

        doc = ExecutionDocument(
            execution=self.execution,
            inspection=foreign_inspection,
            category=ExecutionDocumentCategory.INSPECTION_REPORT,
            file_name="foreign_inspection.pdf",
            content_type="application/pdf",
            size_bytes=4096,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-foreign_sgs.pdf",
            uploaded_by=self.supplier_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            doc.save()
        self.assertIn("inspection", ctx.exception.message_dict)

    def test_direct_deletion_prevented(self):
        """Verify pre_delete signal prevents deleting ExecutionDocument records."""
        doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="contract.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/{uuid.uuid4()}-contract.pdf",
            uploaded_by=self.buyer_user,
        )
        with self.assertRaises(ValidationError):
            doc.delete()
