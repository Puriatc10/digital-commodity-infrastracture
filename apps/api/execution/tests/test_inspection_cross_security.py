from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus, InspectionResult
from execution.exceptions import CrossObjectIntegrityError, ExecutionClosedError
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    cancel_inspection,
    complete_inspection,
    create_or_get_execution_for_deal,
    mark_inspection_not_required,
    schedule_inspection,
)
from execution.tests.base import BaseExecutionTestCase


class InspectionCrossSecurityAndClosedTests(BaseExecutionTestCase):
    """
    Tests for cross-object integrity protection and closed execution safeguards (T1005).
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
        now = timezone.now()

        # Try to schedule execution_1 with foreign deal_2 ID
        with self.assertRaises(CrossObjectIntegrityError):
            schedule_inspection(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
                scheduled_at=now,
                deal_id=self.deal_2.id,
            )

        # Via API returns 400 Bad Request
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/execution/{self.execution_1.id}/inspection/schedule/"
        resp = self.client.post(
            url,
            {
                "expected_version": 1,
                "scheduled_at": now.isoformat(),
                "deal_id": str(self.deal_2.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("referenced Deal", resp.data["detail"])

    def test_closed_execution_rejects_inspection_mutations(self):
        """Mutations on an already CLOSED execution are rejected with ExecutionClosedError."""
        now = timezone.now()

        # Manually close execution_1
        self.execution_1.status = ExecutionStatus.CLOSED
        self.execution_1.closed_at = now
        self.execution_1.save()

        # 1. schedule rejected
        with self.assertRaises(ExecutionClosedError):
            schedule_inspection(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
                scheduled_at=now,
            )

        # 2. complete rejected
        with self.assertRaises(ExecutionClosedError):
            complete_inspection(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
                inspection_at=now,
                result=InspectionResult.PASS,
            )

        # 3. cancel rejected
        with self.assertRaises(ExecutionClosedError):
            cancel_inspection(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
            )

        # 4. mark not required rejected
        with self.assertRaises(ExecutionClosedError):
            mark_inspection_not_required(
                execution_id=self.execution_1.id,
                expected_version=1,
                actor=self.operator_user,
            )
