import threading
import uuid

from django.db import connection, close_old_connections

from execution.enums import (
    ExecutionStatus,
    IssueSeverity,
    IssueStatus,
    IssueType,
)
from execution.exceptions import (
    ExecutionClosedError,
    ExecutionClosingBlockedError,
    InvalidIssueTransitionError,
    StaleVersionError,
)
from execution.models import ExecutionIssue, ExecutionMilestone
from execution.services import (
    cancel_issue,
    complete_milestone,
    create_or_get_execution_for_deal,
    open_issue,
    publish_version,
    resolve_issue,
)
from execution.tests.base import BaseExecutionTransactionTestCase


class IssueConcurrencyTests(BaseExecutionTransactionTestCase):
    """
    Mandatory Real PostgreSQL concurrency tests for Issue Management (Epic 10 Contract §67-74).
    Verifies that OCC and pessimistic row locks protect against lost updates, split-brain states,
    and closing with unresolved blocking issues.
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code=f"issue_conc_{uuid.uuid4().hex[:6]}")
        self.version, (self.m1, self.m2, self.m3) = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

    def test_real_postgresql_race_resolve_vs_cancel(self):
        """
        Mandatory Race 1: resolve vs cancel on the same issue.

        Scenario:
        - Issue is OPEN, version=1.
        - Caller A calls resolve_issue(expected_version=1).
        - Caller B calls cancel_issue(expected_version=1).
        - Both execute concurrently across separate PostgreSQL connections via threading.Barrier(2).

        Invariants verified:
        - Exactly one authoritative transition wins (either RESOLVED or CANCELLED, version=2).
        - The other caller receives StaleVersionError (HTTP 409) or InvalidIssueTransitionError.
        - Database state is never corrupted; version is incremented exactly once.
        - No unhandled 500 error occurs.
        """
        issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Concurrent resolution test",
            severity=IssueSeverity.HIGH,
            actor=self.buyer_owner,
        )
        self.assertEqual(issue.version, 1)
        self.assertEqual(issue.status, IssueStatus.OPEN)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_resolve():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                res = resolve_issue(
                    self.execution.id,
                    issue.id,
                    expected_version=1,
                    resolution_notes="Resolved by buyer agreement",
                    actor=self.buyer_owner,
                )
                results.append(("resolve", res))
            except Exception as e:
                errors.append(("resolve", e))
            finally:
                connection.close()

        def run_cancel():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                res = cancel_issue(
                    self.execution.id,
                    issue.id,
                    expected_version=1,
                    actor=self.supplier_user,
                )
                results.append(("cancel", res))
            except Exception as e:
                errors.append(("cancel", e))
            finally:
                connection.close()

        t1 = threading.Thread(target=run_resolve)
        t2 = threading.Thread(target=run_cancel)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        close_old_connections()
        issue.refresh_from_db()

        # Invariant 1: Exactly one succeeded, exactly one failed
        self.assertEqual(len(results), 1, f"Expected exactly 1 success, got {len(results)}: {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 error, got {len(errors)}: {errors}")

        # Invariant 2: Winner set version to 2 and status to RESOLVED or CANCELLED
        winner_op, _ = results[0]
        loser_op, loser_err = errors[0]

        self.assertIn(winner_op, ["resolve", "cancel"])
        self.assertIn(loser_op, ["resolve", "cancel"])
        self.assertNotEqual(winner_op, loser_op)

        self.assertEqual(issue.version, 2)
        if winner_op == "resolve":
            self.assertEqual(issue.status, IssueStatus.RESOLVED)
            self.assertEqual(issue.resolved_by, self.buyer_owner)
            self.assertIsNotNone(issue.resolved_at)
        else:
            self.assertEqual(issue.status, IssueStatus.CANCELLED)

        # Invariant 3: Loser received controlled OCC / state transition exception (never 500)
        self.assertTrue(
            isinstance(loser_err, (StaleVersionError, InvalidIssueTransitionError)),
            f"Expected StaleVersionError or InvalidIssueTransitionError, got {type(loser_err)}: {loser_err}",
        )

    def test_real_postgresql_race_close_vs_open_blocking_issue(self):
        """
        Mandatory Race 2: complete_milestone (closing execution) vs open_issue (blocking issue).

        Scenario:
        - Execution has reached terminal milestone ready to close.
        - Caller A calls complete_milestone on terminal milestone to close execution.
        - Caller B calls open_issue with blocks_execution=True.
        - Both execute concurrently across separate PostgreSQL connections via threading.Barrier(2).

        Invariants verified:
        - SERIALIZATION GUARANTEE: Both operations serialize via Execution pessimistic row lock.
        - IMPOSSIBLE STATE PREVENTED: An execution can NEVER be CLOSED with an active blocking issue open.
          * If close wins: execution becomes CLOSED, open_issue fails with ExecutionClosedError (HTTP 409).
          * If open_issue wins: issue is created (status=OPEN, blocks_execution=True), complete_milestone
            detects active blocker and fails with ExecutionClosingBlockedError (HTTP 409).
        - Exactly one winner and one controlled exception; no corrupted database state.
        """
        # Advance workflow to final step ready for completion
        inst1 = ExecutionMilestone.objects.get(execution=self.execution, definition__code="STEP_ONE")
        complete_milestone(self.execution.id, inst1.id, expected_version=1, actor=self.buyer_owner)

        inst2 = ExecutionMilestone.objects.get(execution=self.execution, definition__code="STEP_TWO")
        complete_milestone(self.execution.id, inst2.id, expected_version=1, actor=self.buyer_owner)

        inst3 = ExecutionMilestone.objects.get(execution=self.execution, definition__code="FINAL_STEP")

        # Execution is currently OPEN, terminal milestone is ready to complete
        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, ExecutionStatus.OPEN)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_close():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                res = complete_milestone(
                    self.execution.id,
                    inst3.id,
                    expected_version=1,
                    actor=self.buyer_owner,
                )
                results.append(("close", res))
            except Exception as e:
                errors.append(("close", e))
            finally:
                connection.close()

        def run_open_issue():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                res = open_issue(
                    self.execution.id,
                    type=IssueType.PAYMENT,
                    title="Disputed settlement amount",
                    blocks_execution=True,
                    actor=self.supplier_user,
                )
                results.append(("open_issue", res))
            except Exception as e:
                errors.append(("open_issue", e))
            finally:
                connection.close()

        t1 = threading.Thread(target=run_close)
        t2 = threading.Thread(target=run_open_issue)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        close_old_connections()
        self.execution.refresh_from_db()

        # Invariant: NEVER allow CLOSED status and an open blocking issue concurrently
        active_blockers = ExecutionIssue.objects.filter(
            execution=self.execution,
            blocks_execution=True,
            status__in=[IssueStatus.OPEN, IssueStatus.IN_PROGRESS],
        )

        if self.execution.status == ExecutionStatus.CLOSED:
            # Close won the race: open_issue must have failed
            self.assertEqual(active_blockers.count(), 0, "Execution closed but active blocker exists!")
            close_res = [r for r in results if r[0] == "close"]
            self.assertEqual(len(close_res), 1)
            open_errs = [e for e in errors if e[0] == "open_issue"]
            self.assertEqual(len(open_errs), 1)
            self.assertIsInstance(open_errs[0][1], ExecutionClosedError)
        else:
            # Open issue won the race: close must have failed with ExecutionClosingBlockedError
            self.assertGreaterEqual(active_blockers.count(), 1)
            open_res = [r for r in results if r[0] == "open_issue"]
            self.assertEqual(len(open_res), 1)
            close_errs = [e for e in errors if e[0] == "close"]
            self.assertEqual(len(close_errs), 1)
            self.assertIsInstance(close_errs[0][1], ExecutionClosingBlockedError)
            self.assertEqual(close_errs[0][1].code, "BLOCKING_ISSUE_OPEN")
