import datetime
from decimal import Decimal
import threading
import time
from unittest.mock import patch
import uuid

from django.db import connection
from django.test import TestCase, TransactionTestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from organizations.models import Organization, OrganizationCapability
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    StaleVersionError,
    SupplyListingNotFoundError,
    SupplyListingValidationError,
)
from trade_hub.models import SupplyListing, SupplyListingStatus
from trade_hub.services import (
    activate_supply,
    close_supply,
    expire_supply,
)


def _setup_test_environment():
    """Helper to initialize standard supplier organization and commodities for testing."""
    supplier_org = Organization.objects.create(
        name="Global Bitumen Refining FZE",
        registration_identifier="REG-GBR-001",
        country="AE",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=supplier_org,
        capability=OrganizationCapability.CapabilityType.SUPPLIER,
    )

    bitumen = CommodityDefinition.objects.create(
        code="bitumen",
        name_fa="قیر",
        name_en="Bitumen",
        is_active=True,
    )
    bitumen_v1 = CommoditySchemaVersion.objects.create(
        commodity=bitumen,
        version=1,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=bitumen_v1,
        key="penetration_grade",
        label_fa="درجه نفوذ",
        label_en="Penetration Grade",
        data_type=CommodityAttributeDefinition.DataType.STRING,
        is_required=True,
        sort_order=1,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=bitumen_v1,
        key="softening_point",
        label_fa="نقطه نرمی",
        label_en="Softening Point",
        data_type=CommodityAttributeDefinition.DataType.NUMBER,
        is_required=False,
        sort_order=2,
    )
    publish_schema(bitumen_v1, activate=True)

    base_oil = CommodityDefinition.objects.create(
        code="base_oil",
        name_fa="روغن پایه",
        name_en="Base Oil",
        is_active=True,
    )
    base_oil_v1 = CommoditySchemaVersion.objects.create(
        commodity=base_oil,
        version=1,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=base_oil_v1,
        key="viscosity_index",
        label_fa="شاخص گرانروی",
        label_en="Viscosity Index",
        data_type=CommodityAttributeDefinition.DataType.INTEGER,
        is_required=True,
        sort_order=1,
    )
    publish_schema(base_oil_v1, activate=True)

    return supplier_org, bitumen, bitumen_v1, base_oil, base_oil_v1


class SupplyLifecycleTransitionsTests(TestCase):
    def setUp(self):
        (
            self.supplier_org,
            self.bitumen,
            self.bitumen_v1,
            self.base_oil,
            self.base_oil_v1,
        ) = _setup_test_environment()

        self.listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("2000.000"),
            unit="MT",
            indicative_price=Decimal("370.00"),
            currency="USD",
            payment_terms="LC at sight",
            incoterm="FOB",
            origin="Bandar Abbas",
            availability_window_start=datetime.date(2026, 11, 1),
            availability_window_end=datetime.date(2026, 11, 30),
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

    # ------------------------------------------------------------------
    # 1. Valid Transitions
    # ------------------------------------------------------------------
    def test_draft_to_active_success(self):
        """Draft SupplyListing transitions to Active, increments version, records activated_at."""
        self.assertEqual(self.listing.status, SupplyListingStatus.DRAFT)
        self.assertEqual(self.listing.version, 1)
        self.assertIsNone(self.listing.activated_at)

        activated = activate_supply(self.listing.id, expected_version=1)

        self.assertEqual(activated.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(activated.version, 2)
        self.assertIsNotNone(activated.activated_at)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(reloaded.version, 2)
        self.assertIsNotNone(reloaded.activated_at)

    def test_draft_to_closed_success(self):
        """Draft SupplyListing transitions directly to Closed, increments version, records closed_at."""
        closed = close_supply(self.listing.id, expected_version=1)

        self.assertEqual(closed.status, SupplyListingStatus.CLOSED)
        self.assertEqual(closed.version, 2)
        self.assertIsNotNone(closed.closed_at)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.status, SupplyListingStatus.CLOSED)
        self.assertEqual(reloaded.version, 2)

    def test_active_to_closed_success(self):
        """Active SupplyListing transitions to Closed with version increment and closed_at."""
        activate_supply(self.listing.id, expected_version=1)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(self.listing.version, 2)

        closed = close_supply(self.listing.id, expected_version=2)
        self.assertEqual(closed.status, SupplyListingStatus.CLOSED)
        self.assertEqual(closed.version, 3)
        self.assertIsNotNone(closed.closed_at)

    def test_active_to_expired_success(self):
        """Active SupplyListing transitions to Expired with version increment and expired_at."""
        activate_supply(self.listing.id, expected_version=1)
        self.listing.refresh_from_db()

        expired = expire_supply(self.listing.id, expected_version=2)
        self.assertEqual(expired.status, SupplyListingStatus.EXPIRED)
        self.assertEqual(expired.version, 3)
        self.assertIsNotNone(expired.expired_at)

    # ------------------------------------------------------------------
    # 2. Invalid Transitions
    # ------------------------------------------------------------------
    def test_invalid_transitions_raise_error(self):
        """Invalid lifecycle transitions raise InvalidTransitionError."""
        # Draft -> Expired is illegal
        with self.assertRaises(InvalidTransitionError):
            expire_supply(self.listing.id, expected_version=1)

        # Activate to Active
        activate_supply(self.listing.id, expected_version=1)
        self.listing.refresh_from_db()

        # Active -> Active is illegal
        with self.assertRaises(InvalidTransitionError):
            activate_supply(self.listing.id, expected_version=2)

        # Close listing
        close_supply(self.listing.id, expected_version=2)
        self.listing.refresh_from_db()

        # Closed -> Active is illegal
        with self.assertRaises(InvalidTransitionError):
            activate_supply(self.listing.id, expected_version=3)

        # Closed -> Expired is illegal
        with self.assertRaises(InvalidTransitionError):
            expire_supply(self.listing.id, expected_version=3)

        # Closed -> Closed is illegal
        with self.assertRaises(InvalidTransitionError):
            close_supply(self.listing.id, expected_version=3)

    # ------------------------------------------------------------------
    # 3. Expected Version & Concurrency Validation
    # ------------------------------------------------------------------
    def test_stale_expected_version_raises_stale_version_error(self):
        """Passing stale expected_version raises StaleVersionError without mutating state."""
        with self.assertRaises(StaleVersionError):
            activate_supply(self.listing.id, expected_version=99)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.status, SupplyListingStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_invalid_expected_version_types_rejected(self):
        """Missing, boolean, negative, or non-integer expected_version raises InvalidVersionError."""
        invalid_versions = [None, True, False, "1", 0, -1, 1.5]
        for bad_version in invalid_versions:
            with self.subTest(bad_version=bad_version):
                with self.assertRaises(InvalidVersionError):
                    activate_supply(self.listing.id, expected_version=bad_version)

    def test_unknown_supply_id_raises_not_found(self):
        """Operating on a non-existent UUID raises SupplyListingNotFoundError."""
        random_id = uuid.uuid4()
        with self.assertRaises(SupplyListingNotFoundError):
            activate_supply(random_id, expected_version=1)

    # ------------------------------------------------------------------
    # 4. Activation Prerequisites
    # ------------------------------------------------------------------
    def test_activate_fails_if_supplier_lacks_capability(self):
        """Organization lacking Supplier capability cannot activate a supply listing."""
        buyer_only_org = Organization.objects.create(name="Buyer Only Corp", country="AE", is_active=True)
        OrganizationCapability.objects.create(
            organization=buyer_only_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        bad_listing = SupplyListing.objects.create(
            organization=buyer_only_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        with self.assertRaises(SupplyListingValidationError) as ctx:
            activate_supply(bad_listing.id, expected_version=1)
        self.assertIn("lacks Supplier capability", str(ctx.exception))

    def test_activate_fails_if_commodity_inactive(self):
        """Inactive commodity blocks activation."""
        self.bitumen.is_active = False
        self.bitumen.save()
        with self.assertRaises(SupplyListingValidationError) as ctx:
            activate_supply(self.listing.id, expected_version=1)
        self.assertIn("commodity is inactive", str(ctx.exception))

    def test_activate_fails_if_schema_version_not_published(self):
        """Draft or retired schema version blocks activation."""
        draft_schema = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        self.listing.schema_version = draft_schema
        self.listing.save(update_fields=["schema_version"])

        with self.assertRaises(SupplyListingValidationError) as ctx:
            activate_supply(self.listing.id, expected_version=1)
        self.assertIn("schema version is not published", str(ctx.exception))

    def test_activate_fails_if_dynamic_specifications_invalid(self):
        """Invalid dynamic specifications block activation."""
        self.listing.specifications = {"invalid_field": "test"}  # missing penetration_grade
        self.listing.save(update_fields=["specifications"])

        with self.assertRaises(SupplyListingValidationError) as ctx:
            activate_supply(self.listing.id, expected_version=1)
        self.assertIn("Activation validation failed", str(ctx.exception))

    # ------------------------------------------------------------------
    # 5. Atomicity and Rollback
    # ------------------------------------------------------------------
    def test_activation_failure_rolls_back_entirely(self):
        """Failure during activation save rolls back status, version, and activated_at."""
        with patch.object(SupplyListing, "save", side_effect=RuntimeError("Simulated database failure")):
            with self.assertRaises(RuntimeError):
                activate_supply(self.listing.id, expected_version=1)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.status, SupplyListingStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)
        self.assertIsNone(reloaded.activated_at)


class SupplyLifecycleConcurrencyTests(TransactionTestCase):
    """
    Real concurrent transaction tests using PostgreSQL row-level locks (FOR UPDATE).
    Executes parallel threads with distinct database connections.
    """

    def setUp(self):
        (
            self.supplier_org,
            self.bitumen,
            self.bitumen_v1,
            _,
            _,
        ) = _setup_test_environment()

        self.listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1500.000"),
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

    def test_activate_vs_activate_race(self):
        """
        Two concurrent threads attempt to activate the same Draft SupplyListing with expected_version=1.
        Exactly one succeeds. The other fails with StaleVersionError.
        Final state: status=ACTIVE, version=2, activated_at set.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_activate(thread_name):
            try:
                barrier.wait()
                time.sleep(0.01)
                activate_supply(self.listing.id, expected_version=1)
                results[thread_name] = "success"
            except Exception as exc:
                results[thread_name] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_activate, args=("t1",))
        t2 = threading.Thread(target=thread_activate, args=("t2",))

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(reloaded.version, 2)
        self.assertIsNotNone(reloaded.activated_at)

    def test_activate_vs_close_draft_race(self):
        """
        Two concurrent threads race (one activate, one close) on Draft SupplyListing with expected_version=1.
        Exactly one succeeds. The loser fails with StaleVersionError.
        Final state: version=2, status is either ACTIVE or CLOSED.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_activate():
            try:
                barrier.wait()
                time.sleep(0.01)
                activate_supply(self.listing.id, expected_version=1)
                results["activate"] = "success"
            except Exception as exc:
                results["activate"] = exc
            finally:
                connection.close()

        def thread_close():
            try:
                barrier.wait()
                time.sleep(0.01)
                close_supply(self.listing.id, expected_version=1)
                results["close"] = "success"
            except Exception as exc:
                results["close"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_activate)
        t2 = threading.Thread(target=thread_close)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.version, 2)
        self.assertIn(reloaded.status, (SupplyListingStatus.ACTIVE, SupplyListingStatus.CLOSED))

    def test_close_vs_expire_active_race(self):
        """
        Two concurrent threads race (one close, one expire) on Active SupplyListing with expected_version=2.
        Exactly one succeeds. The loser fails with StaleVersionError.
        Final state: version=3, status is either CLOSED or EXPIRED.
        """
        activate_supply(self.listing.id, expected_version=1)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(self.listing.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def thread_close():
            try:
                barrier.wait()
                time.sleep(0.01)
                close_supply(self.listing.id, expected_version=2)
                results["close"] = "success"
            except Exception as exc:
                results["close"] = exc
            finally:
                connection.close()

        def thread_expire():
            try:
                barrier.wait()
                time.sleep(0.01)
                expire_supply(self.listing.id, expected_version=2)
                results["expire"] = "success"
            except Exception as exc:
                results["expire"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_close)
        t2 = threading.Thread(target=thread_expire)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = SupplyListing.objects.get(pk=self.listing.pk)
        self.assertEqual(reloaded.version, 3)
        self.assertIn(reloaded.status, (SupplyListingStatus.CLOSED, SupplyListingStatus.EXPIRED))
