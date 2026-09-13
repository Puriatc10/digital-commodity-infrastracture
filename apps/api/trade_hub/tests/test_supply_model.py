import datetime
from decimal import Decimal

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
from trade_hub.models import SupplyListing, SupplyListingStatus, SupplyListingVisibility


class SupplyListingModelTests(TestCase):
    def setUp(self):
        # Setup supplier organization with supplier capability
        self.supplier_org = Organization.objects.create(
            name="Gulf Petroleum Supplies LLC",
            registration_identifier="REG-SUP-987",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
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

        # Setup Base Oil commodity and published v1 schema (second commodity)
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
    def test_valid_generic_supply_listing_persists(self):
        """A valid SupplyListing persists with correct initial states, foreign keys, and values."""
        listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("3000.000"),
            unit="MT",
            indicative_price=Decimal("360.00"),
            currency="USD",
            payment_terms="LC at sight",
            incoterm="FOB",
            origin="Bandar Abbas",
            destination="Global",
            availability_window_start=datetime.date(2026, 10, 1),
            availability_window_end=datetime.date(2026, 10, 31),
            quality_notes="Third-party SGS inspection certificates available upon request.",
            notes="Refinery batch 2026-Q3.",
            status=SupplyListingStatus.DRAFT,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        self.assertIsNotNone(listing.id)
        self.assertEqual(listing.organization, self.supplier_org)
        self.assertEqual(listing.supplier, self.supplier_org)
        self.assertEqual(listing.commodity, self.bitumen)
        self.assertEqual(listing.schema_version, self.bitumen_v1)
        self.assertEqual(listing.quantity, Decimal("3000.000"))
        self.assertEqual(listing.unit, "MT")
        self.assertEqual(listing.indicative_price, Decimal("360.00"))
        self.assertEqual(listing.currency, "USD")
        self.assertEqual(listing.origin, "Bandar Abbas")
        self.assertEqual(listing.status, SupplyListingStatus.DRAFT)
        self.assertEqual(listing.visibility, SupplyListingVisibility.PUBLIC)
        self.assertEqual(listing.version, 1)
        self.assertIsNone(listing.activated_at)
        self.assertIsNone(listing.closed_at)
        self.assertIsNone(listing.expired_at)

    def test_second_commodity_base_oil_persists_without_code_changes(self):
        """Verify dynamic commodity genericity: Base Oil supply listing persists cleanly."""
        listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.base_oil,
            schema_version=self.base_oil_v1,
            specifications={"viscosity_index": 95},
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("850.00"),
            currency="USD",
            origin="Singapore",
            status=SupplyListingStatus.DRAFT,
            visibility=SupplyListingVisibility.NETWORK,
        )
        self.assertIsNotNone(listing.id)
        self.assertEqual(listing.commodity.code, "base_oil")
        self.assertEqual(listing.specifications["viscosity_index"], 95)
        self.assertEqual(listing.visibility, SupplyListingVisibility.NETWORK)

    def test_supplier_property_alias(self):
        """Verify supplier getter and setter property alias to organization."""
        listing = SupplyListing(supplier=self.supplier_org)
        self.assertEqual(listing.organization, self.supplier_org)
        self.assertEqual(listing.supplier, self.supplier_org)

        new_org = Organization.objects.create(name="Second Supplier", country="OM", is_active=True)
        listing.supplier = new_org
        self.assertEqual(listing.organization, new_org)
        self.assertEqual(listing.supplier, new_org)

    # ------------------------------------------------------------------
    # 2. Dynamic Specifications Validation
    # ------------------------------------------------------------------
    def test_invalid_dynamic_specifications_fail_validation(self):
        """Invalid dynamic specification payload fails validate_commodity_payload."""
        # Missing required penetration_grade
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.bitumen_v1, {"softening_point": 49.5})
        errors = ctx.exception.params.get("errors", [])
        field_names = [e["field"] for e in errors]
        self.assertIn("penetration_grade", field_names)

        # Wrong data type for softening_point (string instead of number)
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(
                self.bitumen_v1,
                {"penetration_grade": "60/70", "softening_point": "not_a_number"},
            )
        errors = ctx.exception.params.get("errors", [])
        field_names = [e["field"] for e in errors]
        self.assertIn("softening_point", field_names)

    def test_commodity_schema_version_mismatch_rejected_in_clean(self):
        """Attaching a schema version belonging to Base Oil to a Bitumen listing is rejected."""
        listing = SupplyListing(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.base_oil_v1,  # Mismatched commodity schema version
            quantity=Decimal("1000.000"),
            specifications={"penetration_grade": "60/70"},
        )
        with self.assertRaises(ValidationError) as ctx:
            listing.clean()
        self.assertIn("schema_version", ctx.exception.message_dict)

    # ------------------------------------------------------------------
    # 3. Availability Window Validation & Constraints
    # ------------------------------------------------------------------
    def test_inverted_availability_window_rejected_in_clean(self):
        """Availability window where end is before start raises ValidationError in clean()."""
        listing = SupplyListing(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("1000.000"),
            specifications={"penetration_grade": "60/70"},
            availability_window_start=datetime.date(2026, 11, 15),
            availability_window_end=datetime.date(2026, 11, 1),
        )
        with self.assertRaises(ValidationError) as ctx:
            listing.clean()
        self.assertIn("availability_window_end", ctx.exception.message_dict)

    def test_inverted_availability_window_rejected_by_db_constraint(self):
        """Direct database insertion with invalid availability window violates check constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([
                    SupplyListing(
                        organization=self.supplier_org,
                        commodity=self.bitumen,
                        schema_version=self.bitumen_v1,
                        quantity=Decimal("1000.000"),
                        specifications={"penetration_grade": "60/70"},
                        availability_window_start=datetime.date(2026, 11, 15),
                        availability_window_end=datetime.date(2026, 11, 1),
                    )
                ])

    # ------------------------------------------------------------------
    # 4. Numeric and Value CheckConstraints
    # ------------------------------------------------------------------
    def test_zero_or_negative_quantity_rejected_in_clean(self):
        """Non-positive quantities are rejected in clean()."""
        for bad_qty in [Decimal("0"), Decimal("-10.500")]:
            with self.subTest(quantity=bad_qty):
                listing = SupplyListing(
                    organization=self.supplier_org,
                    commodity=self.bitumen,
                    schema_version=self.bitumen_v1,
                    quantity=bad_qty,
                    specifications={"penetration_grade": "60/70"},
                )
                with self.assertRaises(ValidationError) as ctx:
                    listing.clean()
                self.assertIn("quantity", ctx.exception.message_dict)

    def test_zero_or_negative_quantity_rejected_by_db_constraint(self):
        """Zero or negative quantity violates check_positive_supply_listing_quantity constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([
                    SupplyListing(
                        organization=self.supplier_org,
                        commodity=self.bitumen,
                        schema_version=self.bitumen_v1,
                        quantity=Decimal("0"),
                        specifications={"penetration_grade": "60/70"},
                    )
                ])

    def test_negative_indicative_price_rejected(self):
        """Negative indicative price violates check_positive_supply_listing_price constraint."""
        listing = SupplyListing(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("100.000"),
            indicative_price=Decimal("-50.00"),
            specifications={"penetration_grade": "60/70"},
        )
        with self.assertRaises(ValidationError) as ctx:
            listing.clean()
        self.assertIn("indicative_price", ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([listing])

    def test_version_must_be_positive(self):
        """Version < 1 violates check_positive_supply_listing_version constraint."""
        listing = SupplyListing(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            quantity=Decimal("100.000"),
            version=0,
            specifications={"penetration_grade": "60/70"},
        )
        with self.assertRaises(ValidationError) as ctx:
            listing.clean()
        self.assertIn("version", ctx.exception.message_dict)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([listing])

    def test_invalid_status_rejected_by_db_constraint(self):
        """Status not in SupplyListingStatus enum violates check_valid_supply_listing_status."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([
                    SupplyListing(
                        organization=self.supplier_org,
                        commodity=self.bitumen,
                        schema_version=self.bitumen_v1,
                        quantity=Decimal("100.000"),
                        status="bogus_status",
                        specifications={"penetration_grade": "60/70"},
                    )
                ])

    def test_invalid_visibility_rejected_by_db_constraint(self):
        """Visibility not in SupplyListingVisibility enum violates check_valid_supply_listing_visibility."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SupplyListing.objects.bulk_create([
                    SupplyListing(
                        organization=self.supplier_org,
                        commodity=self.bitumen,
                        schema_version=self.bitumen_v1,
                        quantity=Decimal("100.000"),
                        visibility="secret_visibility",
                        specifications={"penetration_grade": "60/70"},
                    )
                ])

    # ------------------------------------------------------------------
    # 5. Immutability Enforcements Post-Activation
    # ------------------------------------------------------------------
    def test_post_activation_immutability_enforced(self):
        """Core commercial and technical fields cannot be modified after activation."""
        listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            indicative_price=Decimal("350.00"),
            origin="Bandar Abbas",
            status=SupplyListingStatus.ACTIVE,
            version=2,
        )

        mutations = [
            ("quantity", Decimal("2000.000")),
            ("indicative_price", Decimal("400.00")),
            ("origin", "Jebel Ali"),
            ("specifications", {"penetration_grade": "85/100"}),
            ("payment_terms", "TT 100% advance"),
            ("incoterm", "CIF"),
        ]

        for field, new_val in mutations:
            with self.subTest(field=field):
                reloaded = SupplyListing.objects.get(pk=listing.pk)
                setattr(reloaded, field, new_val)
                with self.assertRaises(ValidationError) as ctx:
                    reloaded.save()
                self.assertIn("Core fields cannot be modified after activation", str(ctx.exception))

    def test_cannot_mutate_core_fields_and_activate_simultaneously(self):
        """Draft listing cannot change core fields and set status=ACTIVE in a single unvalidated save."""
        draft = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        draft.quantity = Decimal("9999.000")
        draft.status = SupplyListingStatus.ACTIVE
        with self.assertRaises(ValidationError) as ctx:
            draft.save()
        self.assertIn("Core fields cannot be modified during activation", str(ctx.exception))

    def test_draft_core_fields_freely_mutable_before_activation(self):
        """Draft listing core fields can be updated and saved without error before activation."""
        draft = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )
        draft.quantity = Decimal("450.000")
        draft.specifications = {"penetration_grade": "85/100", "softening_point": 51.0}
        draft.origin = "Sharjah"
        draft.save()

        reloaded = SupplyListing.objects.get(pk=draft.pk)
        self.assertEqual(reloaded.quantity, Decimal("450.000"))
        self.assertEqual(reloaded.specifications["penetration_grade"], "85/100")
        self.assertEqual(reloaded.origin, "Sharjah")

    # ------------------------------------------------------------------
    # 6. Foreign Key Deletion Protection (on_delete=models.PROTECT)
    # ------------------------------------------------------------------
    def test_foreign_keys_protected_from_deletion(self):
        """Referenced Organization, CommodityDefinition, and CommoditySchemaVersion are protected."""
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
        )

        with self.assertRaises(models.ProtectedError):
            self.supplier_org.delete()

        with self.assertRaises(models.ProtectedError):
            self.bitumen.delete()

        with self.assertRaises(models.ProtectedError):
            self.bitumen_v1.delete()
