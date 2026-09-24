import threading
from django.db import connection, close_old_connections
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import InspectionResult, InspectionStatus
from execution.exceptions import (
    ExecutionValidationError,
    InvalidInspectionTransitionError,
    StaleVersionError,
)
from execution.models.inspection import ExecutionInspection
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    cancel_inspection,
    complete_inspection,
    create_or_get_execution_for_deal,
    schedule_inspection,
)
from execution.tests.base import BaseExecutionTransactionTestCase


class InspectionConcurrencyTests(BaseExecutionTransactionTestCase):
    """
    Tests for optimistic concurrency control and real PostgreSQL thread races (Epic 10 Contract §85, T1005).
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

    def test_stale_expected_version_rejected_with_409(self):
        """Passing outdated expected_version returns 409 Conflict via API and raises StaleVersionError."""
        now = timezone.now()

        # Step 1: schedule inspection -> version becomes 2
        schedule_inspection(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_at=now,
        )
        insp = ExecutionInspection.objects.get(execution=self.execution)
        self.assertEqual(insp.version, 2)

        # Step 2: Stale caller uses expected_version=1
        with self.assertRaises(StaleVersionError):
            complete_inspection(
                self.execution.id,
                expected_version=1,
                actor=self.supplier_user,
                inspection_at=now,
                result=InspectionResult.PASS,
            )

        # Step 3: Test via API returns 409 Conflict
        self.client.force_authenticate(user=self.supplier_user)
        url = f"/api/execution/{self.execution.id}/inspection/complete/"
        resp = self.client.post(
            url,
            {
                "expected_version": 1,
                "inspection_at": now.isoformat(),
                "result": InspectionResult.PASS,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("conflict", resp.data["detail"].lower())

    def test_invalid_expected_version_rejected_with_400(self):
        """Negative, non-integer, or missing expected_version raises ExecutionValidationError."""
        now = timezone.now()
        for invalid in [0, -1, "one", None]:
            with self.assertRaises(ExecutionValidationError):
                schedule_inspection(
                    self.execution.id,
                    expected_version=invalid,
                    actor=self.supplier_user,
                    scheduled_at=now,
                )

    def test_real_postgresql_race_complete_vs_cancel(self):
        """
        Real PostgreSQL race: complete_inspection vs cancel_inspection.

        Expected:
        - Both callers start with expected_version=1.
        - Exactly one authoritative final transition commits (COMPLETED or CANCELLED).
        - Stale/losing caller receives controlled StaleVersionError (or InvalidInspectionTransitionError).
        - No lost writes, no DB deadlocks, no 500 server errors.
        - Final aggregate version is exactly 2.
        """
        now = timezone.now()
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_complete():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                insp = complete_inspection(
                    self.execution.id,
                    expected_version=1,
                    actor=self.supplier_user,
                    inspection_at=now,
                    result=InspectionResult.PASS,
                    agency="SGS Race",
                )
                results.append(("complete", insp))
            except Exception as e:
                errors.append(("complete", e))
            finally:
                connection.close()

        def run_cancel():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                insp = cancel_inspection(
                    self.execution.id,
                    expected_version=1,
                    actor=self.supplier_user,
                    notes="Cancelled concurrently.",
                )
                results.append(("cancel", insp))
            except Exception as e:
                errors.append(("cancel", e))
            finally:
                connection.close()

        t1 = threading.Thread(target=run_complete)
        t2 = threading.Thread(target=run_cancel)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # Assert exactly one winner and one loser
        self.assertEqual(len(results), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 loser, got: {errors}")

        winner_action, winner_obj = results[0]
        loser_action, loser_exc = errors[0]

        # The losing error must be StaleVersionError or InvalidInspectionTransitionError (controlled conflict)
        self.assertIn(
            type(loser_exc),
            [StaleVersionError, InvalidInspectionTransitionError],
            f"Expected controlled conflict for losing operation, got: {type(loser_exc).__name__}: {loser_exc}",
        )

        # Final record state verification
        final_insp = ExecutionInspection.objects.get(execution=self.execution)
        self.assertEqual(final_insp.version, 2)
        if winner_action == "complete":
            self.assertEqual(final_insp.status, InspectionStatus.COMPLETED)
            self.assertEqual(final_insp.result, InspectionResult.PASS)
        else:
            self.assertEqual(final_insp.status, InspectionStatus.CANCELLED)
            self.assertEqual(final_insp.result, InspectionResult.UNKNOWN)
