from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from offers.enums import CostComponentKind, LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.models import Offer, OfferCostComponent, OfferVersion
from offers.tests.base import BaseOffersTestCase


class OfferVersionModelConstraintTests(BaseOffersTestCase):
    """
    Direct database constraint and model validation tests for OfferVersion and OfferCostComponent.
    Ensures PostgreSQL CheckConstraints and UniqueConstraints enforce invariants directly.
    """

    def setUp(self):
        super().setUp()
        self.offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )

    def test_one_draft_per_offer_unique_constraint(self):
        """PostgreSQL conditional UniqueConstraint permits at most one DRAFT per Offer."""
        OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.supplier_user,
        )

        # Second draft on same offer fails conditional unique constraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfferVersion.objects.create(
                    offer=self.offer,
                    version_number=2,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("150.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("360.00"),
                    currency="USD",
                    created_by=self.supplier_user,
                )

    def test_multiple_submitted_versions_allowed(self):
        """Multiple SUBMITTED versions can coexist on the same Offer."""
        OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )
        OfferVersion.objects.create(
            offer=self.offer,
            version_number=2,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )
        self.assertEqual(self.offer.versions.filter(status=OfferVersionStatus.SUBMITTED).count(), 2)


    def test_version_number_unique_per_offer(self):
        """Duplicate version_number on the same Offer fails UniqueConstraint."""
        OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfferVersion.objects.create(
                    offer=self.offer,
                    version_number=1,  # duplicate version 1
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    created_by=self.supplier_user,
                )

    def test_offered_quantity_must_be_positive_check_constraint(self):
        """Zero and negative offered_quantity fail PostgreSQL CheckConstraint."""
        for invalid_qty in [Decimal("0.000"), Decimal("-10.500")]:
            with self.subTest(qty=invalid_qty):
                with self.assertRaises((IntegrityError, ValidationError)):
                    with transaction.atomic():
                        v = OfferVersion(
                            offer=self.offer,
                            version_number=1,
                            status=OfferVersionStatus.DRAFT,
                            schema_version=self.schema_version,
                            specifications={"penetration_grade": "60/70"},
                            offered_quantity=invalid_qty,
                            quantity_unit="MT",
                            unit_price=Decimal("350.00"),
                            currency="USD",
                            created_by=self.supplier_user,
                        )
                        v.save()

    def test_unit_price_must_be_positive_check_constraint(self):
        """Zero and negative unit_price fail PostgreSQL CheckConstraint."""
        for invalid_price in [Decimal("0.00"), Decimal("-50.00")]:
            with self.subTest(price=invalid_price):
                with self.assertRaises((IntegrityError, ValidationError)):
                    with transaction.atomic():
                        v = OfferVersion(
                            offer=self.offer,
                            version_number=1,
                            status=OfferVersionStatus.DRAFT,
                            schema_version=self.schema_version,
                            specifications={"penetration_grade": "60/70"},
                            offered_quantity=Decimal("100.000"),
                            quantity_unit="MT",
                            unit_price=invalid_price,
                            currency="USD",
                            created_by=self.supplier_user,
                        )
                        v.save()

    def test_delivery_window_valid_check_constraint(self):
        """delivery_start > delivery_end fails PostgreSQL CheckConstraint."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                v = OfferVersion(
                    offer=self.offer,
                    version_number=1,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    delivery_start=today,
                    delivery_end=yesterday,  # invalid: start > end
                    created_by=self.supplier_user,
                )
                v.save()

    def test_logistics_cost_consistency_check_constraint(self):
        """Logistics cost consistency rules are strictly enforced at DB level."""
        # 1. KNOWN_SEPARATE without amount fails
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                v = OfferVersion(
                    offer=self.offer,
                    version_number=1,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
                    logistics_cost_amount=None,  # missing amount!
                    created_by=self.supplier_user,
                )
                v.save()

        # 2. INCLUDED_IN_PRICE with amount fails
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                v = OfferVersion(
                    offer=self.offer,
                    version_number=2,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
                    logistics_cost_amount=Decimal("25.00"),  # must be None!
                    created_by=self.supplier_user,
                )
                v.save()

        # 3. NOT_APPLICABLE with amount fails
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                v = OfferVersion(
                    offer=self.offer,
                    version_number=3,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    logistics_cost_status=LogisticsCostStatus.NOT_APPLICABLE,
                    logistics_cost_amount=Decimal("10.00"),  # must be None!
                    created_by=self.supplier_user,
                )
                v.save()

        # 4. UNKNOWN with amount fails (do not encode UNKNOWN as zero)
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                v = OfferVersion(
                    offer=self.offer,
                    version_number=4,
                    status=OfferVersionStatus.DRAFT,
                    schema_version=self.schema_version,
                    specifications={"penetration_grade": "60/70"},
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("350.00"),
                    currency="USD",
                    logistics_cost_status=LogisticsCostStatus.UNKNOWN,
                    logistics_cost_amount=Decimal("0.00"),  # UNKNOWN cannot be 0!
                    created_by=self.supplier_user,
                )
                v.save()


class OfferVersionImmutabilityTests(BaseOffersTestCase):
    """
    Tests ensuring that SUBMITTED OfferVersion instances and their child cost components
    are strictly immutable at model level.
    """

    def setUp(self):
        super().setUp()
        self.offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        self.submitted_version = OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("410.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="CIF Karachi",
            incoterm="CIF",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("35.00"),
            notes="Initial proposal",
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )
        self.offer.current_submitted_version = self.submitted_version
        self.offer.save(update_fields=["current_submitted_version"])

    def test_submitted_version_rejects_commercial_modifications(self):
        """Direct save on SUBMITTED OfferVersion modifying commercial terms raises ValidationError."""
        mutations = [
            ("offered_quantity", Decimal("350.000")),
            ("unit_price", Decimal("390.00")),
            ("currency", "EUR"),
            ("payment_terms", "TT advance"),
            ("delivery_terms", "FOB Bandar Abbas"),
            ("incoterm", "FOB"),
            ("notes", "Mutated notes"),
            ("specifications", {"penetration_grade": "85/100"}),
            ("logistics_cost_amount", Decimal("40.00")),
            ("status", OfferVersionStatus.DRAFT),
        ]

        for field, new_val in mutations:
            with self.subTest(field=field):
                v = OfferVersion.objects.get(pk=self.submitted_version.pk)
                setattr(v, field, new_val)
                with self.assertRaises(ValidationError) as ctx:
                    v.save()
                self.assertIn("Submitted OfferVersion is immutable", str(ctx.exception))

    def test_submitted_version_rejects_delete(self):
        """Direct delete on SUBMITTED OfferVersion raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            self.submitted_version.delete()
        self.assertIn("Submitted OfferVersion cannot be deleted", str(ctx.exception))

    def test_draft_version_can_be_deleted(self):
        """DRAFT OfferVersion can be deleted normally."""
        # Create second offer for testing draft deletion
        other_offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
            created_by=self.broker_user,
        )
        draft = OfferVersion.objects.create(
            offer=other_offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("300.00"),
            currency="USD",
            created_by=self.broker_user,
        )
        draft_pk = draft.pk
        draft.delete()
        self.assertFalse(OfferVersion.objects.filter(pk=draft_pk).exists())


class OfferCostComponentTests(BaseOffersTestCase):
    """
    Tests for OfferCostComponent constraints, currency alignment, and parent immutability.
    """

    def setUp(self):
        super().setUp()
        self.offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        self.draft_version = OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            created_by=self.supplier_user,
        )

    def test_cost_component_currency_must_match_offer_version(self):
        """Cost component currency must match parent OfferVersion currency."""
        comp = OfferCostComponent(
            offer_version=self.draft_version,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("25.00"),
            currency="EUR",  # mismatch: version is USD
        )
        with self.assertRaises(ValidationError) as ctx:
            comp.save()
        self.assertIn("must match OfferVersion currency", str(ctx.exception))

    def test_cost_component_valid_creation_on_draft(self):
        """Cost component can be attached to DRAFT version."""
        comp = OfferCostComponent.objects.create(
            offer_version=self.draft_version,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("30.00"),
            currency="USD",
            description="Freight and barge",
        )
        self.assertEqual(comp.offer_version, self.draft_version)
        self.assertEqual(self.draft_version.cost_components.count(), 1)

    def test_cost_component_immutable_once_parent_submitted(self):
        """Cannot create, modify, or delete cost components on SUBMITTED parent."""
        # Create cost component while DRAFT
        comp = OfferCostComponent.objects.create(
            offer_version=self.draft_version,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("30.00"),
            currency="USD",
            description="Ocean Freight",
        )

        # Transition parent to SUBMITTED
        self.draft_version.status = OfferVersionStatus.SUBMITTED
        self.draft_version.submitted_by = self.supplier_user
        self.draft_version.submitted_at = timezone.now()
        self.draft_version.save()

        # 1. Attempt create new child under submitted parent
        with self.assertRaises(ValidationError) as ctx:
            OfferCostComponent.objects.create(
                offer_version=self.draft_version,
                kind=CostComponentKind.OTHER,
                amount=Decimal("10.00"),
                currency="USD",
                description="Handling fee",
            )
        self.assertIn("Cannot add or modify cost components", str(ctx.exception))

        # 2. Attempt update existing child under submitted parent
        comp.amount = Decimal("35.00")
        with self.assertRaises(ValidationError) as ctx:
            comp.save()
        self.assertIn("Cannot add or modify cost components", str(ctx.exception))

        # 3. Attempt delete child under submitted parent
        with self.assertRaises(ValidationError) as ctx:
            comp.delete()
        self.assertIn("Cannot delete cost components", str(ctx.exception))


class OfferCurrentSubmittedVersionPointerTests(BaseOffersTestCase):
    """
    Tests enforcing Offer.current_submitted_version pointer invariants.
    """

    def setUp(self):
        super().setUp()
        self.offer_a = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        self.offer_b = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
            created_by=self.broker_user,
        )

    def test_current_pointer_rejects_draft_version(self):
        """Offer.current_submitted_version cannot target a DRAFT version."""
        draft_a = OfferVersion.objects.create(
            offer=self.offer_a,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.supplier_user,
        )

        self.offer_a.current_submitted_version = draft_a
        with self.assertRaises(ValidationError) as ctx:
            self.offer_a.save()
        self.assertIn("must be in SUBMITTED status", str(ctx.exception))

    def test_current_pointer_rejects_version_of_another_offer(self):
        """Offer.current_submitted_version cannot target a version belonging to another Offer."""
        submitted_b = OfferVersion.objects.create(
            offer=self.offer_b,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.broker_user,
            submitted_by=self.broker_user,
            submitted_at=timezone.now(),
        )

        self.offer_a.current_submitted_version = submitted_b  # belonging to offer_b!
        with self.assertRaises(ValidationError) as ctx:
            self.offer_a.save()
        self.assertIn("must belong to this offer", str(ctx.exception))

    def test_current_pointer_accepts_valid_submitted_version(self):
        """Offer.current_submitted_version accepts a valid SUBMITTED version of this Offer."""
        submitted_a = OfferVersion.objects.create(
            offer=self.offer_a,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )

        self.offer_a.current_submitted_version = submitted_a
        self.offer_a.save()
        self.offer_a.refresh_from_db()
        self.assertEqual(self.offer_a.current_submitted_version_id, submitted_a.id)
