
from django.utils import timezone
from rest_framework.test import APIClient

from execution.enums import MilestoneStatus
from execution.exceptions import ExecutionValidationError
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    complete_milestone,
    create_or_get_execution_for_deal,
    record_delivery,
    record_loading,
    schedule_loading,
)
from execution.tests.base import BaseExecutionTestCase


class LogisticsMilestoneIntegrationTests(BaseExecutionTestCase):
    """
    Tests for authoritative logistics facts guarding milestone progression (Epic 10 Contract §25, §26, §29, §30, T1004).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

        # Complete prerequisites up to PAYMENT_REPORTED
        # Bitumen flow: AWARDED (auto-completed) -> CONTRACT_SIGNED -> PAYMENT_REPORTED -> LOADING_SCHEDULED -> LOADED -> INSPECTION_COMPLETED -> IN_TRANSIT -> DELIVERED -> ACCEPTED -> CLOSED
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actor=self.operator_user,
        )

        m_payment = ExecutionMilestone.objects.get(execution=self.execution, definition__code="PAYMENT_REPORTED")
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_payment.id,
            expected_version=1,
            actor=self.operator_user,
        )

    def test_loading_scheduled_milestone_guarded_by_scheduled_loading_at(self):
        """Milestone LOADING_SCHEDULED requires scheduled_loading_at in logistics tracking."""
        m_scheduled = ExecutionMilestone.objects.get(execution=self.execution, definition__code="LOADING_SCHEDULED")

        # 1. Attempt to complete without scheduled_loading_at -> REJECTED
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_scheduled.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires scheduled loading date/time in logistics tracking", str(ctx.exception))

        # 2. Record scheduled loading in logistics
        now = timezone.now()
        schedule_loading(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_loading_at=now + timezone.timedelta(days=2),
        )

        # 3. Now completing LOADING_SCHEDULED succeeds
        m_scheduled.refresh_from_db()
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_scheduled.id,
            expected_version=m_scheduled.version,
            actor=self.operator_user,
        )
        m_scheduled.refresh_from_db()
        self.assertEqual(m_scheduled.status, MilestoneStatus.COMPLETED)

    def test_loaded_milestone_guarded_by_actual_loading_at(self):
        """Milestone LOADED requires actual_loading_at in logistics tracking."""
        # Advance through LOADING_SCHEDULED first
        now = timezone.now()
        schedule_loading(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_loading_at=now,
        )
        m_scheduled = ExecutionMilestone.objects.get(execution=self.execution, definition__code="LOADING_SCHEDULED")
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_scheduled.id,
            expected_version=1,
            actor=self.operator_user,
        )

        m_loaded = ExecutionMilestone.objects.get(execution=self.execution, definition__code="LOADED")

        # 1. Attempt to complete LOADED without actual_loading_at -> REJECTED
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_loaded.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires actual loading date/time in logistics tracking", str(ctx.exception))

        # 2. Record actual loading in logistics
        record_loading(
            self.execution.id,
            expected_version=2,
            actor=self.supplier_user,
            actual_loading_at=now,
        )

        # 3. Completing LOADED now succeeds
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_loaded.id,
            expected_version=1,
            actor=self.operator_user,
        )
        m_loaded.refresh_from_db()
        self.assertEqual(m_loaded.status, MilestoneStatus.COMPLETED)

    def test_delivered_milestone_guarded_and_does_not_imply_accepted(self):
        """
        Milestone DELIVERED requires actual_delivery_at in logistics tracking.
        Completing DELIVERED does NOT automatically imply or complete ACCEPTED.
        """
        now = timezone.now()
        schedule_loading(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_loading_at=now,
        )
        m_sched = ExecutionMilestone.objects.get(execution=self.execution, definition__code="LOADING_SCHEDULED")
        complete_milestone(execution_id=self.execution.id, milestone_id=m_sched.id, expected_version=1, actor=self.operator_user)

        record_loading(
            self.execution.id,
            expected_version=2,
            actor=self.supplier_user,
            actual_loading_at=now,
        )
        m_load = ExecutionMilestone.objects.get(execution=self.execution, definition__code="LOADED")
        complete_milestone(execution_id=self.execution.id, milestone_id=m_load.id, expected_version=1, actor=self.operator_user)

        # Advance INSPECTION_COMPLETED and IN_TRANSIT
        m_insp = ExecutionMilestone.objects.get(execution=self.execution, definition__code="INSPECTION_COMPLETED")
        complete_milestone(execution_id=self.execution.id, milestone_id=m_insp.id, expected_version=1, actor=self.operator_user)

        m_transit = ExecutionMilestone.objects.get(execution=self.execution, definition__code="IN_TRANSIT")
        complete_milestone(execution_id=self.execution.id, milestone_id=m_transit.id, expected_version=1, actor=self.operator_user)

        m_deliv = ExecutionMilestone.objects.get(execution=self.execution, definition__code="DELIVERED")

        # 1. Complete DELIVERED without actual_delivery_at in logistics -> REJECTED
        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_deliv.id,
                expected_version=1,
                actor=self.operator_user,
            )
        self.assertIn("requires actual delivery date/time in logistics tracking", str(ctx.exception))

        # 2. Record delivery receipt by Buyer
        delivery_time = now + timezone.timedelta(days=3)
        record_delivery(
            self.execution.id,
            expected_version=3,
            actor=self.buyer_owner,
            actual_delivery_at=delivery_time,
        )

        # 3. Complete DELIVERED milestone -> SUCCEEDS
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_deliv.id,
            expected_version=1,
            actor=self.operator_user,
        )
        m_deliv.refresh_from_db()
        self.assertEqual(m_deliv.status, MilestoneStatus.COMPLETED)

        # 4. CRITICAL INVARIANT: ACCEPTED milestone MUST REMAIN PENDING!
        m_accept = ExecutionMilestone.objects.get(execution=self.execution, definition__code="ACCEPTED")
        self.assertEqual(m_accept.status, MilestoneStatus.PENDING)
        self.assertIsNone(m_accept.actual_at)
