import datetime
from decimal import Decimal
import threading
import time
from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError
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
    PublicationValidationError,
    RFQNotFoundError,
    StaleVersionError,
)
from trade_hub.models import RFQ, RFQStatus
from trade_hub.services import (
    RFQLifecycleService,
    cancel_rfq,
    close_rfq,
    publish_rfq,
)


def _setup_test_environment():
    """Helper to initialize standard organizations and commodities for testing."""
    buyer_org = Organization.objects.create(
        name="Petrochem Gulf Corp",
        registration_identifier="REG-GULF-001",
        country="AE",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=buyer_org,
        capability=OrganizationCapability.CapabilityType.BUYER,
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

    return buyer_org, bitumen, bitumen_v1, base_oil, base_oil_v1


class RFQLifecycleTransitionsTests(TestCase):
    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            self.base_oil,
            self.base_oil_v1,
        ) = _setup_test_environment()

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("1200.000"),
            unit="MT",
            target_price=Decimal("375.00"),
            currency="USD",
            payment_terms="LC at sight",
            incoterm="FOB",
            origin="Bandar Abbas",
            destination="Jebel Ali",
        )

    # ------------------------------------------------------------------
    # 1. Valid Transitions
    # ------------------------------------------------------------------
    def test_draft_to_published_success(self):
        """Draft RFQ transitions to Published, increments version, records published_at."""
        self.assertEqual(self.rfq.status, RFQStatus.DRAFT)
        self.assertEqual(self.rfq.version, 1)
        self.assertIsNone(self.rfq.published_at)

        published = publish_rfq(self.rfq.id, expected_version=1)

        self.assertEqual(published.status, RFQStatus.PUBLISHED)
        self.assertEqual(published.version, 2)
        self.assertIsNotNone(published.published_at)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.PUBLISHED)
        self.assertEqual(reloaded.version, 2)
        self.assertEqual(reloaded.published_at, published.published_at)

    def test_publish_accepts_rfq_instance_or_uuid_or_string(self):
        """publish_rfq accepts RFQ instance, UUID, or UUID string without trusting caller instance."""
        # Test passing instance
        published = publish_rfq(self.rfq, expected_version=1)
        self.assertEqual(published.status, RFQStatus.PUBLISHED)

        # Test passing string on close
        closed = close_rfq(str(self.rfq.id), expected_version=2)
        self.assertEqual(closed.status, RFQStatus.CLOSED)

    def test_draft_to_cancelled_success(self):
        """Draft RFQ transitions to Cancelled, increments version, records cancelled_at."""
        cancelled = cancel_rfq(
            self.rfq.id,
            expected_version=1,
            reason="Buyer decided to postpone procurement.",
        )

        self.assertEqual(cancelled.status, RFQStatus.CANCELLED)
        self.assertEqual(cancelled.version, 2)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(
            cancelled.cancellation_reason, "Buyer decided to postpone procurement."
        )

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.CANCELLED)
        self.assertEqual(reloaded.version, 2)

    def test_draft_to_cancelled_optional_reason(self):
        """Cancelling a Draft RFQ allows empty or omitted reason."""
        cancelled = cancel_rfq(self.rfq.id, expected_version=1)
        self.assertEqual(cancelled.status, RFQStatus.CANCELLED)
        self.assertEqual(cancelled.cancellation_reason, "")

    def test_published_to_closed_success(self):
        """Published RFQ transitions to Closed, increments version, records closed_at."""
        publish_rfq(self.rfq.id, expected_version=1)

        closed = close_rfq(self.rfq.id, expected_version=2)

        self.assertEqual(closed.status, RFQStatus.CLOSED)
        self.assertEqual(closed.version, 3)
        self.assertIsNotNone(closed.closed_at)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.CLOSED)
        self.assertEqual(reloaded.version, 3)

    def test_published_to_cancelled_success(self):
        """Published RFQ transitions to Cancelled with required reason, increments version."""
        publish_rfq(self.rfq.id, expected_version=1)

        cancelled = cancel_rfq(
            self.rfq.id,
            expected_version=2,
            reason="Commercial terms renegotiated outside platform.",
        )

        self.assertEqual(cancelled.status, RFQStatus.CANCELLED)
        self.assertEqual(cancelled.version, 3)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(
            cancelled.cancellation_reason,
            "Commercial terms renegotiated outside platform.",
        )

    def test_published_to_cancelled_requires_reason(self):
        """Cancelling a Published RFQ strictly requires a non-empty cancellation reason."""
        publish_rfq(self.rfq.id, expected_version=1)

        # Empty reason
        with self.assertRaises(InvalidTransitionError):
            cancel_rfq(self.rfq.id, expected_version=2, reason="")

        # Whitespace-only reason
        with self.assertRaises(InvalidTransitionError):
            cancel_rfq(self.rfq.id, expected_version=2, reason="   ")

        # None reason
        with self.assertRaises(InvalidTransitionError):
            cancel_rfq(self.rfq.id, expected_version=2, reason=None)

        # Confirm state unmodified
        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.PUBLISHED)
        self.assertEqual(reloaded.version, 2)
        self.assertIsNone(reloaded.cancelled_at)

    # ------------------------------------------------------------------
    # 2. Unsupported & Terminal Transitions
    # ------------------------------------------------------------------
    def test_draft_to_closed_rejected(self):
        """Draft RFQ cannot transition directly to Closed."""
        with self.assertRaises(InvalidTransitionError) as ctx:
            close_rfq(self.rfq.id, expected_version=1)
        self.assertIn("Only published RFQs can be closed", str(ctx.exception))

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_published_cannot_be_republished(self):
        """Published RFQ cannot be published again."""
        publish_rfq(self.rfq.id, expected_version=1)
        with self.assertRaises(InvalidTransitionError) as ctx:
            publish_rfq(self.rfq.id, expected_version=2)
        self.assertIn("Only draft RFQs can be published", str(ctx.exception))

    def test_closed_is_terminal(self):
        """Closed RFQ cannot be published, cancelled, or closed again."""
        publish_rfq(self.rfq.id, expected_version=1)
        close_rfq(self.rfq.id, expected_version=2)

        with self.assertRaises(InvalidTransitionError):
            publish_rfq(self.rfq.id, expected_version=3)

        with self.assertRaises(InvalidTransitionError):
            cancel_rfq(self.rfq.id, expected_version=3, reason="Close terminal test")

        with self.assertRaises(InvalidTransitionError):
            close_rfq(self.rfq.id, expected_version=3)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.CLOSED)
        self.assertEqual(reloaded.version, 3)

    def test_cancelled_is_terminal(self):
        """Cancelled RFQ cannot be published, closed, or cancelled again."""
        cancel_rfq(self.rfq.id, expected_version=1, reason="Cancelled")

        with self.assertRaises(InvalidTransitionError):
            publish_rfq(self.rfq.id, expected_version=2)

        with self.assertRaises(InvalidTransitionError):
            close_rfq(self.rfq.id, expected_version=2)

        with self.assertRaises(InvalidTransitionError):
            cancel_rfq(self.rfq.id, expected_version=2, reason="Again")

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.CANCELLED)
        self.assertEqual(reloaded.version, 2)

    def test_reserved_statuses_strictly_forbidden_in_epic_5(self):
        """Epic 5 does not permit transitioning into Collecting Offers, Negotiating, or Awarded."""
        # Services only expose publish, cancel, close; verify no entry point into reserved statuses
        self.assertFalse(hasattr(RFQLifecycleService, "collect_offers"))
        self.assertFalse(hasattr(RFQLifecycleService, "negotiate"))
        self.assertFalse(hasattr(RFQLifecycleService, "award"))


class RFQLifecycleExpectedVersionTests(TestCase):
    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            _,
            _,
        ) = _setup_test_environment()

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

    def test_missing_or_none_expected_version_rejected(self):
        """expected_version=None is rejected with InvalidVersionError."""
        with self.assertRaises(InvalidVersionError):
            publish_rfq(self.rfq.id, expected_version=None)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_invalid_type_expected_version_rejected(self):
        """String, float, and boolean values for expected_version are rejected with InvalidVersionError."""
        for invalid_val in ["1", 1.0, True, False, [1]]:
            with self.subTest(invalid_val=invalid_val):
                with self.assertRaises(InvalidVersionError):
                    publish_rfq(self.rfq.id, expected_version=invalid_val)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_non_positive_expected_version_rejected(self):
        """Zero and negative expected_version are rejected with InvalidVersionError."""
        for non_pos in [0, -1, -99]:
            with self.subTest(non_pos=non_pos):
                with self.assertRaises(InvalidVersionError):
                    publish_rfq(self.rfq.id, expected_version=non_pos)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_stale_expected_version_rejected(self):
        """Mismatched expected_version raises StaleVersionError without mutating database state."""
        with self.assertRaises(StaleVersionError) as ctx:
            publish_rfq(self.rfq.id, expected_version=99)
        self.assertIn("Stale version error", str(ctx.exception))

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)
        self.assertIsNone(reloaded.published_at)

    def test_caller_supplied_unlocked_rfq_not_validated_directly(self):
        """Service locks and validates fresh row; caller tampering with in-memory instance has no effect."""
        # Tamper with the in-memory object version or status
        in_memory = RFQ.objects.get(pk=self.rfq.pk)
        in_memory.version = 999
        in_memory.status = RFQStatus.CLOSED

        # Calling publish passing the tampered in-memory instance with the REAL db expected_version (1) succeeds
        published = publish_rfq(in_memory, expected_version=1)
        self.assertEqual(published.status, RFQStatus.PUBLISHED)
        self.assertEqual(published.version, 2)

    def test_nonexistent_rfq_raises_not_found(self):
        """Providing a nonexistent UUID raises RFQNotFoundError."""
        random_id = uuid.uuid4()
        with self.assertRaises(RFQNotFoundError):
            publish_rfq(random_id, expected_version=1)

        with self.assertRaises(RFQNotFoundError):
            publish_rfq("invalid-uuid-format", expected_version=1)


class RFQLifecyclePublicationValidationTests(TestCase):
    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            _,
            _,
        ) = _setup_test_environment()

    def test_missing_required_specification_rejected_on_publish(self):
        """Publishing fails if a required specification attribute is missing."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={},  # Missing required penetration_grade
            quantity=Decimal("500.000"),
        )

        with self.assertRaises(PublicationValidationError) as ctx:
            publish_rfq(rfq.id, expected_version=1)

        self.assertIn("Publication validation failed", str(ctx.exception))
        self.assertTrue(
            any(e.get("field") == "penetration_grade" for e in ctx.exception.errors)
        )

        reloaded = RFQ.objects.get(pk=rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_unknown_specification_attribute_rejected_on_publish(self):
        """Publishing fails if unknown specification attributes are present."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={
                "penetration_grade": "60/70",
                "fabricated_extra_property": 12345,
            },
            quantity=Decimal("500.000"),
        )

        with self.assertRaises(PublicationValidationError) as ctx:
            publish_rfq(rfq.id, expected_version=1)

        self.assertTrue(
            any(
                e.get("field") == "fabricated_extra_property"
                for e in ctx.exception.errors
            )
        )

        reloaded = RFQ.objects.get(pk=rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_invalid_specification_attribute_type_rejected_on_publish(self):
        """Publishing fails if a specification attribute has invalid data type."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={
                "penetration_grade": "60/70",
                "softening_point": "not_a_number",  # softening_point is NUMBER
            },
            quantity=Decimal("500.000"),
        )

        with self.assertRaises(PublicationValidationError) as ctx:
            publish_rfq(rfq.id, expected_version=1)

        self.assertTrue(
            any(e.get("field") == "softening_point" for e in ctx.exception.errors)
        )

        reloaded = RFQ.objects.get(pk=rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_historical_schema_version_binding_regression(self):
        """
        Historical schema version invariant:
        RFQ is created with schema v1.
        A new schema v2 with a new required attribute is published and activated.
        Publishing the RFQ validates against stored schema v1, NOT v2.
        """
        # Create draft RFQ with valid v1 specs (penetration_grade only)
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

        # Create and publish schema v2 with an additional required attribute 'viscosity_at_60c'
        bitumen_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=bitumen_v2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=bitumen_v2,
            key="viscosity_at_60c",
            label_fa="گرانروی در 60 درجه",
            label_en="Viscosity at 60C",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,  # Required in v2!
            sort_order=2,
        )
        publish_schema(bitumen_v2, activate=True)

        # Verify active schema on commodity is now v2
        self.bitumen.refresh_from_db()
        self.assertEqual(self.bitumen.active_schema_version, bitumen_v2)

        # The RFQ does NOT have 'viscosity_at_60c'.
        # If it were validated against active v2, it would fail.
        # But it MUST validate against stored schema v1, where 'viscosity_at_60c' does not exist.
        published = publish_rfq(rfq.id, expected_version=1)
        self.assertEqual(published.status, RFQStatus.PUBLISHED)
        self.assertEqual(published.schema_version, self.bitumen_v1)
        self.assertEqual(published.version, 2)

    def test_inactive_commodity_rejected_on_publish(self):
        """Publishing fails if the commodity definition is marked inactive."""
        self.bitumen.is_active = False
        self.bitumen.save(update_fields=["is_active"])

        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

        with self.assertRaises(PublicationValidationError) as ctx:
            publish_rfq(rfq.id, expected_version=1)
        self.assertIn("commodity is inactive", str(ctx.exception))

        reloaded = RFQ.objects.get(pk=rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)

    def test_unpublished_schema_version_rejected_on_publish(self):
        """Publishing fails if the referenced schema version is not in Published status."""
        draft_schema = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=99,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=draft_schema,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

        with self.assertRaises(PublicationValidationError) as ctx:
            publish_rfq(rfq.id, expected_version=1)
        self.assertIn("schema version is not published", str(ctx.exception))


class RFQLifecyclePostPublishImmutabilityTests(TestCase):
    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            self.base_oil,
            self.base_oil_v1,
        ) = _setup_test_environment()

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("1500.000"),
            unit="MT",
            target_price=Decimal("380.00"),
            currency="USD",
            payment_terms="LC 90 days",
            incoterm="CIF",
            origin="Bandar Abbas",
            destination="Mumbai",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            inspection_required=True,
            quality_notes="Third-party SGS test report required.",
        )
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

    def test_published_rfq_quantity_is_immutable(self):
        """Mutating quantity on a published RFQ raises ValidationError."""
        self.rfq.quantity = Decimal("2000.000")
        with self.assertRaises(ValidationError) as ctx:
            self.rfq.save()
        self.assertIn("Core fields cannot be modified after publication", str(ctx.exception))

    def test_published_rfq_specifications_is_immutable(self):
        """Mutating specifications dictionary on a published RFQ raises ValidationError."""
        self.rfq.specifications = {"penetration_grade": "85/100"}
        with self.assertRaises(ValidationError) as ctx:
            self.rfq.save()
        self.assertIn("Core fields cannot be modified after publication", str(ctx.exception))

    def test_published_rfq_commodity_and_schema_version_are_immutable(self):
        """Mutating commodity or schema version on a published RFQ raises ValidationError."""
        self.rfq.commodity = self.base_oil
        self.rfq.schema_version = self.base_oil_v1
        with self.assertRaises(ValidationError) as ctx:
            self.rfq.save()
        self.assertIn("Core fields cannot be modified after publication", str(ctx.exception))

    def test_published_rfq_commercial_and_delivery_terms_are_immutable(self):
        """Commercial, delivery, and inspection terms cannot change once published."""
        mutations = [
            ("unit", "Barrels"),
            ("target_price", Decimal("400.00")),
            ("currency", "EUR"),
            ("payment_terms", "TT 100% advance"),
            ("incoterm", "FOB"),
            ("origin", "Jebel Ali"),
            ("destination", "Karachi"),
            ("delivery_window_start", datetime.date(2026, 12, 1)),
            ("delivery_window_end", datetime.date(2026, 12, 31)),
            ("inspection_required", False),
            ("quality_notes", "Different notes"),
        ]
        for field, new_val in mutations:
            with self.subTest(field=field):
                rfq = RFQ.objects.get(pk=self.rfq.pk)
                setattr(rfq, field, new_val)
                with self.assertRaises(ValidationError) as ctx:
                    rfq.save()
                self.assertIn("Core fields cannot be modified after publication", str(ctx.exception))

    def test_cannot_mutate_core_fields_and_publish_simultaneously(self):
        """Draft RFQ cannot change core fields and set status=PUBLISHED in a single unvalidated save."""
        draft = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        draft.quantity = Decimal("9999.000")
        draft.status = RFQStatus.PUBLISHED
        with self.assertRaises(ValidationError) as ctx:
            draft.save()
        self.assertIn("Core fields cannot be modified during publication", str(ctx.exception))

    def test_closed_and_cancelled_rfqs_also_strictly_immutable(self):
        """Closed and Cancelled RFQs enforce identical core field immutability."""
        # Close RFQ
        close_rfq(self.rfq.id, expected_version=2)
        closed_rfq = RFQ.objects.get(pk=self.rfq.pk)
        closed_rfq.quantity = Decimal("5000.000")
        with self.assertRaises(ValidationError):
            closed_rfq.save()

        # Cancel another RFQ from draft
        draft_cancel = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        cancel_rfq(draft_cancel.id, expected_version=1, reason="Cancelled")
        cancelled_rfq = RFQ.objects.get(pk=draft_cancel.pk)
        cancelled_rfq.quantity = Decimal("5000.000")
        with self.assertRaises(ValidationError):
            cancelled_rfq.save()

    def test_draft_rfq_core_fields_freely_mutable(self):
        """Draft RFQ core fields can be updated and saved without error before publication."""
        draft = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        draft.quantity = Decimal("250.000")
        draft.specifications = {"penetration_grade": "85/100", "softening_point": 50.0}
        draft.incoterm = "CFR"
        draft.save()

        reloaded = RFQ.objects.get(pk=draft.pk)
        self.assertEqual(reloaded.quantity, Decimal("250.000"))
        self.assertEqual(reloaded.specifications["penetration_grade"], "85/100")
        self.assertEqual(reloaded.incoterm, "CFR")

    def test_administrative_fields_mutable_post_publish(self):
        """Administrative and deadline fields can be updated post-publication."""
        deadline = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=datetime.timezone.utc)
        self.rfq.submission_deadline = deadline
        self.rfq.notes = "Updated internal notes"
        self.rfq.save(update_fields=["submission_deadline", "notes", "updated_at"])

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.submission_deadline, deadline)
        self.assertEqual(reloaded.notes, "Updated internal notes")


class RFQLifecycleAtomicityTests(TestCase):
    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            _,
            _,
        ) = _setup_test_environment()

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

    def test_failure_injection_rolls_back_status_version_and_timestamps(self):
        """Simulated exception during save rolls back status, version, and timestamps together."""
        with patch.object(RFQ, "save", side_effect=RuntimeError("Simulated database failure during save")):
            with self.assertRaises(RuntimeError):
                publish_rfq(self.rfq.id, expected_version=1)

        # Database state must be completely untouched
        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)
        self.assertIsNone(reloaded.published_at)

    def test_cancel_failure_rolls_back_entirely(self):
        """Simulated exception during cancel rolls back status, version, and cancellation_reason."""
        with patch.object(RFQ, "save", side_effect=RuntimeError("Simulated write failure")):
            with self.assertRaises(RuntimeError):
                cancel_rfq(self.rfq.id, expected_version=1, reason="Rollback test")

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.DRAFT)
        self.assertEqual(reloaded.version, 1)
        self.assertIsNone(reloaded.cancelled_at)
        self.assertEqual(reloaded.cancellation_reason, "")


class RFQLifecycleConcurrencyTests(TransactionTestCase):
    """
    Real concurrent transaction tests using PostgreSQL row-level locks (FOR UPDATE).
    Executes parallel threads with distinct database connections.
    """

    def setUp(self):
        (
            self.buyer_org,
            self.bitumen,
            self.bitumen_v1,
            _,
            _,
        ) = _setup_test_environment()

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
        )

    def test_publish_vs_publish_race(self):
        """
        publish vs publish race:
        Two concurrent threads attempt to publish the same Draft RFQ with expected_version=1.
        Exactly one succeeds.
        The other fails with StaleVersionError.
        Final state: status=PUBLISHED, version=2, published_at set.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_publish(thread_name):
            try:
                barrier.wait()
                time.sleep(0.01)
                publish_rfq(self.rfq.id, expected_version=1)
                results[thread_name] = "success"
            except Exception as exc:
                results[thread_name] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_publish, args=("t1",))
        t2 = threading.Thread(target=thread_publish, args=("t2",))

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # Assert exactly one succeeded and one raised StaleVersionError
        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.status, RFQStatus.PUBLISHED)
        self.assertEqual(reloaded.version, 2)
        self.assertIsNotNone(reloaded.published_at)

    def test_publish_vs_cancel_draft_race(self):
        """
        publish vs cancel draft race:
        Two concurrent threads race (one publish, one cancel) on Draft RFQ with expected_version=1.
        Exactly one succeeds.
        The loser fails with StaleVersionError.
        Final state: version=2, status is either PUBLISHED or CANCELLED.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_publish():
            try:
                barrier.wait()
                time.sleep(0.01)
                publish_rfq(self.rfq.id, expected_version=1)
                results["publish"] = "success"
            except Exception as exc:
                results["publish"] = exc
            finally:
                connection.close()

        def thread_cancel():
            try:
                barrier.wait()
                time.sleep(0.01)
                cancel_rfq(self.rfq.id, expected_version=1, reason="Cancelled in race")
                results["cancel"] = "success"
            except Exception as exc:
                results["cancel"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_publish)
        t2 = threading.Thread(target=thread_cancel)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.version, 2)
        self.assertIn(reloaded.status, (RFQStatus.PUBLISHED, RFQStatus.CANCELLED))

    def test_close_vs_cancel_published_race(self):
        """
        close vs cancel published race:
        RFQ starts in PUBLISHED status with version=2.
        Two concurrent threads race (one close, one cancel) with expected_version=2.
        Exactly one succeeds.
        The loser fails with StaleVersionError.
        Final state: version=3, status is either CLOSED or CANCELLED.
        """
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)
        self.assertEqual(self.rfq.version, 2)

        barrier = threading.Barrier(2)
        results = {}

        def thread_close():
            try:
                barrier.wait()
                time.sleep(0.01)
                close_rfq(self.rfq.id, expected_version=2)
                results["close"] = "success"
            except Exception as exc:
                results["close"] = exc
            finally:
                connection.close()

        def thread_cancel():
            try:
                barrier.wait()
                time.sleep(0.01)
                cancel_rfq(
                    self.rfq.id,
                    expected_version=2,
                    reason="Cancelled published RFQ in race",
                )
                results["cancel"] = "success"
            except Exception as exc:
                results["cancel"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_close)
        t2 = threading.Thread(target=thread_cancel)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        successes = [k for k, v in results.items() if v == "success"]
        failures = [k for k, v in results.items() if isinstance(v, Exception)]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(failures), 1, f"Expected exactly 1 failure, got {results}")
        self.assertIsInstance(results[failures[0]], StaleVersionError)

        reloaded = RFQ.objects.get(pk=self.rfq.pk)
        self.assertEqual(reloaded.version, 3)
        self.assertIn(reloaded.status, (RFQStatus.CLOSED, RFQStatus.CANCELLED))
