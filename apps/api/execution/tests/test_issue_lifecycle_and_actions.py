from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus, IssueSeverity, IssueStatus, IssueType
from execution.exceptions import (
    ExecutionClosedError,
    InvalidIssueTransitionError,
    StaleVersionError,
)
from execution.models.milestone import ExecutionMilestone
from execution.services import (
    cancel_issue,
    complete_milestone,
    create_or_get_execution_for_deal,
    open_issue,
    publish_version,
    resolve_issue,
    start_issue,
)
from execution.tests.base import BaseExecutionTestCase


class IssueLifecycleAndActionTests(BaseExecutionTestCase):
    """Tests for explicit issue lifecycle actions, concurrency versioning, and close protection."""

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code="issue_lifecycle_test")
        self.version, (self.m1, self.m2, self.term_def) = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_open_issue_server_derives_metadata(self):
        """
        Invariants (Epic 10 Contract §65, §91, T1008):
        Server derives opened_by and opened_at; client cannot forge them.
        Initial status is strictly OPEN and version is 1.
        """
        before = timezone.now()
        issue = open_issue(
            self.execution.id,
            type=IssueType.LOGISTICS,
            title="Carrier delay reported",
            description="Truck delayed at weighbridge",
            severity=IssueSeverity.HIGH,
            blocks_execution=True,
            actor=self.buyer_owner,
        )
        after = timezone.now()

        self.assertEqual(issue.status, IssueStatus.OPEN)
        self.assertEqual(issue.version, 1)
        self.assertEqual(issue.opened_by, self.buyer_owner)
        self.assertTrue(before <= issue.opened_at <= after)
        self.assertIsNone(issue.resolved_by)
        self.assertIsNone(issue.resolved_at)
        self.assertEqual(issue.resolution_notes, "")
        self.assertTrue(issue.blocks_execution)

    def test_full_lifecycle_open_to_in_progress_to_resolved(self):
        """Normal lifecycle: OPEN -> IN_PROGRESS -> RESOLVED."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Penetration grade variance",
            actor=self.supplier_user,
        )
        self.assertEqual(issue.status, IssueStatus.OPEN)
        self.assertEqual(issue.version, 1)

        # 1. Start investigation (OPEN -> IN_PROGRESS)
        started = start_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(started.status, IssueStatus.IN_PROGRESS)
        self.assertEqual(started.version, 2)

        # 2. Authoritative resolution (IN_PROGRESS -> RESOLVED)
        resolved = resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=2,
            resolution_notes="Lab re-test confirmed within acceptable tolerances.",
            actor=self.operator_user,
        )
        self.assertEqual(resolved.status, IssueStatus.RESOLVED)
        self.assertEqual(resolved.version, 3)
        self.assertEqual(resolved.resolved_by, self.operator_user)
        self.assertIsNotNone(resolved.resolved_at)
        self.assertEqual(resolved.resolution_notes, "Lab re-test confirmed within acceptable tolerances.")

    def test_direct_resolution_from_open(self):
        """Issue can be directly resolved from OPEN (quick operational correction)."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.DOCUMENT,
            title="Missing customs stamp",
            actor=self.buyer_owner,
        )
        self.assertEqual(issue.status, IssueStatus.OPEN)

        resolved = resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Revised certified document uploaded with proper customs endorsement.",
            actor=self.supplier_user,
        )
        self.assertEqual(resolved.status, IssueStatus.RESOLVED)
        self.assertEqual(resolved.version, 2)
        self.assertEqual(resolved.resolved_by, self.supplier_user)

    def test_cancellation_from_open_and_in_progress(self):
        """Issue can be cancelled from OPEN or IN_PROGRESS."""
        # OPEN -> CANCELLED
        i1 = open_issue(
            self.execution.id,
            type=IssueType.OTHER,
            title="Duplicate issue report",
            actor=self.buyer_owner,
        )
        c1 = cancel_issue(
            self.execution.id,
            i1.id,
            expected_version=1,
            actor=self.buyer_owner,
            notes="Logged in error; duplicate of #42.",
        )
        self.assertEqual(c1.status, IssueStatus.CANCELLED)
        self.assertEqual(c1.version, 2)
        self.assertIn("duplicate of #42", c1.description)

        # IN_PROGRESS -> CANCELLED
        i2 = open_issue(
            self.execution.id,
            type=IssueType.LOGISTICS,
            title="Suspected vehicle breakdown",
            actor=self.supplier_user,
        )
        start_issue(self.execution.id, i2.id, expected_version=1, actor=self.supplier_user)
        c2 = cancel_issue(
            self.execution.id,
            i2.id,
            expected_version=2,
            actor=self.supplier_user,
            notes="False alarm; truck arrived on time.",
        )
        self.assertEqual(c2.status, IssueStatus.CANCELLED)
        self.assertEqual(c2.version, 3)

    def test_terminal_states_cannot_be_mutated_or_reopened(self):
        """RESOLVED and CANCELLED issues cannot transition further or be casually reopened."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.PAYMENT,
            title="Disputed bank fee",
            actor=self.buyer_owner,
        )
        resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Fee waived by supplier.",
            actor=self.operator_user,
        )

        # Attempt to start already RESOLVED issue
        with self.assertRaises(InvalidIssueTransitionError):
            start_issue(self.execution.id, issue.id, expected_version=2, actor=self.operator_user)

        # Attempt to cancel already RESOLVED issue
        with self.assertRaises(InvalidIssueTransitionError):
            cancel_issue(self.execution.id, issue.id, expected_version=2, actor=self.operator_user)

        # Attempt to resolve again
        with self.assertRaises(InvalidIssueTransitionError):
            resolve_issue(
                self.execution.id,
                issue.id,
                expected_version=2,
                resolution_notes="Second resolution",
                actor=self.operator_user,
            )

    def test_stale_expected_version_rejected(self):
        """Optimistic concurrency check rejects stale expected_version with StaleVersionError."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.QUANTITY,
            title="Weight bridge difference",
            actor=self.buyer_owner,
        )
        self.assertEqual(issue.version, 1)

        # Advance issue version
        start_issue(self.execution.id, issue.id, expected_version=1, actor=self.operator_user)

        # Attempt action with stale version 1
        with self.assertRaises(StaleVersionError):
            resolve_issue(
                self.execution.id,
                issue.id,
                expected_version=1,  # Stale! Current is 2
                resolution_notes="Should fail",
                actor=self.operator_user,
            )

    def test_cannot_open_issue_on_closed_execution(self):
        """
        Invariants (Epic 10 Contract §71, T1008):
        Reject ordinary creation of new Issue on CLOSED Execution.
        Does not implicitly reopen execution.
        """
        # Complete all milestones to close execution
        m1 = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m1)
        complete_milestone(self.execution.id, m1.id, expected_version=1, actor=self.operator_user)

        m2 = ExecutionMilestone.objects.get(execution=self.execution, definition=self.m2)
        complete_milestone(self.execution.id, m2.id, expected_version=1, actor=self.operator_user)

        term = ExecutionMilestone.objects.get(execution=self.execution, definition=self.term_def)
        complete_milestone(self.execution.id, term.id, expected_version=1, actor=self.operator_user)

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.CLOSED)

        # Attempt to open issue on closed execution
        with self.assertRaises(ExecutionClosedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Post-close dispute",
                actor=self.buyer_owner,
            )

    def test_api_issue_actions_and_concurrency_conflict_409(self):
        """Test API endpoints for issue open, start, resolve, cancel and 409 conflict handling."""
        self.client.force_authenticate(user=self.buyer_owner)

        # 1. Open issue via API
        url_list = f"/api/execution/{self.execution.id}/issues/"
        resp = self.client.post(
            url_list,
            {
                "type": "PAYMENT",
                "title": "Payment wire delayed",
                "severity": "HIGH",
                "blocks_execution": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        issue_id = resp.data["id"]
        self.assertEqual(resp.data["status"], "OPEN")
        self.assertEqual(resp.data["version"], 1)
        self.assertTrue(resp.data["blocks_execution"])
        self.assertTrue(resp.data["is_active_blocker"])

        # 2. Start investigation via API
        url_start = f"/api/execution/{self.execution.id}/issues/{issue_id}/start/"
        resp_start = self.client.post(url_start, {"expected_version": 1}, format="json")
        self.assertEqual(resp_start.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_start.data["status"], "IN_PROGRESS")
        self.assertEqual(resp_start.data["version"], 2)

        # 3. Optimistic concurrency conflict via API (expected_version=1 is stale)
        url_resolve = f"/api/execution/{self.execution.id}/issues/{issue_id}/resolve/"
        resp_stale = self.client.post(
            url_resolve,
            {
                "expected_version": 1,
                "resolution_notes": "Attempting stale resolve",
            },
            format="json",
        )
        self.assertEqual(resp_stale.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Optimistic concurrency conflict", resp_stale.data["detail"])

        # 4. Resolve with correct expected_version=2
        resp_resolve = self.client.post(
            url_resolve,
            {
                "expected_version": 2,
                "resolution_notes": "Payment receipt verified and cleared.",
            },
            format="json",
        )
        self.assertEqual(resp_resolve.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_resolve.data["status"], "RESOLVED")
        self.assertEqual(resp_resolve.data["version"], 3)
        self.assertFalse(resp_resolve.data["is_active_blocker"])
