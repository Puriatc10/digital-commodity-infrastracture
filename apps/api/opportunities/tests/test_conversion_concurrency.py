import datetime
from decimal import Decimal
import threading
import time

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from opportunities.exceptions import (
    InvalidTransitionError,
    OpportunityAlreadyConvertedError,
    StaleVersionError,
)
from opportunities.models import (
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    update_opportunity,
)
from opportunities.services_conversion import convert_opportunity_to_rfq
from opportunities.services_lifecycle import (
    mark_opportunity_lost,
    qualify_opportunity,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
)
from trade_hub.models import RFQ

User = get_user_model()


class OpportunityConversionConcurrencyTests(TransactionTestCase):
    """
    Multi-threaded concurrency tests for Opportunity -> RFQ conversion against PostgreSQL.

    Verifies row-level lock synchronization and optimistic concurrency under:
    1. Convert vs Convert (competing conversion attempts).
    2. Convert vs Lifecycle (competing transition to Lost).
    3. Convert vs Opportunity Update (preventing TOCTOU and stale reads).
    """

    def setUp(self):
        self.operator = User.objects.create_user(email="operator_conc@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.buyer_org = Organization.objects.create(name="Concurrent Buyer Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_conc",
            name_en="Bitumen Concurrency",
            name_fa="قیر همزمانی",
            is_active=True,
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.schema, activate=True)

    def _create_and_qualify_opportunity(self):
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            unit="MT",
            indicative_price=Decimal("350.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="Letter of Credit at sight",
            geography="Jebel Ali Port, UAE",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        return opp

    # -------------------------------------------------------------------------
    # 1. Convert vs Convert Race
    # -------------------------------------------------------------------------

    def test_convert_vs_convert_race(self):
        """
        Two concurrent threads race to convert the same Qualified Demand Opportunity (expected_version=2).
        Under row lock:
        - Exactly one thread succeeds in creating the RFQ and advancing Opportunity version to 3.
        - The competing thread raises StaleVersionError or OpportunityAlreadyConvertedError.
        - Exactly one RFQ is created.
        """
        opp = self._create_and_qualify_opportunity()
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def worker(thread_name):
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_rfq(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={"schema_version_id": self.schema.id},
                )
                results[thread_name] = "success"
            except Exception as exc:
                results[thread_name] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=("thread_1",))
        t2 = threading.Thread(target=worker, args=("thread_2",))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got results: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 loser, got results: {results}")

        loser_exc = results[failures[0]]
        self.assertTrue(
            isinstance(loser_exc, (StaleVersionError, OpportunityAlreadyConvertedError)),
            f"Expected StaleVersionError or OpportunityAlreadyConvertedError, got: {type(loser_exc)}: {loser_exc}",
        )

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertEqual(opp.version, 3)
        self.assertIsNotNone(opp.converted_rfq_id)
        self.assertEqual(RFQ.objects.filter(source_opportunity=opp).count(), 1)

    # -------------------------------------------------------------------------
    # 2. Convert vs Lifecycle (Lost) Race
    # -------------------------------------------------------------------------

    def test_convert_vs_lifecycle_race(self):
        """
        Two concurrent threads race: one converts to RFQ, the other marks Opportunity as Lost.
        Under row lock:
        - Exactly one transition wins.
        - The other transition fails with StaleVersionError or InvalidTransitionError / OpportunityConversionError.
        """
        opp = self._create_and_qualify_opportunity()
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def convert_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_rfq(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={"schema_version_id": self.schema.id},
                )
                results["convert"] = "success"
            except Exception as exc:
                results["convert"] = exc
            finally:
                connection.close()

        def lost_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                mark_opportunity_lost(
                    opp.id,
                    expected_version=2,
                    reason="Customer cancelled requirement",
                    actor=self.operator,
                )
                results["lost"] = "success"
            except Exception as exc:
                results["lost"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=convert_worker)
        t2 = threading.Thread(target=lost_worker)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 loser, got: {results}")

        opp.refresh_from_db()
        self.assertIn(opp.status, (OpportunityStatus.CONVERTED, OpportunityStatus.LOST))
        self.assertEqual(opp.version, 3)

        if results.get("convert") == "success":
            self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
            self.assertEqual(RFQ.objects.filter(source_opportunity=opp).count(), 1)
        else:
            self.assertEqual(opp.status, OpportunityStatus.LOST)
            self.assertEqual(RFQ.objects.filter(source_opportunity=opp).count(), 0)

    # -------------------------------------------------------------------------
    # 3. Convert vs Opportunity Update Race (No TOCTOU)
    # -------------------------------------------------------------------------

    def test_convert_vs_opportunity_update_race(self):
        """
        Two concurrent threads race: one converts Opportunity to RFQ, the other updates Opportunity quantity.
        Under row lock:
        - Neither operation consumes stale aggregate data.
        - Exactly one succeeds for expected_version=2, the other fails with StaleVersionError.
        """
        opp = self._create_and_qualify_opportunity()
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def convert_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_rfq(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={"schema_version_id": self.schema.id},
                )
                results["convert"] = "success"
            except Exception as exc:
                results["convert"] = exc
            finally:
                connection.close()

        def update_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                update_opportunity(
                    opp,
                    data={
                        "expected_version": 2,
                        "quantity": Decimal("2500.000"),
                    },
                )
                results["update"] = "success"
            except Exception as exc:
                results["update"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=convert_worker)
        t2 = threading.Thread(target=update_worker)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 loser, got: {results}")

        loser = failures[0]
        self.assertTrue(
            isinstance(results[loser], (StaleVersionError, InvalidTransitionError)),
            f"Expected StaleVersionError or InvalidTransitionError, got {type(results[loser])}: {results[loser]}",
        )
