import threading

from django.db import close_old_connections, connection
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import PaymentStatus
from execution.exceptions import (
    ExecutionValidationError,
    InvalidPaymentTransitionError,
    StaleVersionError,
)
from execution.models.payment import ExecutionPayment
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    confirm_payment,
    create_or_get_execution_for_deal,
    report_payment,
)
from execution.tests.base import BaseExecutionTransactionTestCase


class PaymentConcurrencyTests(BaseExecutionTransactionTestCase):
    """
    Tests for optimistic concurrency control and real PostgreSQL thread races (Epic 10 Contract §88, T1006).
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
        # 1. Report payment -> version becomes 2
        report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            reference="REF-001",
        )
        pmt = ExecutionPayment.objects.get(execution=self.execution)
        self.assertEqual(pmt.version, 2)
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)

        # 2. Stale caller attempts to confirm with expected_version=1
        with self.assertRaises(StaleVersionError):
            confirm_payment(
                self.execution.id,
                expected_version=1,
                actor=self.operator_user,
            )

        # 3. Test via API returns 409 Conflict
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/execution/{self.execution.id}/payment/confirm/"
        resp = self.client.post(
            url,
            {"expected_version": 1, "reference": "CONF-STALE"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("conflict", resp.data["detail"].lower())

    def test_invalid_expected_version_rejected_with_400(self):
        """Negative, non-integer, or missing expected_version raises ExecutionValidationError."""
        for invalid in [0, -1, "one", None, False, True]:
            with self.assertRaises(ExecutionValidationError):
                report_payment(
                    self.execution.id,
                    expected_version=invalid,
                    actor=self.buyer_owner,
                )

    def test_real_postgresql_race_report_vs_confirm(self):
        """
        Mandatory Real PostgreSQL race: report_payment vs confirm_payment from overlapping state.

        Scenario:
        - Initial state: status=EXPECTED, version=1.
        - Request A: report_payment(expected_version=1)
        - Request B: confirm_payment(expected_version=1)
        - Both execute concurrently across separate PostgreSQL connections via threading.Barrier(2).

        Invariants verified:
        - Legal ordering is preserved: EXPECTED -> REPORTED -> CONFIRMED.
        - Direct jump from EXPECTED to CONFIRMED is impossible.
        - Exactly one authoritative transition commits:
          * Either report wins lock first -> completes to REPORTED (v=2), and confirm fails with StaleVersionError (409)
          * Or confirm wins lock first -> fails immediately with InvalidPaymentTransitionError (status=EXPECTED cannot be confirmed), and report completes to REPORTED (v=2)
        - No lost update.
        - No impossible CONFIRMED state without prior REPORTED state.
        - No raw 500 error; stale or invalid caller controlled.
        """
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_report():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                pmt = report_payment(
                    self.execution.id,
                    expected_version=1,
                    actor=self.buyer_owner,
                    reference="RACE-REPORT-001",
                )
                results.append(("report", pmt))
            except Exception as e:
                errors.append(("report", e))
            finally:
                connection.close()

        def run_confirm():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                pmt = confirm_payment(
                    self.execution.id,
                    expected_version=1,
                    actor=self.operator_user,
                    reference="RACE-CONFIRM-001",
                )
                results.append(("confirm", pmt))
            except Exception as e:
                errors.append(("confirm", e))
            finally:
                connection.close()

        t1 = threading.Thread(target=run_report)
        t2 = threading.Thread(target=run_confirm)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # Reconnect main test thread
        close_old_connections()
        pmt = ExecutionPayment.objects.get(execution=self.execution)

        # Assertions
        # 1. Confirm must NEVER have succeeded directly from EXPECTED state
        confirm_successes = [r for r in results if r[0] == "confirm"]
        self.assertEqual(len(confirm_successes), 0, "confirm_payment should never succeed from EXPECTED state.")

        # 2. Report should have succeeded
        report_successes = [r for r in results if r[0] == "report"]
        self.assertEqual(len(report_successes), 1, "report_payment should succeed.")

        # 3. Final state is REPORTED with version 2
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)
        self.assertEqual(pmt.version, 2)
        self.assertEqual(pmt.reported_by, self.buyer_owner)
        self.assertIsNone(pmt.confirmed_at)
        self.assertIsNone(pmt.confirmed_by)

        # 4. Confirm error must be either StaleVersionError or InvalidPaymentTransitionError (controlled 409 or 400, never 500)
        confirm_errors = [e for e in errors if e[0] == "confirm"]
        self.assertEqual(len(confirm_errors), 1)
        err = confirm_errors[0][1]
        self.assertTrue(
            isinstance(err, (StaleVersionError, InvalidPaymentTransitionError)),
            f"Expected StaleVersionError or InvalidPaymentTransitionError, got {type(err)}: {err}",
        )

    def test_real_postgresql_race_concurrent_confirms(self):
        """
        Real PostgreSQL race: concurrent confirm_payment requests from REPORTED state.

        Expected:
        - Both callers start with expected_version=2 on REPORTED payment.
        - Exactly one caller successfully transitions to CONFIRMED (version=3).
        - Stale caller receives StaleVersionError (HTTP 409).
        - No lost writes, no corrupted state.
        """
        # Set up payment in REPORTED state (v=2)
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)
        pmt = ExecutionPayment.objects.get(execution=self.execution)
        self.assertEqual(pmt.version, 2)
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def run_confirm_a():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                p = confirm_payment(
                    self.execution.id,
                    expected_version=2,
                    actor=self.operator_user,
                    reference="CONFIRM-A",
                )
                results.append(("confirm_a", p))
            except Exception as e:
                errors.append(("confirm_a", e))
            finally:
                connection.close()

        def run_confirm_b():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                p = confirm_payment(
                    self.execution.id,
                    expected_version=2,
                    actor=self.operator_user,
                    reference="CONFIRM-B",
                )
                results.append(("confirm_b", p))
            except Exception as e:
                errors.append(("confirm_b", e))
            finally:
                connection.close()

        t1 = threading.Thread(target=run_confirm_a)
        t2 = threading.Thread(target=run_confirm_b)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        close_old_connections()
        pmt = ExecutionPayment.objects.get(execution=self.execution)

        # Exactly 1 success, 1 StaleVersionError
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0][1], StaleVersionError)

        self.assertEqual(pmt.status, PaymentStatus.CONFIRMED)
        self.assertEqual(pmt.version, 3)
        self.assertEqual(pmt.confirmed_by, self.operator_user)
        self.assertIsNotNone(pmt.confirmed_at)
