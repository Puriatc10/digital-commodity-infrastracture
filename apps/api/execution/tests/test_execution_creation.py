import concurrent.futures
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus
from execution.exceptions import ExecutionValidationError
from execution.models.execution import Execution
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    publish_version,
    retire_version,
)
from execution.tests.base import BaseExecutionTestCase, BaseExecutionTransactionTestCase


class ExecutionCreationTests(BaseExecutionTestCase):
    """Tests for idempotent Execution creation and PostgreSQL concurrency races (Epic 10 Contract §7, T1003)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.client = APIClient()

    def test_idempotent_execution_creation_service(self):
        """create_or_get_execution_for_deal creates execution on first call, returns existing on second."""
        exec1 = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.assertIsNotNone(exec1.id)
        self.assertEqual(exec1.deal_id, self.deal.id)
        self.assertEqual(exec1.status, ExecutionStatus.OPEN)
        self.assertEqual(exec1.workflow_template_version_id, self.bitumen_v1.id)

        # Count executions and milestones
        exec_count = Execution.objects.filter(deal=self.deal).count()
        milestone_count = ExecutionMilestone.objects.filter(execution=exec1).count()
        self.assertEqual(exec_count, 1)
        self.assertEqual(milestone_count, 10)

        # Second call returns existing execution without creating duplicates
        exec2 = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.assertEqual(exec1.id, exec2.id)
        self.assertEqual(Execution.objects.filter(deal=self.deal).count(), 1)
        self.assertEqual(ExecutionMilestone.objects.filter(execution=exec1).count(), 10)

    def test_execution_creation_api_idempotent(self):
        """API POST /api/deals/{deal_id}/execution/ is idempotent."""
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{self.deal.id}/execution/"

        # 1. First call: materializes execution
        resp1 = self.client.post(url, {}, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        data1 = resp1.json()
        exec_id = data1["id"]
        self.assertEqual(data1["status"], ExecutionStatus.OPEN)
        self.assertEqual(len(data1["milestones"]), 10)

        # 2. Second call: returns existing execution
        resp2 = self.client.post(url, {}, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        data2 = resp2.json()
        self.assertEqual(data2["id"], exec_id)
        self.assertEqual(len(data2["milestones"]), 10)

        # 3. GET /api/deals/{deal_id}/execution/
        resp_get = self.client.get(url)
        self.assertEqual(resp_get.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_get.json()["id"], exec_id)

    def test_cannot_create_execution_with_retired_workflow_version(self):
        """Retired workflow versions cannot be selected for new execution."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=False)
        retire_version(v1, actor=self.operator_user)

        with self.assertRaises(ExecutionValidationError):
            create_or_get_execution_for_deal(
                deal_id=self.deal.id,
                workflow_template_version_id=v1.id,
                actor=self.operator_user,
            )


class ExecutionCreationConcurrencyTests(BaseExecutionTransactionTestCase):
    """Real PostgreSQL concurrency tests for Execution creation (Epic 10 Contract §7, T1003)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)

    def test_real_postgresql_concurrent_creation_race(self):
        """
        Real PostgreSQL race:
        create Execution vs create Execution simultaneously.
        Expected: exactly 1 Execution, 1 milestone graph, 0 duplicate rows, 0 500 errors.
        """
        deal = self.create_sample_deal()
        results = []
        errors = []

        def run_create():
            connection.close()
            try:
                ex = create_or_get_execution_for_deal(
                    deal_id=deal.id,
                    actor=self.operator_user,
                )
                return ex.id
            except Exception as e:
                errors.append(e)
                return None
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_create) for _ in range(4)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res:
                    results.append(res)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        # All threads must receive the EXACT same execution ID
        self.assertEqual(len(set(results)), 1)

        # DB must have exactly 1 Execution row and 10 milestones
        self.assertEqual(Execution.objects.filter(deal=deal).count(), 1)
        created_exec = Execution.objects.get(deal=deal)
        self.assertEqual(ExecutionMilestone.objects.filter(execution=created_exec).count(), 10)

