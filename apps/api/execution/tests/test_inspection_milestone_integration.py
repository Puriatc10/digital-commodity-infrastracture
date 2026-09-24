import copy
from django.utils import timezone

from deals.models import DealTermsSnapshot
from execution.enums import InspectionResult, InspectionStatus, MilestoneStatus
from execution.exceptions import ExecutionValidationError
from execution.models.inspection import ExecutionInspection
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    cancel_inspection,
    complete_inspection,
    complete_milestone,
    create_or_get_execution_for_deal,
    mark_inspection_not_required,
    record_loading,
    report_payment,
    schedule_inspection,
    schedule_loading,
)
from execution.tests.base import BaseExecutionTestCase


class InspectionMilestoneIntegrationTests(BaseExecutionTestCase):
    """
    Tests for INSPECTION_COMPLETED milestone integration and commercial Deal immutability (Contract §49, T1005).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)

    def _advance_to_inspection(self, execution):
        """Helper to advance execution workflow prerequisites up to INSPECTION_COMPLETED."""
        # Bitumen flow: AWARDED (auto-completed) -> CONTRACT_SIGNED -> PAYMENT_REPORTED -> LOADING_SCHEDULED -> LOADED -> INSPECTION_COMPLETED
        m_contract = ExecutionMilestone.objects.get(execution=execution, definition__code="CONTRACT_SIGNED")
        complete_milestone(execution_id=execution.id, milestone_id=m_contract.id, expected_version=1, actor=self.operator_user)

        report_payment(execution_id=execution.id, expected_version=1, actor=self.buyer_owner)
        m_pay = ExecutionMilestone.objects.get(execution=execution, definition__code="PAYMENT_REPORTED")
        complete_milestone(execution_id=execution.id, milestone_id=m_pay.id, expected_version=1, actor=self.operator_user)

        now = timezone.now()
        schedule_loading(execution.id, expected_version=1, actor=self.supplier_user, scheduled_loading_at=now)
        m_sched = ExecutionMilestone.objects.get(execution=execution, definition__code="LOADING_SCHEDULED")
        complete_milestone(execution_id=execution.id, milestone_id=m_sched.id, expected_version=1, actor=self.operator_user)

        record_loading(execution.id, expected_version=2, actor=self.supplier_user, actual_loading_at=now)
        m_load = ExecutionMilestone.objects.get(execution=execution, definition__code="LOADED")
        complete_milestone(execution_id=execution.id, milestone_id=m_load.id, expected_version=1, actor=self.operator_user)

    def test_milestone_allowed_when_not_required(self):
        """When inspection is NOT_REQUIRED, INSPECTION_COMPLETED milestone completes successfully."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        insp = ExecutionInspection.objects.get(execution=execution)
        self.assertEqual(insp.status, InspectionStatus.NOT_REQUIRED)

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        m_completed = complete_milestone(
            execution_id=execution.id,
            milestone_id=m_insp.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)

    def test_milestone_allowed_when_completed_pass(self):
        """When inspection is COMPLETED with PASS, INSPECTION_COMPLETED milestone completes successfully."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        now = timezone.now()
        schedule_inspection(execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=now)
        complete_inspection(execution.id, expected_version=2, actor=self.supplier_user, inspection_at=now, result=InspectionResult.PASS)

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        m_completed = complete_milestone(
            execution_id=execution.id,
            milestone_id=m_insp.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)
        self.assertEqual(m_completed.actual_at, now)

    def test_milestone_allowed_when_completed_fail(self):
        """
        Critical Contract Invariant (§49):
        COMPLETED + FAIL allows INSPECTION_COMPLETED milestone to complete.
        Inspection occurred; quality did not pass. Downstream acceptance / issue policy handles failure.
        """
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        now = timezone.now()
        schedule_inspection(execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=now)
        complete_inspection(execution.id, expected_version=2, actor=self.supplier_user, inspection_at=now, result=InspectionResult.FAIL)

        insp = ExecutionInspection.objects.get(execution=execution)
        self.assertEqual(insp.status, InspectionStatus.COMPLETED)
        self.assertEqual(insp.result, InspectionResult.FAIL)

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        m_completed = complete_milestone(
            execution_id=execution.id,
            milestone_id=m_insp.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)

    def test_milestone_allowed_when_completed_conditional(self):
        """COMPLETED + CONDITIONAL allows INSPECTION_COMPLETED milestone to complete."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        now = timezone.now()
        schedule_inspection(execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=now)
        complete_inspection(execution.id, expected_version=2, actor=self.supplier_user, inspection_at=now, result=InspectionResult.CONDITIONAL)

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        m_completed = complete_milestone(
            execution_id=execution.id,
            milestone_id=m_insp.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)

    def test_milestone_rejected_when_pending(self):
        """When inspection is PENDING, INSPECTION_COMPLETED milestone cannot complete."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        insp = ExecutionInspection.objects.get(execution=execution)
        insp.status = InspectionStatus.PENDING
        insp.required = True
        insp.save()

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=execution.id,
                milestone_id=m_insp.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires inspection status to be COMPLETED or NOT_REQUIRED", str(ctx.exception))

    def test_milestone_rejected_when_scheduled(self):
        """When inspection is SCHEDULED, INSPECTION_COMPLETED milestone cannot complete."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        now = timezone.now()
        schedule_inspection(execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=now)

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=execution.id,
                milestone_id=m_insp.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires inspection status to be COMPLETED or NOT_REQUIRED", str(ctx.exception))

    def test_milestone_rejected_when_cancelled(self):
        """When inspection is CANCELLED, INSPECTION_COMPLETED milestone cannot complete."""
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self._advance_to_inspection(execution)

        cancel_inspection(execution.id, expected_version=1, actor=self.supplier_user, notes="Cancelled due to storm.")

        m_insp = ExecutionMilestone.objects.get(execution=execution, definition__code="INSPECTION_COMPLETED")
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=execution.id,
                milestone_id=m_insp.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires inspection status to be COMPLETED or NOT_REQUIRED", str(ctx.exception))

    def test_commercial_deal_immutability_across_all_inspection_actions(self):
        """
        Verify that Deal and DealTermsSnapshot (specifications, schema_version, etc.)
        remain 100% immutable across schedule, complete, cancel, and mark-not-required actions.
        """
        deal = self.create_sample_deal()
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)

        terms_snap = DealTermsSnapshot.objects.get(deal=deal)
        initial_specs = copy.deepcopy(terms_snap.specifications)
        initial_schema_version_id = terms_snap.schema_version_id
        initial_quantity = terms_snap.quantity
        initial_unit_price = terms_snap.unit_price
        initial_currency = terms_snap.currency

        now = timezone.now()

        # Action 1: schedule
        schedule_inspection(execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=now, agency="SGS")
        terms_snap.refresh_from_db()
        self.assertEqual(terms_snap.specifications, initial_specs)
        self.assertEqual(terms_snap.schema_version_id, initial_schema_version_id)
        self.assertEqual(terms_snap.quantity, initial_quantity)
        self.assertEqual(terms_snap.unit_price, initial_unit_price)
        self.assertEqual(terms_snap.currency, initial_currency)

        # Action 2: complete (with FAIL to test quality failure immutability)
        complete_inspection(execution.id, expected_version=2, actor=self.supplier_user, inspection_at=now, result=InspectionResult.FAIL)
        terms_snap.refresh_from_db()
        self.assertEqual(terms_snap.specifications, initial_specs)
        self.assertEqual(terms_snap.schema_version_id, initial_schema_version_id)
        self.assertEqual(terms_snap.quantity, initial_quantity)
        self.assertEqual(terms_snap.unit_price, initial_unit_price)
        self.assertEqual(terms_snap.currency, initial_currency)

        # Action 3: cancel on a second execution
        deal2 = self.create_sample_deal()
        exec2 = create_or_get_execution_for_deal(deal_id=deal2.id, actor=self.operator_user)
        terms2 = DealTermsSnapshot.objects.get(deal=deal2)
        specs2 = copy.deepcopy(terms2.specifications)

        schedule_inspection(exec2.id, expected_version=1, actor=self.supplier_user, scheduled_at=now)
        cancel_inspection(exec2.id, expected_version=2, actor=self.supplier_user, notes="Cancelled.")
        terms2.refresh_from_db()
        self.assertEqual(terms2.specifications, specs2)
        self.assertEqual(terms2.schema_version_id, initial_schema_version_id)

        # Action 4: mark not required on a third execution
        deal3 = self.create_sample_deal()
        exec3 = create_or_get_execution_for_deal(deal_id=deal3.id, actor=self.operator_user)
        terms3 = DealTermsSnapshot.objects.get(deal=deal3)
        specs3 = copy.deepcopy(terms3.specifications)

        mark_inspection_not_required(exec3.id, expected_version=1, actor=self.buyer_owner)
        terms3.refresh_from_db()
        self.assertEqual(terms3.specifications, specs3)
        self.assertEqual(terms3.schema_version_id, initial_schema_version_id)
