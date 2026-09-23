from django.core.exceptions import ValidationError
from django.utils import timezone

from execution.enums import InspectionResult, InspectionStatus
from execution.models.inspection import ExecutionInspection
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal
from execution.tests.base import BaseExecutionTestCase


class ExecutionInspectionModelTests(BaseExecutionTestCase):
    """
    Unit tests for ExecutionInspection aggregate model invariants (Epic 10 Contract §43–§49, T1005).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.inspection = ExecutionInspection.objects.get(execution=self.execution)

    def test_exact_statuses(self):
        """Status choices must strictly match NOT_REQUIRED, PENDING, SCHEDULED, COMPLETED, CANCELLED."""
        expected = {"NOT_REQUIRED", "PENDING", "SCHEDULED", "COMPLETED", "CANCELLED"}
        actual = set(InspectionStatus.values)
        self.assertEqual(actual, expected)

    def test_exact_results(self):
        """Result choices must strictly match PASS, FAIL, CONDITIONAL, UNKNOWN."""
        expected = {"PASS", "FAIL", "CONDITIONAL", "UNKNOWN"}
        actual = set(InspectionResult.values)
        self.assertEqual(actual, expected)

    def test_reject_inconsistent_pending_with_pass(self):
        """PENDING status with PASS result is rejected."""
        self.inspection.status = InspectionStatus.PENDING
        self.inspection.result = InspectionResult.PASS
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("result", ctx.exception.message_dict)
        self.assertIn("must remain UNKNOWN", str(ctx.exception))

    def test_reject_inconsistent_scheduled_with_fail(self):
        """SCHEDULED status with FAIL result is rejected."""
        self.inspection.status = InspectionStatus.SCHEDULED
        self.inspection.result = InspectionResult.FAIL
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("result", ctx.exception.message_dict)
        self.assertIn("must remain UNKNOWN", str(ctx.exception))

    def test_reject_not_required_with_fake_pass(self):
        """NOT_REQUIRED status must not become a fake PASS."""
        self.inspection.status = InspectionStatus.NOT_REQUIRED
        self.inspection.result = InspectionResult.PASS
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("result", ctx.exception.message_dict)
        self.assertIn("UNKNOWN", str(ctx.exception))

    def test_reject_completed_without_inspection_at(self):
        """COMPLETED status requires inspection_at timestamp."""
        self.inspection.status = InspectionStatus.COMPLETED
        self.inspection.result = InspectionResult.PASS
        self.inspection.inspection_at = None
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("inspection_at", ctx.exception.message_dict)

    def test_valid_completed_states(self):
        """COMPLETED status with valid inspection_at and each valid result succeeds."""
        now = timezone.now()
        for res in [InspectionResult.PASS, InspectionResult.FAIL, InspectionResult.CONDITIONAL, InspectionResult.UNKNOWN]:
            # Create a fresh execution/inspection for each check to avoid immutability error
            deal = self.create_sample_deal()
            exec_inst = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
            insp = ExecutionInspection.objects.get(execution=exec_inst)
            insp.status = InspectionStatus.COMPLETED
            insp.result = res
            insp.inspection_at = now
            insp.agency = "SGS"
            insp.save()
            insp.refresh_from_db()
            self.assertEqual(insp.status, InspectionStatus.COMPLETED)
            self.assertEqual(insp.result, res)

    def test_completed_facts_immutable_no_reopen(self):
        """Completed inspection cannot be casually reopened or altered."""
        now = timezone.now()
        self.inspection.status = InspectionStatus.COMPLETED
        self.inspection.result = InspectionResult.PASS
        self.inspection.inspection_at = now
        self.inspection.agency = "SGS"
        self.inspection.save()

        # 1. Attempt to reopen to PENDING
        self.inspection.status = InspectionStatus.PENDING
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("status", ctx.exception.message_dict)
        self.assertIn("cannot be reopened", str(ctx.exception))

        # Reset status
        self.inspection.status = InspectionStatus.COMPLETED

        # 2. Attempt to alter inspection_at
        self.inspection.inspection_at = now + timezone.timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("inspection_at", ctx.exception.message_dict)
        self.assertIn("immutable", str(ctx.exception))

        # Reset inspection_at
        self.inspection.inspection_at = now

        # 3. Attempt to alter result from PASS to FAIL
        self.inspection.result = InspectionResult.FAIL
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("result", ctx.exception.message_dict)
        self.assertIn("immutable", str(ctx.exception))

    def test_cancelled_inspection_no_reopen(self):
        """Cancelled inspection cannot be casually reopened or altered."""
        self.inspection.status = InspectionStatus.CANCELLED
        self.inspection.save()

        self.inspection.status = InspectionStatus.PENDING
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("status", ctx.exception.message_dict)
        self.assertIn("cannot be casually reopened", str(ctx.exception))

    def test_execution_reference_immutable(self):
        """Execution foreign key reference cannot be mutated."""
        other_deal = self.create_sample_deal()
        other_exec = create_or_get_execution_for_deal(deal_id=other_deal.id, actor=self.operator_user)

        self.inspection.execution = other_exec
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("execution", ctx.exception.message_dict)

    def test_positive_version_check(self):
        """Version must be >= 1."""
        self.inspection.version = 0
        with self.assertRaises(ValidationError) as ctx:
            self.inspection.save()
        self.assertIn("version", ctx.exception.message_dict)

    def test_notes_do_not_infer_result(self):
        """Free text notes containing 'passed' or 'failed' never infer or change result."""
        self.inspection.status = InspectionStatus.PENDING
        self.inspection.notes = "Sample 123 passed all laboratory penetration tests."
        self.inspection.save()
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.result, InspectionResult.UNKNOWN)
        self.assertEqual(self.inspection.status, InspectionStatus.PENDING)
