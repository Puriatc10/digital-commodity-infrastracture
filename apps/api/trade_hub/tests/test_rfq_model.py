import datetime
from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema, validate_commodity_payload
from organizations.models import Organization, OrganizationCapability
from trade_hub.models import RFQ, RFQStatus, RFQVisibility


class RFQModelTests(TestCase):
    def setUp(self):
        # Setup buyer organization with buyer capability
        self.buyer_org = Organization.objects.create(
            name="Test Petrochem Corp",
            registration_identifier="REG-123456",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )

        # Setup Bitumen commodity and published v1 schema
        self.bitumen = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.bitumen_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=False,
            sort_order=2,
        )
        publish_schema(self.bitumen_v1, activate=True)

        # Setup Base Oil commodity and published v1 schema
        self.base_oil = CommodityDefinition.objects.create(
            code="base_oil",
            name_fa="روغن پایه",
            name_en="Base Oil",
            is_active=True,
        )
        self.base_oil_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.base_oil,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.base_oil_v1,
            key="viscosity_index",
            label_fa="شاخص گرانروی",
            label_en="Viscosity Index",
            data_type=CommodityAttributeDefinition.DataType.INTEGER,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.base_oil_v1, activate=True)

    # ------------------------------------------------------------------
    # 1. Creation & Basic Persistence
    # ------------------------------------------------------------------
    def test_valid_generic_rfq_persists(self):
        """A valid RFQ persists with correct initial states, foreign keys, and values."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("1500.000"),
            unit="MT",
            target_price=Decimal("385.50"),
            currency="USD",
            payment_terms="LC at sight",
            incoterm="FOB",
            origin="Bandar Abbas",
            destination="Jebel Ali",
            delivery_window_start=datetime.date(2026, 10, 1),
            delivery_window_end=datetime.date(2026, 10, 20),
            submission_deadline=datetime.datetime(2026, 9, 25, 12, 0, tzinfo=datetime.timezone.utc),
            inspection_required=True,
            quality_notes="SGS inspection required at loading port.",
            notes="Prompt delivery preferred.",
        )

        self.assertIsInstance(rfq.id, uuid.UUID)
        self.assertEqual(rfq.organization, self.buyer_org)
        self.assertEqual(rfq.buyer, self.buyer_org)
        self.assertEqual(rfq.commodity, self.bitumen)
        self.assertEqual(rfq.schema_version, self.bitumen_v1)
        self.assertEqual(rfq.status, RFQStatus.DRAFT)
        self.assertEqual(rfq.visibility, RFQVisibility.PRIVATE)
        self.assertEqual(rfq.version, 1)
        self.assertEqual(rfq.quantity, Decimal("1500.000"))
        self.assertEqual(rfq.unit, "MT")
        self.assertEqual(rfq.target_price, Decimal("385.50"))
        self.assertEqual(rfq.currency, "USD")
        self.assertTrue(rfq.inspection_required)
        self.assertFalse(rfq.created_by_operator)
        self.assertIsNotNone(rfq.created_at)
        self.assertIsNotNone(rfq.updated_at)

        # Specifications preserved accurately
        reloaded = RFQ.objects.get(pk=rfq.pk)
        self.assertEqual(reloaded.specifications["penetration_grade"], "60/70")
        self.assertEqual(reloaded.specifications["softening_point"], 49.5)
        self.assertIn("bitumen", str(reloaded))

    def test_buyer_kwarg_and_property_alias(self):
        """Passing buyer=... in initialization and reading rfq.buyer behaves identically to organization."""
        rfq = RFQ.objects.create(
            buyer=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
        )
        self.assertEqual(rfq.organization, self.buyer_org)
        self.assertEqual(rfq.buyer, self.buyer_org)

        # Updating via buyer setter
        other_org = Organization.objects.create(name="Another Buyer Ltd", is_active=True)
        rfq.buyer = other_org
        rfq.save()
        rfq.refresh_from_db()
        self.assertEqual(rfq.organization, other_org)

    # ------------------------------------------------------------------
    # 2. Commodity Genericity
    # ------------------------------------------------------------------
    def test_commodity_genericity_supports_multiple_commodities(self):
        """
        The identical RFQ model supports multiple distinct commodities without
        hard-coded columns or conditional branches.
        """
        # Bitumen RFQ
        bitumen_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.0},
            quantity=Decimal("1000.000"),
            unit="MT",
        )

        # Base Oil RFQ
        base_oil_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.base_oil,
            schema_version=self.base_oil_v1,
            specifications={"viscosity_index": 95},
            quantity=Decimal("200.000"),
            unit="MT",
        )

        # Verify neither commodity has columns on the RFQ model
        rfq_column_names = [f.name for f in RFQ._meta.get_fields()]
        self.assertNotIn("penetration_grade", rfq_column_names)
        self.assertNotIn("softening_point", rfq_column_names)
        self.assertNotIn("viscosity_index", rfq_column_names)

        # Dynamic specifications validation for both records works using respective schemas
        validate_commodity_payload(bitumen_rfq.schema_version, bitumen_rfq.specifications)
        validate_commodity_payload(base_oil_rfq.schema_version, base_oil_rfq.specifications)

    # ------------------------------------------------------------------
    # 3. Historical Schema Binding
    # ------------------------------------------------------------------
    def test_historical_schema_binding_preserved_across_new_versions(self):
        """
        RFQ created with schema v1 remains bound to v1 even after v2 is published
        and set active. Existing specifications retain v1 meaning and are not
        revalidated against or mutated by v2.
        """
        # 1. Create RFQ with v1
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.0},
            quantity=Decimal("1000.000"),
            unit="MT",
        )
        self.assertEqual(rfq.schema_version_id, self.bitumen_v1.id)

        # 2. Add and publish Bitumen v2 with a new required attribute
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
            key="flash_point",
            label_fa="نقطه اشتعال",
            label_en="Flash Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,  # New required attribute in v2!
            sort_order=2,
        )
        publish_schema(bitumen_v2, activate=True)

        # 3. Verify commodity active schema is now v2
        self.bitumen.refresh_from_db()
        self.assertEqual(self.bitumen.active_schema_version_id, bitumen_v2.id)

        # 4. Verify existing RFQ continues referencing v1
        rfq.refresh_from_db()
        self.assertEqual(rfq.schema_version_id, self.bitumen_v1.id)
        self.assertEqual(rfq.schema_version.version, 1)

        # 5. Specifications continue to pass validation against RFQ's bound v1 schema
        validate_commodity_payload(rfq.schema_version, rfq.specifications)

        # 6. Had the specifications been validated against v2, it would fail due to missing flash_point
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(bitumen_v2, rfq.specifications)
        error_fields = [err["field"] for err in ctx.exception.params.get("errors", [])]
        self.assertIn("flash_point", error_fields)

    # ------------------------------------------------------------------
    # 4. Numeric Integrity & PostgreSQL Constraints
    # ------------------------------------------------------------------
    def test_zero_quantity_rejected_by_db_constraint(self):
        """Database check constraint rejects zero quantity upon direct persistence."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("0.000"),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                super(RFQ, rfq).save(force_insert=True)

    def test_negative_quantity_rejected_by_db_constraint(self):
        """Database check constraint rejects negative quantity upon direct persistence."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("-100.000"),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                super(RFQ, rfq).save(force_insert=True)

    def test_negative_target_price_rejected_by_db_constraint(self):
        """Database check constraint rejects negative target price upon direct persistence."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("100.000"),
            target_price=Decimal("-1.00"),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                super(RFQ, rfq).save(force_insert=True)

    def test_invalid_delivery_window_ordering_rejected_by_db_constraint(self):
        """Database check constraint rejects delivery window end prior to start upon direct persistence."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("100.000"),
            delivery_window_start=datetime.date(2026, 11, 20),
            delivery_window_end=datetime.date(2026, 11, 10),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                super(RFQ, rfq).save(force_insert=True)

    def test_invalid_version_rejected_by_db_constraint(self):
        """Database check constraint rejects version < 1 upon direct persistence."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("100.000"),
            version=0,
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                super(RFQ, rfq).save(force_insert=True)

    def test_model_clean_validation_detects_invalid_numerics(self):
        """Model clean() raises ValidationError for invalid numeric and date ranges."""
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("-5.000"),
            target_price=Decimal("-10.00"),
            delivery_window_start=datetime.date(2026, 11, 20),
            delivery_window_end=datetime.date(2026, 11, 10),
            version=0,
        )
        with self.assertRaises(ValidationError) as ctx:
            rfq.clean()
        errors = ctx.exception.message_dict
        self.assertIn("quantity", errors)
        self.assertIn("target_price", errors)
        self.assertIn("delivery_window_end", errors)
        self.assertIn("version", errors)

    # ------------------------------------------------------------------
    # 5. Enum Integrity
    # ------------------------------------------------------------------
    def test_invalid_status_rejected_by_db_constraint(self):
        """Database check constraint rejects arbitrary invalid status strings."""
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                RFQ.objects.create(
                    organization=self.buyer_org,
                    commodity=self.bitumen,
                    schema_version=self.bitumen_v1,
                    quantity=Decimal("100.000"),
                    status="arbitrary_status",
                )

    def test_invalid_visibility_rejected_by_db_constraint(self):
        """Database check constraint rejects arbitrary invalid visibility strings."""
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                RFQ.objects.create(
                    organization=self.buyer_org,
                    commodity=self.bitumen,
                    schema_version=self.bitumen_v1,
                    quantity=Decimal("100.000"),
                    visibility="broadcast_all",
                )

    # ------------------------------------------------------------------
    # 6. Cross-Commodity Schema Relationship Integrity
    # ------------------------------------------------------------------
    def test_mismatched_commodity_and_schema_version_rejected(self):
        """
        An RFQ cannot reference a schema version belonging to a different commodity
        (e.g., Bitumen RFQ referencing Base Oil schema version).
        """
        rfq = RFQ(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.base_oil_v1,  # Base Oil schema for Bitumen commodity!
            quantity=Decimal("500.000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rfq.clean()
        self.assertIn("schema_version", ctx.exception.message_dict)

        # save() calls clean(), so direct save also raises ValidationError
        with self.assertRaises(ValidationError):
            rfq.save()

    # ------------------------------------------------------------------
    # 7. Historical Deletion Protection
    # ------------------------------------------------------------------
    def test_buyer_organization_protected_from_deletion(self):
        """An organization cannot be deleted while referenced by an RFQ."""
        RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
        )
        with self.assertRaises(models.ProtectedError):
            self.buyer_org.delete()

    def test_commodity_definition_protected_from_deletion(self):
        """A CommodityDefinition cannot be deleted while referenced by an RFQ."""
        RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
        )
        with self.assertRaises((models.ProtectedError, ValidationError)):
            self.bitumen.delete()

    def test_commodity_schema_version_protected_from_deletion(self):
        """A CommoditySchemaVersion cannot be deleted while referenced by an RFQ."""
        RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
        )
        with self.assertRaises((models.ProtectedError, ValidationError)):
            self.bitumen_v1.delete()

    # ------------------------------------------------------------------
    # 8. Optimistic Concurrency Foundation
    # ------------------------------------------------------------------
    def test_version_initialization_and_increment(self):
        """Aggregate version defaults to 1 and increments properly."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
        )
        self.assertEqual(rfq.version, 1)
        rfq.version += 1
        rfq.save()
        rfq.refresh_from_db()
        self.assertEqual(rfq.version, 2)

    # ------------------------------------------------------------------
    # 9. Edge Cases & Boundary Conditions
    # ------------------------------------------------------------------
    def test_null_target_price_permitted(self):
        """Target price is optional; null target price persists cleanly."""
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
            target_price=None,
        )
        self.assertIsNone(rfq.target_price)

    def test_same_day_delivery_window_permitted(self):
        """Delivery window start and end on the same day is valid."""
        today = datetime.date.today()
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
            delivery_window_start=today,
            delivery_window_end=today,
        )
        self.assertEqual(rfq.delivery_window_start, rfq.delivery_window_end)

    def test_partial_delivery_windows_permitted(self):
        """Having only start date or only end date is valid."""
        today = datetime.date.today()
        rfq_start_only = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
            delivery_window_start=today,
            delivery_window_end=None,
        )
        self.assertIsNotNone(rfq_start_only.delivery_window_start)
        self.assertIsNone(rfq_start_only.delivery_window_end)

        rfq_end_only = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
            delivery_window_start=None,
            delivery_window_end=today,
        )
        self.assertIsNone(rfq_end_only.delivery_window_start)
        self.assertIsNotNone(rfq_end_only.delivery_window_end)

    def test_creator_tracking_and_operator_flag(self):
        """Created_by user relationship and created_by_operator flag persist."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(email="procurement_officer@example.com", password="password123")

        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("500.000"),
            created_by=user,
            created_by_operator=True,
        )
        self.assertEqual(rfq.created_by, user)
        self.assertTrue(rfq.created_by_operator)

        # Deleting creator is protected
        with self.assertRaises(models.ProtectedError):
            user.delete()

