import concurrent.futures
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import MilestoneStatus
from execution.exceptions import (
    MilestoneAlreadyCompletedError,
    MilestonePrerequisiteUnmetError,
    StaleVersionError,
)
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    complete_milestone,
    create_or_get_execution_for_deal,
    start_milestone,
)
from execution.tests.base import BaseExecutionTestCase, BaseExecutionTransactionTestCase


class MilestoneGuardsAndConcurrencyTests(BaseExecutionTestCase):
    """Tests for milestone transition guards, optimistic concurrency, and PostgreSQL races (Epic 10 Contract §17, §18, §85, §86, T1003)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_prerequisites_cannot_be_bypassed(self):
        """Milestone cannot be started or completed if prerequisites are not COMPLETED."""
        # Milestone 2 is CONTRACT_SIGNED, Milestone 3 is PAYMENT_REPORTED
        m_payment = ExecutionMilestone.objects.get(execution=self.execution, definition__code="PAYMENT_REPORTED")

        # CONTRACT_SIGNED is PENDING, so completing PAYMENT_REPORTED must fail
        with self.assertRaises(MilestonePrerequisiteUnmetError):
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_payment.id,
                expected_version=m_payment.version,
                actor=self.operator_user,
            )

        # Start PAYMENT_REPORTED also fails prerequisites
        with self.assertRaises(MilestonePrerequisiteUnmetError):
            start_milestone(
                execution_id=self.execution.id,
                milestone_id=m_payment.id,
                expected_version=m_payment.version,
                actor=self.operator_user,
            )

    def test_stale_expected_version_rejected_with_409(self):
        """Providing outdated expected_version returns 409 Conflict via API and raises StaleVersionError."""
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")

        # Direct service call with bad version
        with self.assertRaises(StaleVersionError):
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_contract.id,
                expected_version=99,
                actor=self.operator_user,
            )

        # API call with stale version
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/execution/{self.execution.id}/milestones/{m_contract.id}/complete/"
        resp = self.client.post(url, {"expected_version": 99}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_completed_milestone_immutable_no_reopen(self):
        """Completed milestone rejects any subsequent start, block, skip, or re-complete action."""
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actor=self.operator_user,
        )
        m_contract.refresh_from_db()

        # Re-complete fails
        with self.assertRaises(MilestoneAlreadyCompletedError):
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_contract.id,
                expected_version=2,
                actor=self.operator_user,
            )

        # Start fails
        with self.assertRaises(MilestoneAlreadyCompletedError):
            start_milestone(
                execution_id=self.execution.id,
                milestone_id=m_contract.id,
                expected_version=2,
                actor=self.operator_user,
            )

    def test_milestone_transition_api_flow(self):
        """API flow: PENDING -> IN_PROGRESS -> COMPLETED."""
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")
        self.client.force_authenticate(user=self.operator_user)

        # 1. Start milestone
        url_start = f"/api/execution/{self.execution.id}/milestones/{m_contract.id}/start/"
        resp_start = self.client.post(url_start, {"expected_version": 1, "notes": "Drafting contract"}, format="json")
        self.assertEqual(resp_start.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_start.json()["status"], MilestoneStatus.IN_PROGRESS)
        self.assertEqual(resp_start.json()["version"], 2)

        # 2. Complete milestone
        url_complete = f"/api/execution/{self.execution.id}/milestones/{m_contract.id}/complete/"
        act_time = timezone.now().isoformat()
        resp_comp = self.client.post(
            url_complete,
            {"expected_version": 2, "actual_at": act_time, "notes": "Contract signed by both parties"},
            format="json",
        )
        self.assertEqual(resp_comp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_comp.json()["status"], MilestoneStatus.COMPLETED)
        self.assertEqual(resp_comp.json()["version"], 3)


class MilestoneConcurrencyTests(BaseExecutionTransactionTestCase):
    """Real PostgreSQL multi-threaded concurrency race tests for milestone actions."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

    def test_real_postgresql_concurrent_completion_race(self):
        """
        Real PostgreSQL race:
        complete same milestone vs complete same milestone simultaneously.
        Expected: exactly 1 authoritative completion, loser gets 409 / StaleVersionError, 0 raw DB errors.
        """
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")
        success_count = 0
        conflict_count = 0
        errors = []

        def run_complete():
            connection.close()
            try:
                complete_milestone(
                    execution_id=self.execution.id,
                    milestone_id=m_contract.id,
                    expected_version=1,
                    actor=self.operator_user,
                )
                return "SUCCESS"
            except (StaleVersionError, MilestoneAlreadyCompletedError):
                return "CONFLICT"
            except Exception as e:
                errors.append(e)
                return "ERROR"
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_complete) for _ in range(2)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res == "SUCCESS":
                    success_count += 1
                elif res == "CONFLICT":
                    conflict_count += 1

        self.assertEqual(errors, [])
        self.assertEqual(success_count, 1)
        self.assertEqual(conflict_count, 1)

        # Assert authoritative completion in DB
        m_contract.refresh_from_db()
        self.assertEqual(m_contract.status, MilestoneStatus.COMPLETED)
        self.assertEqual(m_contract.version, 2)
        self.assertIsNotNone(m_contract.actual_at)
        self.assertEqual(m_contract.completed_by, self.operator_user)

