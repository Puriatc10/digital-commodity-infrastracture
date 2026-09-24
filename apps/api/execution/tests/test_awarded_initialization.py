from django.contrib.auth import get_user_model

from execution.enums import MilestoneStatus
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal
from execution.tests.base import BaseExecutionTestCase

User = get_user_model()


class AwardedInitializationTests(BaseExecutionTestCase):
    """Tests for authoritative AWARDED milestone initialization (Epic 10 Contract §22, T1003)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()

    def test_awarded_milestone_auto_completes_at_creation(self):
        """AWARDED milestone automatically completes at execution creation."""
        execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        awarded_m = ExecutionMilestone.objects.get(
            execution=execution,
            definition__code="AWARDED",
        )
        self.assertEqual(awarded_m.status, MilestoneStatus.COMPLETED)
        self.assertIsNotNone(awarded_m.actual_at)
        self.assertIsNotNone(awarded_m.recorded_at)

        # Authoritative timestamp matches Award finalization
        expected_time = self.deal.award.finalized_at or self.deal.created_at
        self.assertEqual(awarded_m.actual_at, expected_time)

    def test_no_fabricated_user_actor_for_awarded(self):
        """Auto-completed AWARDED does not fabricate dummy/system users."""
        initial_user_count = User.objects.count()

        execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        awarded_m = ExecutionMilestone.objects.get(
            execution=execution,
            definition__code="AWARDED",
        )

        # User count in DB must NOT have increased
        self.assertEqual(User.objects.count(), initial_user_count)

        # completed_by is either the real user who finalized the award, or None. Never a dummy user.
        if awarded_m.completed_by:
            self.assertEqual(awarded_m.completed_by, self.deal.award.finalized_by)

    def test_all_other_milestones_remain_pending(self):
        """All milestones other than AWARDED must remain PENDING at initialization."""
        execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        other_milestones = list(
            ExecutionMilestone.objects.filter(execution=execution)
            .exclude(definition__code="AWARDED")
            .order_by("definition__sort_order")
        )

        self.assertEqual(len(other_milestones), 9)
        for m in other_milestones:
            self.assertEqual(
                m.status,
                MilestoneStatus.PENDING,
                f"Milestone {m.definition.code} should be PENDING, got {m.status}.",
            )
            self.assertIsNone(m.actual_at, f"Milestone {m.definition.code} actual_at should be None.")
            self.assertIsNone(m.completed_by, f"Milestone {m.definition.code} completed_by should be None.")
            self.assertIsNone(m.recorded_at, f"Milestone {m.definition.code} recorded_at should be None.")
