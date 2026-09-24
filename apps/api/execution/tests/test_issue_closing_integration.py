from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus, IssueType
from execution.exceptions import ExecutionClosingBlockedError
from execution.models.milestone import ExecutionMilestone
from execution.services import (
    cancel_issue,
    complete_milestone,
    create_or_get_execution_for_deal,
    open_issue,
    publish_version,
    resolve_issue,
)
from execution.tests.base import BaseExecutionTestCase


class IssueClosingIntegrationTests(BaseExecutionTestCase):
    """
    Tests for Execution closure integration with Issue Management (Epic 10 Contract §70, §71, T1008).

    Invariants:
    - Close permitted only when:
        terminal workflow guards pass
        AND
        no unresolved blocking Issue exists
        AND
        other currently-implemented close guards pass
    - Only issues with blocks_execution=True AND status in {OPEN, IN_PROGRESS} prevent close.
    - Non-blocking issues do NOT prevent close.
    - Resolved blocking issues do NOT prevent close.
    - Cancelled blocking issues do NOT prevent close.
    - Controlled machine-readable code BLOCKING_ISSUE_OPEN returned when close blocked.
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code="close_issue_test")
        self.version, (self.m1, self.m2, self.term_def) = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

        # Complete M1 and M2 prerequisites
        m1_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m1)
        complete_milestone(self.execution.id, m1_inst.id, expected_version=1, actor=self.operator_user)

        m2_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m2)
        complete_milestone(self.execution.id, m2_inst.id, expected_version=1, actor=self.operator_user)

        self.term_inst = ExecutionMilestone.objects.get(execution=self.execution, definition=self.term_def)

    def test_active_blocking_issue_prevents_terminal_closure(self):
        """Active blocking issue (blocks_execution=True, OPEN) prevents Execution closing."""
        blocking_issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Blocking off-spec issue",
            blocks_execution=True,
            actor=self.buyer_owner,
        )

        with self.assertRaises(ExecutionClosingBlockedError) as ctx:
            complete_milestone(
                self.execution.id,
                self.term_inst.id,
                expected_version=self.term_inst.version,
                actor=self.operator_user,
            )

        self.assertEqual(ctx.exception.code, "BLOCKING_ISSUE_OPEN")
        self.assertIn(str(blocking_issue.id), ctx.exception.context["blocking_issue_ids"])

        # Execution remains OPEN
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.OPEN)
        self.assertIsNone(self.execution.closed_at)

    def test_api_close_blocked_returns_controlled_error_contract(self):
        """API close blocked by open blocking issue returns HTTP 400 with BLOCKING_ISSUE_OPEN code and context."""
        blocking_issue = open_issue(
            self.execution.id,
            type=IssueType.PAYMENT,
            title="Blocking wire discrepancy",
            blocks_execution=True,
            actor=self.supplier_user,
        )

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/execution/{self.execution.id}/milestones/{self.term_inst.id}/complete/"
        resp = self.client.post(url, {"expected_version": self.term_inst.version}, format="json")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "BLOCKING_ISSUE_OPEN")
        self.assertIn(str(blocking_issue.id), resp.data["context"]["blocking_issue_ids"])

        # Execution remains OPEN
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.OPEN)

    def test_non_blocking_issue_does_not_prevent_close(self):
        """Non-blocking issue (blocks_execution=False) does NOT prevent Execution closure."""
        open_issue(
            self.execution.id,
            type=IssueType.OTHER,
            title="Minor cosmetic report",
            blocks_execution=False,
            actor=self.buyer_owner,
        )

        # Completing terminal milestone succeeds
        completed = complete_milestone(
            self.execution.id,
            self.term_inst.id,
            expected_version=self.term_inst.version,
            actor=self.operator_user,
        )
        self.assertEqual(completed.status, "COMPLETED")

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)
        self.assertIsNotNone(self.execution.closed_at)

    def test_resolved_blocking_issue_permits_close(self):
        """Resolved blocking issue (blocks_execution=True, RESOLVED) does NOT prevent Execution closure."""
        blocking_issue = open_issue(
            self.execution.id,
            type=IssueType.QUANTITY,
            title="Weight ticket mismatch",
            blocks_execution=True,
            actor=self.buyer_owner,
        )

        # Resolve the blocking issue
        resolve_issue(
            self.execution.id,
            blocking_issue.id,
            expected_version=1,
            resolution_notes="Discrepancy resolved via joint recalibration certificate.",
            actor=self.operator_user,
        )

        # Completing terminal milestone now succeeds
        completed = complete_milestone(
            self.execution.id,
            self.term_inst.id,
            expected_version=self.term_inst.version,
            actor=self.operator_user,
        )
        self.assertEqual(completed.status, "COMPLETED")

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)
        self.assertIsNotNone(self.execution.closed_at)

    def test_cancelled_blocking_issue_permits_close(self):
        """Cancelled blocking issue (blocks_execution=True, CANCELLED) does NOT prevent Execution closure."""
        blocking_issue = open_issue(
            self.execution.id,
            type=IssueType.DOCUMENT,
            title="Reported missing CMR",
            blocks_execution=True,
            actor=self.buyer_owner,
        )

        # Cancel the blocking issue
        cancel_issue(
            self.execution.id,
            blocking_issue.id,
            expected_version=1,
            notes="Document was found in archive; invalid report.",
            actor=self.buyer_owner,
        )

        # Completing terminal milestone succeeds
        completed = complete_milestone(
            self.execution.id,
            self.term_inst.id,
            expected_version=self.term_inst.version,
            actor=self.operator_user,
        )
        self.assertEqual(completed.status, "COMPLETED")

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)
        self.assertIsNotNone(self.execution.closed_at)
