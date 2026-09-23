import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus
from execution.exceptions import CrossObjectIntegrityError, ExecutionClosedError, ExecutionNotFoundError
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    confirm_payment,
    create_or_get_execution_for_deal,
    get_or_create_execution_payment,
    report_payment,
)
from execution.tests.base import BaseExecutionTestCase


class PaymentCrossSecurityAndClosedTests(BaseExecutionTestCase):
    """
    Tests for cross-object integrity protection and closed execution safeguards (Contract §57, §59, T1006).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal_1 = self.create_sample_deal()
        self.execution_1 = create_or_get_execution_for_deal(
            deal_id=self.deal_1.id,
            actor=self.operator_user,
        )
        self.deal_2 = self.create_sample_deal()
        self.execution_2 = create_or_get_execution_for_deal(
            deal_id=self.deal_2.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_cross_deal_integrity_rejected(self):
        """Cross-referencing mismatched execution and deal is rejected with CrossObjectIntegrityError."""
        # 1. get_or_create with mismatched deal_id
        with self.assertRaises(CrossObjectIntegrityError):
            get_or_create_execution_payment(
                execution_id=self.execution_1.id,
                deal_id=self.deal_2.id,
            )

        # 2. report_payment with mismatched deal_id
        with self.assertRaises(CrossObjectIntegrityError):
            report_payment(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.buyer_owner,
                deal_id=self.deal_2.id,
            )

        # 3. Via API returns 400 Bad Request
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/execution/{self.execution_1.id}/payment/report/"
        resp = self.client.post(
            url,
            {
                "expected_version": 1,
                "deal_id": str(self.deal_2.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("referenced Deal", resp.data["detail"])

    def test_closed_execution_rejects_payment_mutations(self):
        """Mutations on an already CLOSED execution are rejected with ExecutionClosedError."""
        now = timezone.now()

        # Close execution_1
        self.execution_1.status = ExecutionStatus.CLOSED
        self.execution_1.closed_at = now
        self.execution_1.save()

        # 1. report rejected
        with self.assertRaises(ExecutionClosedError):
            report_payment(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.buyer_owner,
            )

        # 2. confirm rejected
        with self.assertRaises(ExecutionClosedError):
            confirm_payment(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
            )

        # 3. API report returns 400 Bad Request
        self.client.force_authenticate(user=self.buyer_owner)
        resp = self.client.post(
            f"/api/execution/{self.execution_1.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already CLOSED", resp.data["detail"])

        # 4. API confirm returns 400 Bad Request
        self.client.force_authenticate(user=self.operator_user)
        resp_conf = self.client.post(
            f"/api/execution/{self.execution_1.id}/payment/confirm/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_conf.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already CLOSED", resp_conf.data["detail"])

    def test_nonexistent_execution_returns_404(self):
        """Requests for a non-existent execution ID raise ExecutionNotFoundError / 404."""
        random_id = uuid.uuid4()
        with self.assertRaises(ExecutionNotFoundError):
            report_payment(
                execution_id=random_id,
                expected_version=1,
                actor=self.buyer_owner,
            )

        self.client.force_authenticate(user=self.buyer_owner)
        resp = self.client.get(f"/api/execution/{random_id}/payment/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
