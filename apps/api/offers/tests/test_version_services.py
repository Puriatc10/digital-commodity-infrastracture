from datetime import date, timedelta
from decimal import Decimal
import uuid

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferImmutableError,
    OfferStateError,
    OfferValidationError,
    StaleVersionError,
)
from offers.models import OfferVersion
from offers.services import (
    create_draft_offer_version,
    create_offer,
    submit_offer_version,
    update_draft_offer_version,
)
from offers.tests.base import BaseOffersTestCase
from trade_hub.models import RFQ, RFQStatus, RFQVisibility


class OfferVersionServiceTests(BaseOffersTestCase):
    """
    Tests for OfferVersion domain services:
    - create_draft_offer_version
    - update_draft_offer_version
    - submit_offer_version
    - Historical integrity proof (V1 submitted, V2 draft mutated, V1 preserved)
    - Dynamic commodity genericity across two commodities
    - Schema version lock vs active schema evolution
    - Concurrency and expected_version invariants
    """

    def setUp(self):
        super().setUp()
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_create_draft_offer_version_success(self):
        """Creating an initial draft allocates V1 and increments aggregate_version without setting current_submitted_version."""
        initial_agg_ver = self.offer.aggregate_version

        draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("420.00"),
            currency="USD",
            payment_terms="LC 60 days",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            delivery_start=date.today() + timedelta(days=10),
            delivery_end=date.today() + timedelta(days=20),
            specifications={"penetration_grade": "60/70"},
            notes="Initial draft proposal",
        )

        self.assertEqual(draft.version_number, 1)
        self.assertEqual(draft.status, OfferVersionStatus.DRAFT)
        self.assertEqual(draft.offered_quantity, Decimal("300.000"))
        self.assertEqual(draft.unit_price, Decimal("420.00"))
        self.assertEqual(draft.currency, "USD")
        self.assertEqual(draft.schema_version, self.published_rfq.schema_version)
        self.assertEqual(draft.created_by, self.supplier_user)
        self.assertIsNone(draft.submitted_by)
        self.assertIsNone(draft.submitted_at)

        self.offer.refresh_from_db()
        self.assertIsNone(self.offer.current_submitted_version)
        self.assertEqual(self.offer.aggregate_version, initial_agg_ver + 1)

    def test_sequential_version_number_allocation(self):
        """Server sequentially allocates V1, V2, V3 across submit-then-draft cycles."""
        # Cycle 1: V1
        v1_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v1_draft.version_number, 1)
        v1_submitted = submit_offer_version(actor=self.supplier_user, offer_version=v1_draft)
        self.assertEqual(v1_submitted.version_number, 1)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v1_submitted.id)

        # Cycle 2: V2
        v2_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("390.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v2_draft.version_number, 2)
        v2_submitted = submit_offer_version(actor=self.supplier_user, offer_version=v2_draft)
        self.assertEqual(v2_submitted.version_number, 2)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v2_submitted.id)

        # Cycle 3: V3
        v3_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("380.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v3_draft.version_number, 3)

    def test_cannot_create_draft_when_draft_already_exists(self):
        """Attempting to create a second draft on the same Offer raises OfferConflictError."""
        create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )

        with self.assertRaises(OfferConflictError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("150.000"),
                quantity_unit="MT",
                unit_price=Decimal("395.00"),
                currency="USD",
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("already has an active draft", str(ctx.exception))

    def test_rfq_schema_lock_and_dynamic_specification_validation(self):
        """OfferVersion is forced to RFQ schema_version and validates dynamic specifications."""
        # Valid payload succeeds
        v = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v.schema_version, self.published_rfq.schema_version)

        # Submit it so we can test invalid specs on next draft
        submit_offer_version(actor=self.supplier_user, offer_version=v)

        # Invalid specifications payload (missing required penetration_grade) fails validate_commodity_payload
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                specifications={"invalid_attr": "value"},  # missing required penetration_grade
            )
        self.assertIn("Dynamic specifications failed schema validation", str(ctx.exception))

    def test_schema_valid_vs_rfq_compliance(self):
        """A schema-valid Offer is accepted even if specification values differ from RFQ demand."""
        # RFQ requested penetration_grade: 60/70
        # Supplier offers penetration_grade: 85/100 (which is a valid string for the attribute schema)
        v = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("380.00"),
            currency="USD",
            specifications={"penetration_grade": "85/100"},
        )
        self.assertEqual(v.specifications["penetration_grade"], "85/100")
        submitted = submit_offer_version(actor=self.supplier_user, offer_version=v)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

    def test_partial_and_surplus_quantities_allowed_without_capping(self):
        """Partial quantity (< RFQ) and surplus quantity (> RFQ) are both stored without capping."""
        # RFQ requested 500 MT
        # 1. Partial quantity: 150 MT
        v_partial = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("150.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v_partial.offered_quantity, Decimal("150.000"))
        submit_offer_version(actor=self.supplier_user, offer_version=v_partial)

        # 2. Surplus quantity: 950 MT
        v_surplus = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("950.000"),
            quantity_unit="MT",
            unit_price=Decimal("370.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v_surplus.offered_quantity, Decimal("950.000"))
        submit_offer_version(actor=self.supplier_user, offer_version=v_surplus)
        v_surplus.refresh_from_db()
        self.assertEqual(v_surplus.offered_quantity, Decimal("950.000"))

    def test_quantity_unit_compatibility_rejection(self):
        """Incompatible quantity unit raises OfferValidationError."""
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="BARRELS",  # RFQ is in MT
                unit_price=Decimal("400.00"),
                currency="USD",
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("is incompatible with RFQ unit", str(ctx.exception))

    def test_price_and_currency_exact_preservation(self):
        """Unit price Decimal and currency code are stored exactly without FX mutation."""
        draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("387.65"),
            currency="EUR",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(draft.unit_price, Decimal("387.65"))
        self.assertEqual(draft.currency, "EUR")

        submitted = submit_offer_version(actor=self.supplier_user, offer_version=draft)
        submitted.refresh_from_db()
        self.assertEqual(submitted.unit_price, Decimal("387.65"))
        self.assertEqual(submitted.currency, "EUR")

    def test_logistics_cost_statuses_and_validation(self):
        """All four logistics statuses behave according to exact specifications."""
        # 1. KNOWN_SEPARATE requires amount
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
                logistics_cost_amount=None,
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("logistics_cost_amount is required", str(ctx.exception))

        # 2. INCLUDED_IN_PRICE forbids amount
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
                logistics_cost_amount=Decimal("15.00"),
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("logistics_cost_amount must be absent", str(ctx.exception))

        # 3. UNKNOWN forbids amount (cannot encode UNKNOWN as 0)
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                logistics_cost_status=LogisticsCostStatus.UNKNOWN,
                logistics_cost_amount=Decimal("0.00"),
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("logistics_cost_amount must be absent", str(ctx.exception))

        # 4. KNOWN_SEPARATE with valid amount succeeds
        v = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("35.50"),
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(v.logistics_cost_status, LogisticsCostStatus.KNOWN_SEPARATE)
        self.assertEqual(v.logistics_cost_amount, Decimal("35.50"))

    def test_delivery_window_date_validation(self):
        """delivery_start <= delivery_end enforced at service level."""
        today = date.today()
        with self.assertRaises(OfferValidationError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                delivery_start=today + timedelta(days=10),
                delivery_end=today + timedelta(days=5),  # start > end
                specifications={"penetration_grade": "60/70"},
            )
        self.assertIn("delivery_start cannot be after delivery_end", str(ctx.exception))

    def test_update_draft_offer_version_success_and_immutability_protection(self):
        """Draft version can be updated; server-owned fields remain protected; submitted version rejects update."""
        draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            notes="Original note",
        )

        updated = update_draft_offer_version(
            actor=self.supplier_user,
            offer_version=draft,
            offered_quantity=Decimal("120.000"),
            unit_price=Decimal("395.00"),
            notes="Revised draft note",
        )
        self.assertEqual(updated.offered_quantity, Decimal("120.000"))
        self.assertEqual(updated.unit_price, Decimal("395.00"))
        self.assertEqual(updated.notes, "Revised draft note")
        self.assertEqual(updated.version_number, 1)  # version_number unchangeable

        # Submit version
        submitted = submit_offer_version(actor=self.supplier_user, offer_version=updated)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

        # Attempt to update submitted version raises OfferImmutableError
        with self.assertRaises(OfferImmutableError) as ctx:
            update_draft_offer_version(
                actor=self.supplier_user,
                offer_version=submitted,
                offered_quantity=Decimal("130.000"),
            )
        self.assertIn("cannot be edited", str(ctx.exception))

    def test_historical_integrity_proof_v1_and_v2(self):
        """
        Comprehensive Historical Integrity Proof:
        1. V1 submitted.
        2. V2 draft created.
        3. Every commercial field changed in V2.
        4. Assert V1 remains completely untouched.
        5. Submit V2 -> current pointer becomes V2.
        6. V1 still exists completely unchanged in database.
        """
        # Step 1: Create and submit V1
        v1_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            payment_terms="LC 30 days",
            delivery_terms="CIF Bandar Abbas",
            incoterm="CIF",
            delivery_start=date(2026, 10, 1),
            delivery_end=date(2026, 10, 15),
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("30.00"),
            specifications={"penetration_grade": "60/70"},
            notes="V1 notes",
            cost_components=[
                {"kind": CostComponentKind.LOGISTICS, "amount": Decimal("30.00"), "currency": "USD", "description": "Freight"},
            ],
        )
        v1_submitted = submit_offer_version(actor=self.supplier_user, offer_version=v1_draft)

        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v1_submitted.id)
        self.assertEqual(v1_submitted.version_number, 1)

        # Step 2: Create V2 draft
        v2_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("365.00"),
            currency="USD",
            payment_terms="TT 100% advance",
            delivery_terms="FOB Jebel Ali",
            incoterm="FOB",
            delivery_start=date(2026, 11, 1),
            delivery_end=date(2026, 11, 20),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            logistics_cost_amount=None,
            specifications={"penetration_grade": "60/70"},
            notes="V2 revised proposal",
        )
        self.assertEqual(v2_draft.version_number, 2)

        # Step 3: Mutate every field on V2 draft
        update_draft_offer_version(
            actor=self.supplier_user,
            offer_version=v2_draft,
            offered_quantity=Decimal("275.000"),
            unit_price=Decimal("360.00"),
            payment_terms="LC 90 days",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            delivery_start=date(2026, 11, 5),
            delivery_end=date(2026, 11, 25),
            logistics_cost_status=LogisticsCostStatus.NOT_APPLICABLE,
            notes="V2 final revised proposal",
        )

        # Step 4: Assert V1 remains completely untouched
        v1_persisted = OfferVersion.objects.get(pk=v1_submitted.pk)
        self.assertEqual(v1_persisted.version_number, 1)
        self.assertEqual(v1_persisted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(v1_persisted.offered_quantity, Decimal("100.000"))
        self.assertEqual(v1_persisted.unit_price, Decimal("400.00"))
        self.assertEqual(v1_persisted.payment_terms, "LC 30 days")
        self.assertEqual(v1_persisted.delivery_terms, "CIF Bandar Abbas")
        self.assertEqual(v1_persisted.incoterm, "CIF")
        self.assertEqual(v1_persisted.delivery_start, date(2026, 10, 1))
        self.assertEqual(v1_persisted.delivery_end, date(2026, 10, 15))
        self.assertEqual(v1_persisted.logistics_cost_status, LogisticsCostStatus.KNOWN_SEPARATE)
        self.assertEqual(v1_persisted.logistics_cost_amount, Decimal("30.00"))
        self.assertEqual(v1_persisted.notes, "V1 notes")
        self.assertEqual(v1_persisted.cost_components.count(), 1)
        self.assertEqual(v1_persisted.cost_components.first().amount, Decimal("30.00"))

        # Current pointer is STILL V1 before V2 submission
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v1_submitted.id)

        # Step 5: Submit V2
        v2_submitted = submit_offer_version(actor=self.supplier_user, offer_version=v2_draft)

        # Current pointer now points to V2
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version_id, v2_submitted.id)
        self.assertEqual(v2_submitted.version_number, 2)
        self.assertEqual(v2_submitted.offered_quantity, Decimal("275.000"))

        # Step 6: Assert V1 still exists completely unchanged in database
        v1_after = OfferVersion.objects.get(pk=v1_submitted.pk)
        self.assertEqual(v1_after.version_number, 1)
        self.assertEqual(v1_after.offered_quantity, Decimal("100.000"))
        self.assertEqual(v1_after.unit_price, Decimal("400.00"))
        self.assertEqual(v1_after.payment_terms, "LC 30 days")
        self.assertEqual(v1_after.status, OfferVersionStatus.SUBMITTED)

    def test_commodity_genericity_across_two_commodities(self):
        """Dynamic specification validation works generically across different commodities without branching."""
        # 1. First Commodity: Bitumen (used above)
        bitumen_version = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.assertEqual(bitumen_version.specifications, {"penetration_grade": "60/70"})
        submit_offer_version(actor=self.supplier_user, offer_version=bitumen_version)

        # 2. Second Commodity: Base Oil
        base_oil_def = CommodityDefinition.objects.create(
            code=f"base_oil_{uuid.uuid4().hex[:6]}",
            name_fa="روغن پایه",
            name_en="Base Oil",
            is_active=True,
        )
        base_oil_schema = CommoditySchemaVersion.objects.create(
            commodity=base_oil_def,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=base_oil_schema,
            key="viscosity_index",
            label_fa="شاخص گرانروی",
            label_en="Viscosity Index",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=1,
        )
        publish_schema(base_oil_schema, activate=True)

        base_oil_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=base_oil_def,
            schema_version=base_oil_schema,
            specifications={"viscosity_index": 95},
            quantity=Decimal("200.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        base_oil_offer = create_offer(
            actor=self.supplier_user,
            rfq=base_oil_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        base_oil_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=base_oil_offer,
            offered_quantity=Decimal("150.000"),
            quantity_unit="MT",
            unit_price=Decimal("900.00"),
            currency="USD",
            specifications={"viscosity_index": 100},
        )
        self.assertEqual(base_oil_v1.specifications, {"viscosity_index": 100})
        submitted_bo = submit_offer_version(actor=self.supplier_user, offer_version=base_oil_v1)
        self.assertEqual(submitted_bo.status, OfferVersionStatus.SUBMITTED)

    def test_schema_version_evolution_preserves_rfq_schema(self):
        """
        Mandatory Schema Test:
        RFQ S1
        OfferVersion S1 -> valid
        Then activate S2/S3 on Commodity.
        Historical OfferVersion remains S1; new version on RFQ continues using S1.
        """
        # Offer V1 on RFQ with schema V1
        v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        v1_submitted = submit_offer_version(actor=self.supplier_user, offer_version=v1)
        self.assertEqual(v1_submitted.schema_version.version, 1)

        # Now evolve the commodity to Schema V2 and activate it
        s2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=s2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=s2,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=2,
        )
        publish_schema(s2, activate=True)

        # Verify commodity active schema is now S2
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version.version, 2)

        # V1 submitted version in database still points to S1
        v1_submitted.refresh_from_db()
        self.assertEqual(v1_submitted.schema_version.version, 1)

        # Creating a new V2 draft on this RFQ strictly inherits RFQ's S1 (does NOT substitute active S2)
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("390.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},  # S1 only requires penetration_grade
        )
        self.assertEqual(v2.schema_version.version, 1)
        self.assertEqual(v2.schema_version.id, self.published_rfq.schema_version_id)

    def test_expected_version_optimistic_concurrency(self):
        """expected_version validation prevents mutations against stale aggregate state."""
        # Current offer aggregate_version is 1
        self.assertEqual(self.offer.aggregate_version, 1)

        # Stale expected_version raises StaleVersionError
        with self.assertRaises(StaleVersionError) as ctx:
            create_draft_offer_version(
                actor=self.supplier_user,
                offer=self.offer,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("400.00"),
                currency="USD",
                specifications={"penetration_grade": "60/70"},
                expected_version=99,  # stale!
            )
        self.assertIn("Stale version error", str(ctx.exception))

        # Invalid expected_version (negative or non-int) raises InvalidVersionError
        for invalid_v in [-1, "one", 1.5, True]:
            with self.subTest(v=invalid_v):
                with self.assertRaises(InvalidVersionError):
                    create_draft_offer_version(
                        actor=self.supplier_user,
                        offer=self.offer,
                        offered_quantity=Decimal("100.000"),
                        quantity_unit="MT",
                        unit_price=Decimal("400.00"),
                        currency="USD",
                        specifications={"penetration_grade": "60/70"},
                        expected_version=invalid_v,
                    )

        # Correct expected_version=1 succeeds
        draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            expected_version=1,
        )
        self.assertEqual(draft.version_number, 1)

        # Offer aggregate_version is now 2
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 2)

        # Submitting with stale expected_version=1 raises StaleVersionError
        with self.assertRaises(StaleVersionError):
            submit_offer_version(
                actor=self.supplier_user,
                offer_version=draft,
                expected_version=1,  # stale! current is 2
            )

        # Submitting with correct expected_version=2 succeeds
        submitted = submit_offer_version(
            actor=self.supplier_user,
            offer_version=draft,
            expected_version=2,
        )
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 3)

    def test_cannot_create_version_on_closed_or_cancelled_rfq(self):
        """RFQ in Closed, Cancelled, or Awarded status rejects new OfferVersion creation."""
        for terminal_status in [RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED]:
            with self.subTest(status=terminal_status):
                self.published_rfq.status = terminal_status
                self.published_rfq.save(update_fields=["status"])

                with self.assertRaises(OfferStateError) as ctx:
                    create_draft_offer_version(
                        actor=self.supplier_user,
                        offer=self.offer,
                        offered_quantity=Decimal("100.000"),
                        quantity_unit="MT",
                        unit_price=Decimal("400.00"),
                        currency="USD",
                        specifications={"penetration_grade": "60/70"},
                    )
                self.assertIn("can only be added", str(ctx.exception))
