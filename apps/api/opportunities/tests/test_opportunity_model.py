from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from commodities.models import CommodityDefinition
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class OpportunityModelTests(TestCase):
    """
    Canonical domain model tests for the Opportunity aggregate.
    Validates PostgreSQL check constraints, model validation, counterparty exclusivity,
    and historical referential protection.
    """

    def setUp(self):
        self.operator_user = User.objects.create_user(
            email="operator@platform.local",
            password="testpassword123",
        )
        self.organization = Organization.objects.create(
            name="Alpha Corp",
            country="AE",
        )
        self.external_counterparty = ExternalCounterparty.objects.create(
            company_name="Gulf Trading FZE",
            contact_name="Farhad Khan",
            geography="Dubai, UAE",
        )
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_vg30",
            name_en="Bitumen VG-30",
            name_fa="قیر VG-30",
        )
        self._seq = 0

    def _create_opportunity(self, **kwargs):
        self._seq += 1
        kwargs.setdefault("identifier", f"OPP-2026-{self._seq:06d}")
        return Opportunity.objects.create(**kwargs)

    # -------------------------------------------------------------------------
    # Direction Invariants
    # -------------------------------------------------------------------------

    def test_direction_supply_accepted(self):
        """Confirm that Trade Direction 'Supply' persists cleanly."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            quantity=Decimal("1000.000"),
            unit="MT",
        )
        self.assertEqual(opp.direction, "Supply")

    def test_direction_demand_accepted(self):
        """Confirm that Trade Direction 'Demand' persists cleanly."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.DEMAND,
            external_counterparty=self.external_counterparty,
            quantity=Decimal("500.000"),
            unit="MT",
        )
        self.assertEqual(opp.direction, "Demand")

    def test_invalid_direction_rejected_in_model_validation(self):
        """Confirm that non-standard direction values are rejected by clean()."""
        opp = Opportunity(
            identifier="OPP-2026-000001",
            direction="ArbitraryDirection",
            organization=self.organization,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("direction", ctx.exception.message_dict)

    def test_invalid_direction_rejected_by_db_check_constraint(self):
        """Confirm that invalid direction values violate PostgreSQL CheckConstraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction="InvalidDir",
                        organization=self.organization,
                    )
                ])


    # -------------------------------------------------------------------------
    # Counterparty Exclusivity Invariants
    # -------------------------------------------------------------------------

    def test_internal_organization_only_persists(self):
        """Confirm Opportunity with internal Organization and null ExternalCounterparty persists."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            external_counterparty=None,
        )
        self.assertIsNotNone(opp.organization)
        self.assertIsNone(opp.external_counterparty)

    def test_external_counterparty_only_persists(self):
        """Confirm Opportunity with ExternalCounterparty and null Organization persists."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization=None,
            external_counterparty=self.external_counterparty,
        )
        self.assertIsNone(opp.organization)
        self.assertIsNotNone(opp.external_counterparty)

    def test_both_counterparties_set_rejected_in_model_validation(self):
        """Confirm setting both Organization and ExternalCounterparty raises ValidationError."""
        opp = Opportunity(
            identifier="OPP-2026-000001",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            external_counterparty=self.external_counterparty,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("counterparty", ctx.exception.message_dict)

    def test_both_counterparties_set_rejected_by_db_check_constraint(self):
        """Confirm setting both Organization and ExternalCounterparty violates PostgreSQL CheckConstraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.organization,
                        external_counterparty=self.external_counterparty,
                    )
                ])

    def test_neither_counterparty_set_rejected_in_model_validation(self):
        """Confirm setting neither Organization nor ExternalCounterparty raises ValidationError."""
        opp = Opportunity(
            identifier="OPP-2026-000001",
            direction=OpportunityDirection.DEMAND,
            organization=None,
            external_counterparty=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("counterparty", ctx.exception.message_dict)

    def test_neither_counterparty_set_rejected_by_db_check_constraint(self):
        """Confirm setting neither Organization nor ExternalCounterparty violates PostgreSQL CheckConstraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.DEMAND,
                        organization=None,
                        external_counterparty=None,
                    )
                ])


    # -------------------------------------------------------------------------
    # No Identity Side Effects
    # -------------------------------------------------------------------------

    def test_create_opportunity_with_external_counterparty_no_identity_side_effects(self):
        """
        Creating an Opportunity with an ExternalCounterparty must NOT create
        any platform User, Organization, OrganizationMembership, or OrganizationCapability.
        """
        user_count_before = User.objects.count()
        org_count_before = Organization.objects.count()
        membership_count_before = OrganizationMembership.objects.count()
        capability_count_before = OrganizationCapability.objects.count()

        self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_counterparty,
            quantity=Decimal("250.000"),
            unit="MT",
            created_by=self.operator_user,
        )

        self.assertEqual(User.objects.count(), user_count_before)
        self.assertEqual(Organization.objects.count(), org_count_before)
        self.assertEqual(OrganizationMembership.objects.count(), membership_count_before)
        self.assertEqual(OrganizationCapability.objects.count(), capability_count_before)

    # -------------------------------------------------------------------------
    # Commodity Genericity
    # -------------------------------------------------------------------------

    def test_generic_commodity_relation(self):
        """Confirm Opportunity references generic CommodityDefinition without branching."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization=self.organization,
            commodity=self.commodity,
        )
        self.assertEqual(opp.commodity.code, "bitumen_vg30")

        second_commodity = CommodityDefinition.objects.create(
            code="base_oil_sn500",
            name_en="Base Oil SN 500",
            name_fa="روغن پایه SN 500",
        )
        opp2 = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_counterparty,
            commodity=second_commodity,
        )
        self.assertEqual(opp2.commodity.code, "base_oil_sn500")

    # -------------------------------------------------------------------------
    # Structural Invariants & Constraints
    # -------------------------------------------------------------------------

    def test_quantity_positivity(self):
        """Confirm quantity must be strictly greater than 0 if provided."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            quantity=Decimal("1.500"),
        )
        self.assertEqual(opp.quantity, Decimal("1.500"))

        # Zero quantity rejected in clean()
        bad_opp = Opportunity(
            identifier="OPP-2026-000001",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            quantity=Decimal("0.000"),
        )
        with self.assertRaises(ValidationError):
            bad_opp.clean()

        # Zero quantity rejected by DB constraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.organization,
                        quantity=Decimal("0.000"),
                    )
                ])

        # Negative quantity rejected by DB constraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.organization,
                        quantity=Decimal("-10.000"),
                    )
                ])

    def test_indicative_price_non_negative(self):
        """Confirm indicative price must be non-negative if provided."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization=self.organization,
            indicative_price=Decimal("0.00"),
        )
        self.assertEqual(opp.indicative_price, Decimal("0.00"))

        # Negative price rejected in clean()
        bad_opp = Opportunity(
            identifier="OPP-2026-000001",
            direction=OpportunityDirection.DEMAND,
            organization=self.organization,
            indicative_price=Decimal("-50.00"),
        )
        with self.assertRaises(ValidationError):
            bad_opp.clean()

        # Negative price rejected by DB constraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.DEMAND,
                        organization=self.organization,
                        indicative_price=Decimal("-50.00"),
                    )
                ])

    def test_status_defaults_to_captured(self):
        """Confirm status defaults to 'Captured'."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
        )
        self.assertEqual(opp.status, OpportunityStatus.CAPTURED)

    def test_invalid_status_rejected_by_db_constraint(self):
        """Confirm invalid status violates PostgreSQL CheckConstraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.organization,
                        status="ArbitraryStatus",
                    )
                ])

    def test_delivery_window_chronological_ordering(self):
        """Confirm delivery window start cannot be after delivery window end."""
        opp = self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 15),
        )
        self.assertEqual(opp.delivery_window_start, date(2026, 10, 1))

        # Inverted window rejected in clean()
        inverted_opp = Opportunity(
            identifier="OPP-2026-000001",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            delivery_window_start=date(2026, 10, 20),
            delivery_window_end=date(2026, 10, 10),
        )
        with self.assertRaises(ValidationError) as ctx:
            inverted_opp.clean()
        self.assertIn("delivery_window_end", ctx.exception.message_dict)

        # Inverted window rejected by DB CheckConstraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier="OPP-2026-000001",
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.organization,
                        delivery_window_start=date(2026, 10, 20),
                        delivery_window_end=date(2026, 10, 10),
                    )
                ])


    # -------------------------------------------------------------------------
    # Referential Integrity & Historical Protection
    # -------------------------------------------------------------------------

    def test_destructive_delete_referenced_organization_raises_protected_error(self):
        """Deleting an Organization referenced by an Opportunity must be blocked by models.PROTECT."""
        self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
        )
        with self.assertRaises(ProtectedError):
            self.organization.delete()

    def test_destructive_delete_referenced_external_counterparty_raises_protected_error(self):
        """Deleting an ExternalCounterparty referenced by an Opportunity must be blocked by models.PROTECT."""
        self._create_opportunity(
            direction=OpportunityDirection.DEMAND,
            external_counterparty=self.external_counterparty,
        )
        with self.assertRaises(ProtectedError):
            self.external_counterparty.delete()

    def test_destructive_delete_referenced_commodity_raises_protected_error(self):
        """Deleting a CommodityDefinition referenced by an Opportunity must be blocked by models.PROTECT."""
        self._create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
            commodity=self.commodity,
        )
        with self.assertRaises(ProtectedError):
            self.commodity.delete()

    # -------------------------------------------------------------------------
    # Identifier Model Invariants
    # -------------------------------------------------------------------------

    def test_missing_identifier_rejected_by_clean(self):
        """Opportunity without identifier must fail validation in clean()."""
        opp = Opportunity(
            identifier="",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("identifier", ctx.exception.message_dict)

    def test_duplicate_identifier_rejected_by_db_unique_constraint(self):
        """Inserting two opportunities with identical identifier must raise IntegrityError."""
        self._create_opportunity(
            identifier="OPP-2026-000777",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.create(
                    identifier="OPP-2026-000777",
                    direction=OpportunityDirection.DEMAND,
                    organization=self.organization,
                )

    def test_identifier_immutable_once_created(self):
        """Modifying identifier on an existing Opportunity instance must fail clean()."""
        opp = self._create_opportunity(
            identifier="OPP-2026-000888",
            direction=OpportunityDirection.SUPPLY,
            organization=self.organization,
        )
        opp.identifier = "OPP-2026-999999"
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("identifier", ctx.exception.message_dict)
        self.assertIn("immutable", ctx.exception.message_dict["identifier"][0])
