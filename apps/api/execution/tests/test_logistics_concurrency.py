import concurrent.futures
import threading

from django.db import connection
from django.utils import timezone

from execution.exceptions import ExecutionValidationError, StaleVersionError
from execution.models.logistics import ExecutionLogistics
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    record_delivery,
    record_loading,
    schedule_loading,
    update_eta,
)
from execution.tests.base import BaseExecutionTransactionTestCase


class LogisticsConcurrencyTests(BaseExecutionTransactionTestCase):
    """
    Mandatory real PostgreSQL multi-threaded race tests for ExecutionLogistics (Epic 10 Contract §42, §85, §87, T1004).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

    def test_mandatory_postgresql_eta_vs_delivery_race(self):
        """
        Mandatory PostgreSQL Race:
        Thread A: update ETA
        Thread B: record actual delivery
        Both start from identical initial version=1 using independent DB connections and synchronization barrier.
        Proves:
        - Exactly one authoritative sequence winner.
        - Loser gets StaleVersionError (409 Conflict).
        - No silent lost update.
        - Zero raw 500 errors or unhandled database exceptions.
        """
        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 1)

        target_eta = timezone.now() + timezone.timedelta(days=7)
        target_delivery = timezone.now() + timezone.timedelta(days=8)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_update_eta():
            connection.close()
            try:
                barrier.wait(timeout=10)
                res = update_eta(
                    self.execution.id,
                    expected_version=1,
                    actor=self.supplier_user,
                    eta=target_eta,
                )
                results.append(("eta", res))
            except Exception as exc:
                errors.append(("eta", exc))

        def run_record_delivery():
            connection.close()
            try:
                barrier.wait(timeout=10)
                res = record_delivery(
                    self.execution.id,
                    expected_version=1,
                    actor=self.buyer_owner,
                    actual_delivery_at=target_delivery,
                )
                results.append(("delivery", res))
            except Exception as exc:
                errors.append(("delivery", exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(run_update_eta)
            fut_b = executor.submit(run_record_delivery)
            concurrent.futures.wait([fut_a, fut_b])

        # Exactly 1 success, exactly 1 failure
        self.assertEqual(len(results), 1, f"Expected exactly 1 winner, got {len(results)}. Results: {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 conflict error, got {len(errors)}. Errors: {errors}")

        # The losing error must be StaleVersionError
        loser_op, loser_exc = errors[0]
        self.assertIsInstance(
            loser_exc,
            StaleVersionError,
            f"Expected StaleVersionError (409) for losing operation, got: {type(loser_exc).__name__}: {loser_exc}",
        )

        # Refresh from database and verify version was incremented to 2
        connection.close()
        logistics.refresh_from_db()
        self.assertEqual(logistics.version, 2)

        winner_op, _ = results[0]
        if winner_op == "eta":
            self.assertEqual(logistics.eta, target_eta)
            self.assertIsNone(logistics.actual_delivery_at)
        else:
            self.assertEqual(logistics.actual_delivery_at, target_delivery)
            self.assertIsNone(logistics.eta)

    def test_loading_schedule_vs_loading_update_overlap_race(self):
        """
        PostgreSQL Race:
        Thread A: schedule loading (expected_version=1)
        Thread B: record actual loading (expected_version=1)
        Proves optimistic concurrency prevents lost updates when loading facts are mutated simultaneously.
        """
        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 1)

        now = timezone.now()
        sched_time = now + timezone.timedelta(days=1)
        load_time = now + timezone.timedelta(days=2)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_schedule_loading():
            connection.close()
            try:
                barrier.wait(timeout=10)
                res = schedule_loading(
                    self.execution.id,
                    expected_version=1,
                    actor=self.supplier_user,
                    scheduled_loading_at=sched_time,
                )
                results.append(("schedule", res))
            except Exception as exc:
                errors.append(("schedule", exc))

        def run_record_loading():
            connection.close()
            try:
                barrier.wait(timeout=10)
                res = record_loading(
                    self.execution.id,
                    expected_version=1,
                    actor=self.supplier_user,
                    actual_loading_at=load_time,
                )
                results.append(("loading", res))
            except Exception as exc:
                errors.append(("loading", exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(run_schedule_loading)
            fut_b = executor.submit(run_record_loading)
            concurrent.futures.wait([fut_a, fut_b])

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0][1], StaleVersionError)

        connection.close()
        logistics.refresh_from_db()
        self.assertEqual(logistics.version, 2)

    def test_stale_eta_cannot_overwrite_actual_delivery(self):
        """
        Stale ETA update cannot overwrite actual delivery:
        1. Buyer records actual delivery (increments version 1 -> 2).
        2. Stale ETA update with expected_version=1 is rejected with StaleVersionError.
        3. Attempting to update ETA after delivery is also rejected as invalid operational progression.
        """
        now = timezone.now()

        # Step 1: Record delivery
        record_delivery(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            actual_delivery_at=now,
        )

        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 2)
        self.assertEqual(logistics.actual_delivery_at, now)

        # Step 2: Stale caller tries expected_version=1 -> StaleVersionError
        with self.assertRaises(StaleVersionError):
            update_eta(
                self.execution.id,
                expected_version=1,
                actor=self.supplier_user,
                eta=now + timezone.timedelta(days=1),
            )

        # Step 3: Even with current version=2, ETA cannot be updated after actual delivery
        with self.assertRaises(ExecutionValidationError) as ctx:
            update_eta(
                self.execution.id,
                expected_version=2,
                actor=self.supplier_user,
                eta=now + timezone.timedelta(days=1),
            )
        self.assertIn("actual delivery has already been recorded", str(ctx.exception))
