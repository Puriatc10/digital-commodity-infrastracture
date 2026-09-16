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
    OpportunityConversionError,
    StaleVersionError,
)
from opportunities.models import (
    ExternalCounterparty,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    update_opportunity,
)
from opportunities.services_conversion import (
    convert_opportunity_to_rfq,
    convert_opportunity_to_supply_listing,
)
from opportunities.services_lifecycle import (
    mark_opportunity_lost,
    qualify_opportunity,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
)
from trade_hub.models import RFQ, SupplyListing

User = get_user_model()


class OpportunitySupplyConversionConcurrencyTests(TransactionTestCase):
    """
    Multi-threaded concurrency tests for Opportunity -> Supply Listing conversion against PostgreSQL.

    Verifies row-level lock synchronization and optimistic concurrency under:
    1. Convert vs Convert (competing conversion attempts).
    2. Convert vs Lifecycle (competing transition to Lost).
    3. Convert vs Opportunity Update (preventing TOCTOU and stale reads).
    4. Supply Conversion vs RFQ Conversion (cross-conversion race).
    5. Two Supplier-owner selections (concurrent requests selecting Org A vs Org B).
    """

    def setUp(self):
        self.operator = User.objects.create_user(email="operator_conc_sup@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.supplier_org = Organization.objects.create(name="Concurrent Supplier Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )

        self.supplier_org_2 = Organization.objects.create(name="Second Supplier Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.supplier_org_2, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_conc_sup",
            name_en="Bitumen Concurrency Supply",
            name_fa="قیر همزمانی عرضه",
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

        self.ext_counterparty = ExternalCounterparty.objects.create(
            company_name="Concurrent Ext Supplier",
            contact_name="Ali Reza",
            email="ali@concurrent.com",
            phone="+989123456789",
        )

    def _create_and_qualify_opportunity(self, **kwargs):
        defaults = {
            "direction": OpportunityDirection.SUPPLY,
            "organization_id": self.supplier_org.id,
            "commodity_id": self.commodity.id,
            "quantity": Decimal("1000.000"),
            "unit": "MT",
            "indicative_price": Decimal("350.00"),
            "currency": "USD",
            "delivery_window_start": datetime.date(2026, 11, 1),
            "delivery_window_end": datetime.date(2026, 11, 30),
            "payment_terms": "Letter of Credit at sight",
            "geography": "Bandar Abbas Port, Iran",
            "source": OpportunitySource.OPERATOR_SOURCING,
        }
        defaults.update(kwargs)
        opp = create_opportunity(**defaults)
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        return opp

    # -------------------------------------------------------------------------
    # 1. Convert vs Convert Race
    # -------------------------------------------------------------------------

    def test_convert_vs_convert_race(self):
        """
        Two concurrent threads race to convert the same Qualified Supply Opportunity (expected_version=2).
        Under row lock:
        - Exactly one thread succeeds in creating the SupplyListing and advancing Opportunity version to 3.
        - The competing thread raises StaleVersionError or OpportunityAlreadyConvertedError.
        - Exactly one SupplyListing is created.
        """
        opp = self._create_and_qualify_opportunity()
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def worker(thread_name):
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_supply_listing(
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
        self.assertIsNotNone(opp.converted_supply_listing_id)
        self.assertEqual(SupplyListing.objects.filter(source_opportunity=opp).count(), 1)

    # -------------------------------------------------------------------------
    # 2. Convert vs Lifecycle (Lost) Race
    # -------------------------------------------------------------------------

    def test_convert_vs_lifecycle_race(self):
        """
        Two concurrent threads race: one converts to SupplyListing, the other marks Opportunity as Lost.
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
                convert_opportunity_to_supply_listing(
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
                    reason="Supplier withdrawn",
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
            self.assertEqual(SupplyListing.objects.filter(source_opportunity=opp).count(), 1)
        else:
            self.assertEqual(opp.status, OpportunityStatus.LOST)
            self.assertEqual(SupplyListing.objects.filter(source_opportunity=opp).count(), 0)

    # -------------------------------------------------------------------------
    # 3. Convert vs Opportunity Update Race (No TOCTOU)
    # -------------------------------------------------------------------------

    def test_convert_vs_opportunity_update_race(self):
        """
        Two concurrent threads race: one converts Opportunity to SupplyListing, the other updates quantity.
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
                convert_opportunity_to_supply_listing(
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

    # -------------------------------------------------------------------------
    # 4. Supply Conversion vs RFQ Conversion (Cross-conversion Race)
    # -------------------------------------------------------------------------

    def test_supply_conversion_vs_rfq_conversion_race(self):
        """
        Two concurrent threads race: one converts to SupplyListing, the other attempts to convert to RFQ.
        Under row lock and invariants:
        - Supply conversion succeeds.
        - RFQ conversion fails immediately (due to direction invariant OpportunityConversionError or AlreadyConverted).
        - Exactly 1 converted target exists (SupplyListing), and 0 RFQs exist.
        """
        opp = self._create_and_qualify_opportunity()
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def supply_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_supply_listing(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={"schema_version_id": self.schema.id},
                )
                results["supply"] = "success"
            except Exception as exc:
                results["supply"] = exc
            finally:
                connection.close()

        def rfq_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_rfq(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={"schema_version_id": self.schema.id},
                )
                results["rfq"] = "success"
            except Exception as exc:
                results["rfq"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=supply_worker)
        t2 = threading.Thread(target=rfq_worker)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Supply conversion succeeds, RFQ conversion must fail
        self.assertEqual(results.get("supply"), "success")
        self.assertTrue(
            isinstance(results.get("rfq"), (OpportunityConversionError, OpportunityAlreadyConvertedError, StaleVersionError)),
            f"Expected RFQ conversion failure, got: {results.get('rfq')}",
        )

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertIsNotNone(opp.converted_supply_listing_id)
        self.assertIsNone(opp.converted_rfq_id)
        self.assertEqual(SupplyListing.objects.filter(source_opportunity=opp).count(), 1)
        self.assertEqual(RFQ.objects.filter(source_opportunity=opp).count(), 0)

    # -------------------------------------------------------------------------
    # 5. Two Supplier-owner Selections Race
    # -------------------------------------------------------------------------

    def test_two_supplier_owner_selections_race(self):
        """
        Concurrent conversion requests on an ExternalCounterparty Opportunity selecting
        different Supplier Organizations (Org A vs Org B) must result in at most one
        authoritative Supply Listing.
        """
        opp = self._create_and_qualify_opportunity(
            organization_id=None,
            external_counterparty_id=self.ext_counterparty.id,
        )
        self.assertEqual(opp.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def org1_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_supply_listing(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={
                        "schema_version_id": self.schema.id,
                        "supplier_organization_id": self.supplier_org.id,
                    },
                )
                results["org1"] = "success"
            except Exception as exc:
                results["org1"] = exc
            finally:
                connection.close()

        def org2_worker():
            try:
                barrier.wait()
                time.sleep(0.01)
                convert_opportunity_to_supply_listing(
                    opp.id,
                    expected_version=2,
                    actor=self.operator,
                    data={
                        "schema_version_id": self.schema.id,
                        "supplier_organization_id": self.supplier_org_2.id,
                    },
                )
                results["org2"] = "success"
            except Exception as exc:
                results["org2"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=org1_worker)
        t2 = threading.Thread(target=org2_worker)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 winner, got: {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 loser, got: {results}")

        loser_exc = results[failures[0]]
        self.assertTrue(
            isinstance(loser_exc, (StaleVersionError, OpportunityAlreadyConvertedError)),
            f"Expected StaleVersionError or OpportunityAlreadyConvertedError, got: {type(loser_exc)}: {loser_exc}",
        )

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertEqual(opp.version, 3)
        self.assertEqual(SupplyListing.objects.filter(source_opportunity=opp).count(), 1)
        created_listing = SupplyListing.objects.get(source_opportunity=opp)
        winning_org_id = self.supplier_org.id if successes[0] == "org1" else self.supplier_org_2.id
        self.assertEqual(created_listing.organization_id, winning_org_id)
