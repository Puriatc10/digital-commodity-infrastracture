from decimal import Decimal
import threading
import time

from django.db import connection
from django.test import TransactionTestCase

from commodities.models import CommodityDefinition
from opportunities.exceptions import (
    InvalidTransitionError,
    StaleVersionError,
)
from opportunities.models import (
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity
from opportunities.services_lifecycle import (
    mark_opportunity_contacted,
    put_opportunity_on_hold,
    qualify_opportunity,
    reject_opportunity,
    resume_opportunity,
)
from organizations.models import Organization, OrganizationCapability


class OpportunityLifecycleConcurrencyTests(TransactionTestCase):
    """
    PostgreSQL multi-threaded concurrency and race condition tests for Opportunity lifecycle.

    Uses real database transactions across separate worker threads with synchronization
    barriers to force concurrent execution against row-level locks.
    """

    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_concurrency",
            name_en="Bitumen Concurrency",
            name_fa="قیر همزمانی",
        )
        self.buyer_org = Organization.objects.create(name="Concurrent Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            source=OpportunitySource.OPERATOR_SOURCING,
        )

    # -------------------------------------------------------------------------
    # 1. Duplicate Action Race: Two concurrent threads attempt same transition
    # -------------------------------------------------------------------------

    def test_duplicate_contact_race(self):
        """
        Two concurrent threads race to mark the same Captured Opportunity as Contacted (expected_version=1).
        Under PostgreSQL row lock (select_for_update):
        - Exactly one thread succeeds.
        - The competing thread raises StaleVersionError.
        - Final state: status=Contacted, version=2.
        """
        barrier = threading.Barrier(2)
        results = {}

        def worker(name):
            try:
                barrier.wait()
                time.sleep(0.01)
                mark_opportunity_contacted(self.opp.id, expected_version=1)
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
        self.assertEqual(self.opp.status, OpportunityStatus.CONTACTED)
        self.assertEqual(self.opp.version, 2)
        self.assertIsNotNone(self.opp.contacted_at)

    # -------------------------------------------------------------------------
    # 2. Competing Valid Transitions Race
    # -------------------------------------------------------------------------

    def test_competing_transitions_race_contact_vs_qualify(self):
        """
        Captured opportunity has two valid exits: Contacted and Qualified.
        Thread 1 attempts mark_contacted (expected_version=1).
        Thread 2 attempts qualify (expected_version=1).
        Under row locking:
        - Exactly one thread succeeds.
        - The other fails with StaleVersionError or InvalidTransitionError.
        - Final version is 2, single authoritative winner.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_contact():
            try:
                barrier.wait()
                time.sleep(0.01)
                mark_opportunity_contacted(self.opp.id, expected_version=1)
                results["contact"] = "success"
            except Exception as exc:
                results["contact"] = exc
            finally:
                connection.close()

        def thread_qualify():
            try:
                barrier.wait()
                time.sleep(0.01)
                qualify_opportunity(self.opp.id, expected_version=1)
                results["qualify"] = "success"
            except Exception as exc:
                results["qualify"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_contact)
        t2 = threading.Thread(target=thread_qualify)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got: {results}")
        self.assertTrue(isinstance(results[failures[0]], (StaleVersionError, InvalidTransitionError)))

        self.opp.refresh_from_db()
        self.assertIn(self.opp.status, (OpportunityStatus.CONTACTED, OpportunityStatus.QUALIFIED))
        self.assertEqual(self.opp.version, 2)

    # -------------------------------------------------------------------------
    # 3. Terminal vs Resume Race
    # -------------------------------------------------------------------------

    def test_terminal_vs_resume_race_on_hold(self):
        """
        Opportunity is placed On Hold (version=2).
        Thread 1 attempts to resume() (expected_version=2).
        Thread 2 attempts to reject() (expected_version=2).
        Under row locking:
        - Exactly one succeeds.
        - The other fails with StaleVersionError (or InvalidTransitionError if stale check evaluates later).
        - Final version is 3. No lost updates or corrupt intermediate state.
        """
        held = put_opportunity_on_hold(self.opp.id, expected_version=1, reason="Temporary hold")
        self.assertEqual(held.version, 2)
        self.assertEqual(held.status, OpportunityStatus.ON_HOLD)

        barrier = threading.Barrier(2)
        results = {}

        def thread_resume():
            try:
                barrier.wait()
                time.sleep(0.01)
                resume_opportunity(self.opp.id, expected_version=2)
                results["resume"] = "success"
            except Exception as exc:
                results["resume"] = exc
            finally:
                connection.close()

        def thread_reject():
            try:
                barrier.wait()
                time.sleep(0.01)
                reject_opportunity(self.opp.id, expected_version=2, reason="Terminated during hold")
                results["reject"] = "success"
            except Exception as exc:
                results["reject"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_resume)
        t2 = threading.Thread(target=thread_reject)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got: {results}")
        self.assertTrue(isinstance(results[failures[0]], (StaleVersionError, InvalidTransitionError)))

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.version, 3)
        self.assertIn(self.opp.status, (OpportunityStatus.CAPTURED, OpportunityStatus.REJECTED))
        if self.opp.status == OpportunityStatus.REJECTED:
            self.assertEqual(self.opp.rejection_reason, "Terminated during hold")
            self.assertIsNotNone(self.opp.rejected_at)
        else:
            self.assertEqual(self.opp.status_before_hold, "")
