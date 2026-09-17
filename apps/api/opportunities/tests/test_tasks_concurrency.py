import datetime
from decimal import Decimal
import threading
import time

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment, User
from opportunities.exceptions import InvalidTransitionError
from opportunities.models import (
    OpportunityDirection,
    OpportunitySource,
    OpportunityTaskStatus,
)
from opportunities.services import (
    cancel_opportunity_task,
    complete_opportunity_task,
    create_opportunity,
    create_opportunity_task,
)
from organizations.models import Organization, OrganizationCapability


class OpportunityTaskConcurrencyTests(TransactionTestCase):
    """
    PostgreSQL multi-threaded concurrency and race condition tests for Opportunity Tasks.

    Uses real database transactions across separate worker threads with synchronization
    barriers to force concurrent execution against row-level locks.
    """

    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_task_concurrency",
            name_en="Bitumen Task Concurrency",
            name_fa="قیر همزمانی تسک",
        )
        self.buyer_org = Organization.objects.create(name="Concurrent Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.operator = User.objects.create_user(
            email="operator_concurrency@platform.com", password="password"
        )
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            source=OpportunitySource.OPERATOR_SOURCING,
            created_by=self.operator,
        )

    def test_concurrent_completion_race(self):
        """
        Two concurrent threads race to complete the same OPEN Opportunity Task.
        Under PostgreSQL row lock (select_for_update):
        - Exactly one thread succeeds.
        - The competing thread raises InvalidTransitionError.
        - completed_at remains stable.
        - Final state: status=COMPLETED.
        """
        task = create_opportunity_task(
            self.opp.id,
            title="Concurrent Complete Task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        barrier = threading.Barrier(2)
        results = {}

        def worker(name):
            try:
                barrier.wait()
                time.sleep(0.01)
                complete_opportunity_task(self.opp.id, task.id, actor=self.operator)
                results[name] = "success"
            except Exception as exc:
                results[name] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=("t1",))
        t2 = threading.Thread(target=worker, args=("t2",))

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got: {results}")
        self.assertIsInstance(results[failures[0]], InvalidTransitionError)

        task.refresh_from_db()
        self.assertEqual(task.status, OpportunityTaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_concurrent_complete_vs_cancel_race(self):
        """
        Two concurrent threads race: one attempts to complete, the other attempts to cancel.
        Under PostgreSQL row lock (select_for_update):
        - Exactly one authoritative transition succeeds.
        - The competing thread raises InvalidTransitionError.
        - No inconsistent or half-committed state.
        """
        task = create_opportunity_task(
            self.opp.id,
            title="Complete vs Cancel Task",
            due_at=timezone.now() + datetime.timedelta(days=1),
            actor=self.operator,
        )

        barrier = threading.Barrier(2)
        results = {}

        def worker_complete():
            try:
                barrier.wait()
                time.sleep(0.01)
                complete_opportunity_task(self.opp.id, task.id, actor=self.operator)
                results["complete"] = "success"
            except Exception as exc:
                results["complete"] = exc
            finally:
                connection.close()

        def worker_cancel():
            try:
                barrier.wait()
                time.sleep(0.01)
                cancel_opportunity_task(self.opp.id, task.id, actor=self.operator)
                results["cancel"] = "success"
            except Exception as exc:
                results["cancel"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=worker_complete)
        t2 = threading.Thread(target=worker_cancel)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got: {results}")
        self.assertIsInstance(results[failures[0]], InvalidTransitionError)

        task.refresh_from_db()
        self.assertIn(task.status, [OpportunityTaskStatus.COMPLETED, OpportunityTaskStatus.CANCELLED])
        if task.status == OpportunityTaskStatus.COMPLETED:
            self.assertIsNotNone(task.completed_at)
        else:
            self.assertIsNone(task.completed_at)
