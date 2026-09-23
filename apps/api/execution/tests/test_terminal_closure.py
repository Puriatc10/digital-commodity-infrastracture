from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus
from execution.exceptions import ExecutionClosedError
from execution.models.milestone import ExecutionMilestone
from execution.services import (
    complete_milestone,
    create_or_get_execution_for_deal,
    publish_version,
)
from execution.tests.base import BaseExecutionTestCase


class TerminalClosureTests(BaseExecutionTestCase):
    """Tests for terminal milestone execution closure and post-close guards (Epic 10 Contract §31, T1003)."""

    def setUp(self):
        super().setUp()
        # Create a custom template with 2 milestones: STEP_ONE -> DONE[terminal=True] (code is NOT "CLOSED")
        self.template = self.create_sample_template(code="custom_term_test")
        self.version, (self.m1, self.m2, self.term_def) = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)


        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_completing_terminal_milestone_atomically_closes_execution(self):
        """
        Completing terminal milestone (code='FINAL_STEP', terminal=True)
        atomically updates Execution.status to CLOSED and closed_at = milestone.actual_at.
        Proves generic terminal metadata, not hard-coding to code == 'CLOSED'.
        """
        self.assertNotEqual(self.term_def.code, "CLOSED")
        self.assertTrue(self.term_def.terminal)

        # Complete M1 and M2 first
        m1_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m1)
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m1_inst.id,
            expected_version=1,
            actor=self.operator_user,
        )

        m2_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m2)
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m2_inst.id,
            expected_version=1,
            actor=self.operator_user,
        )

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.OPEN)
        self.assertIsNone(self.execution.closed_at)

        # Complete terminal milestone M3
        m3_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.term_def)
        target_close_time = timezone.now()
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m3_inst.id,
            expected_version=1,
            actual_at=target_close_time,
            actor=self.operator_user,
        )

        # Execution must be atomically CLOSED with closed_at
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)
        self.assertEqual(self.execution.closed_at, target_close_time)
        self.assertEqual(self.execution.version, 2)

    def test_closed_execution_rejects_further_actions(self):
        """Once Execution is CLOSED, further milestone actions are rejected."""
        m1_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m1)
        complete_milestone(execution_id=self.execution.id, milestone_id=m1_inst.id, expected_version=1, actor=self.operator_user)

        m2_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m2)
        complete_milestone(execution_id=self.execution.id, milestone_id=m2_inst.id, expected_version=1, actor=self.operator_user)

        m3_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.term_def)
        complete_milestone(execution_id=self.execution.id, milestone_id=m3_inst.id, expected_version=1, actor=self.operator_user)

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)

        # Any subsequent action on any milestone of this execution must be rejected
        with self.assertRaises(ExecutionClosedError):
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m1_inst.id,
                expected_version=m1_inst.version,
                actor=self.operator_user,
            )

        # Via API
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/execution/{self.execution.id}/milestones/{m1_inst.id}/complete/"
        resp = self.client.post(url, {"expected_version": m1_inst.version}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
