import datetime
from decimal import Decimal
import threading
import time

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment
from opportunities.exceptions import (
    InvalidTransitionError,
    StaleVersionError,
)
from opportunities.models import (
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity, update_opportunity
from opportunities.services_lifecycle import (
    put_opportunity_on_hold,
    qualify_opportunity,
)
from organizations.models import Organization, OrganizationCapability

User = get_user_model()


class OpportunityQualificationConcurrencyTests(TransactionTestCase):
    """
    Mandatory PostgreSQL concurrency tests for Opportunity qualification (T0608).

    Verifies race safety using real PostgreSQL connections and synchronization barriers:
    1. Qualify vs Qualify (same Opportunity, same version)
    2. Qualify vs Competing Lifecycle Transition (Qualify vs Put on Hold)
    3. Qualify vs Opportunity Update (stale read detection)
    """

    def setUp(self):
        self.operator = User.objects.create_user(
            email="operator_concurrency@test.local", password="password"
        )
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_concurrency_qual",
            name_en="Bitumen Concurrency Qual",
            name_fa="قیر همزمانی صلاحیت",
            is_active=True,
        )
        self.buyer_org = Organization.objects.create(name="Concurrent Buyer Corp")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            unit="MT",
            indicative_price=Decimal("360.00"),
            currency="USD",
            geography="Jebel Ali, UAE",
            delivery_window_start=datetime.date(2026, 12, 1),
            delivery_window_end=datetime.date(2026, 12, 31),
            payment_terms="100% LC at sight",
            source=OpportunitySource.OPERATOR_SOURCING,
        )

    # -------------------------------------------------------------------------
    # 1. Qualify vs Qualify Race
    # -------------------------------------------------------------------------

    def test_duplicate_qualify_race(self):
        """
        Two concurrent threads race to qualify the same Opportunity with expected_version=1.
        Under PostgreSQL row lock (select_for_update):
        - Exactly one thread succeeds and advances version to 2.
        - The competing thread raises StaleVersionError.
        """
        barrier = threading.Barrier(2)
        results = {}

        def worker(name):
            try:
                barrier.wait()
                time.sleep(0.01)
                qualify_opportunity(self.opp.id, expected_version=1, actor=self.operator)
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
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(self.opp.version, 2)
        self.assertIsNotNone(self.opp.qualified_at)

    # -------------------------------------------------------------------------
    # 2. Qualify vs Competing Lifecycle Transition Race
    # -------------------------------------------------------------------------

    def test_competing_transition_race_qualify_vs_hold(self):
        """
        Captured opportunity faces competing valid actions: Qualify vs Put on Hold.
        Thread 1 attempts qualify (expected_version=1).
        Thread 2 attempts put_on_hold (expected_version=1).
        Under row locking:
        - Exactly one thread succeeds.
        - The competing thread raises StaleVersionError or InvalidTransitionError.
        - Aggregate version advances to exactly 2.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_qualify():
            try:
                barrier.wait()
                time.sleep(0.01)
                qualify_opportunity(self.opp.id, expected_version=1, actor=self.operator)
                results["qualify"] = "success"
            except Exception as exc:
                results["qualify"] = exc
            finally:
                connection.close()

        def thread_hold():
            try:
                barrier.wait()
                time.sleep(0.01)
                put_opportunity_on_hold(
                    self.opp.id,
                    expected_version=1,
                    reason="Competing hold test",
                    actor=self.operator,
                )
                results["hold"] = "success"
            except Exception as exc:
                results["hold"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_qualify)
        t2 = threading.Thread(target=thread_hold)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got: {results}")

        loser_exc = results[failures[0]]
        self.assertTrue(
            isinstance(loser_exc, (StaleVersionError, InvalidTransitionError)),
            f"Expected concurrency or transition error, got {type(loser_exc)}: {loser_exc}",
        )

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.version, 2)
        self.assertIn(self.opp.status, [OpportunityStatus.QUALIFIED, OpportunityStatus.ON_HOLD])

    # -------------------------------------------------------------------------
    # 3. Qualify vs Opportunity Update (Stale Read Protection)
    # -------------------------------------------------------------------------

    def test_qualify_vs_update_race_guards_stale_read(self):
        """
        Proves qualification cannot validate stale state and qualify the wrong persisted version.
        Thread A: reads Opportunity at version 1 and prepares qualification with expected_version=1.
        Thread B: concurrently modifies Opportunity data, incrementing version to 2.
        Thread A's qualification attempt with expected_version=1 must be rejected with StaleVersionError.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_qualify():
            try:
                barrier.wait()
                time.sleep(0.02)  # Allow Thread B to lock and commit update first
                qualify_opportunity(self.opp.id, expected_version=1, actor=self.operator)
                results["qualify"] = "success"
            except Exception as exc:
                results["qualify"] = exc
            finally:
                connection.close()

        def thread_update():
            try:
                barrier.wait()
                update_opportunity(
                    self.opp,
                    data={"quantity": Decimal("2500.000")},
                    expected_version=1,
                )
                results["update"] = "success"
            except Exception as exc:
                results["update"] = exc
            finally:
                connection.close()

        t_upd = threading.Thread(target=thread_update)
        t_qual = threading.Thread(target=thread_qualify)

        t_upd.start()
        t_qual.start()

        t_upd.join(timeout=10)
        t_qual.join(timeout=10)

        self.assertEqual(results.get("update"), "success")
        self.assertIsInstance(results.get("qualify"), StaleVersionError)

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.version, 2)
        self.assertEqual(self.opp.quantity, Decimal("2500.000"))
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertIsNone(self.opp.qualified_at)
