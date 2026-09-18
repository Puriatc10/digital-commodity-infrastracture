from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from offers.enums import OfferorRole
from offers.models import Offer
from offers.tests.base import BaseOffersTestCase
from trade_hub.models import RFQ, RFQStatus, RFQVisibility


class OfferModelDatabaseConstraintTests(BaseOffersTestCase):
    """
    Direct PostgreSQL database constraint attack tests for Offer model (T0801).
    Validates XOR economic party exclusivity, offeror role constraints, conditional
    uniqueness, and referential historical protection against deletions.
    """

    def test_economic_party_organization_only_succeeds(self):
        """Offer with offering_organization and no external_counterparty succeeds."""
        offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            external_counterparty=None,
            created_by=self.supplier_user,
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.offering_organization, self.supplier_org)
        self.assertIsNone(offer.external_counterparty)
        self.assertFalse(offer.is_external)
        self.assertEqual(offer.economic_party, self.supplier_org)
        self.assertEqual(offer.aggregate_version, 1)
        self.assertEqual(offer.version, 1)

    def test_economic_party_external_only_succeeds(self):
        """Offer with external_counterparty and no offering_organization succeeds."""
        offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=None,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.external_counterparty, self.external_cp)
        self.assertIsNone(offer.offering_organization)
        self.assertTrue(offer.is_external)
        self.assertEqual(offer.economic_party, self.external_cp)
        self.assertEqual(offer.aggregate_version, 1)

    def test_economic_party_both_fails_check_constraint(self):
        """Offer with BOTH organization and external_counterparty fails PostgreSQL check constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=self.supplier_org,
                    external_counterparty=self.external_cp,
                    created_by=self.supplier_user,
                )

    def test_economic_party_neither_fails_check_constraint(self):
        """Offer with NEITHER organization nor external_counterparty fails PostgreSQL check constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=None,
                    external_counterparty=None,
                    created_by=self.supplier_user,
                )

    def test_offeror_role_supplier_and_broker_succeed(self):
        """Valid roles SUPPLIER and BROKER both persist successfully."""
        offer_sup = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        self.assertEqual(offer_sup.offeror_role, OfferorRole.SUPPLIER)

        offer_brk = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
            created_by=self.broker_user,
        )
        self.assertEqual(offer_brk.offeror_role, OfferorRole.BROKER)

    def test_offeror_role_trader_forbidden_fails_check_constraint(self):
        """Forbidden role TRADER fails PostgreSQL check constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role="TRADER",
                    offering_organization=self.supplier_org,
                    created_by=self.supplier_user,
                )

    def test_offeror_role_arbitrary_fails_check_constraint(self):
        """Arbitrary string role fails PostgreSQL check constraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role="BUYER",
                    offering_organization=self.supplier_org,
                    created_by=self.supplier_user,
                )

    def test_internal_duplicate_thread_fails_unique_constraint(self):
        """Duplicate (rfq, offering_organization, offeror_role) fails DB conditional uniqueness."""
        Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=self.supplier_org,
                    created_by=self.supplier_user,
                )

    def test_external_duplicate_thread_fails_unique_constraint(self):
        """Duplicate (rfq, external_counterparty, offeror_role) fails DB conditional uniqueness."""
        Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Offer.objects.create(
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    external_counterparty=self.external_cp,
                    source_opportunity=self.opp_external_qualified,
                    created_by=self.operator_user,
                )

    def test_same_organization_different_roles_allowed(self):
        """Same organization with both roles (SUPPLIER and BROKER) creates distinct valid Offer parents."""
        offer1 = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.multi_org,
            created_by=self.multi_user,
        )
        offer2 = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.multi_org,
            created_by=self.multi_user,
        )
        self.assertNotEqual(offer1.id, offer2.id)
        self.assertEqual(Offer.objects.filter(rfq=self.published_rfq, offering_organization=self.multi_org).count(), 2)

    def test_same_external_counterparty_different_roles_allowed(self):
        """Same external counterparty with both roles creates distinct valid Offer parents."""
        offer1 = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )
        offer2 = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )
        self.assertNotEqual(offer1.id, offer2.id)
        self.assertEqual(Offer.objects.filter(rfq=self.published_rfq, external_counterparty=self.external_cp).count(), 2)

    def test_different_rfqs_same_organization_and_role_allowed(self):
        """Same organization and role can create distinct Offer parents against different RFQs."""
        rfq2 = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("200.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        offer1 = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        offer2 = Offer.objects.create(
            rfq=rfq2,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        self.assertNotEqual(offer1.id, offer2.id)

    def test_deletion_historical_protection(self):
        """Historical entities cannot be CASCADE-deleted if referenced by an Offer (ProtectedError)."""
        Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )

        # 1. RFQ cannot be deleted
        with self.assertRaises(ProtectedError):
            self.published_rfq.delete()

        # 2. Offering Organization cannot be deleted
        with self.assertRaises(ProtectedError):
            self.supplier_org.delete()

        # 3. Creator User cannot be deleted
        with self.assertRaises(ProtectedError):
            self.supplier_user.delete()

        # 4. External Counterparty cannot be deleted
        Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )
        with self.assertRaises(ProtectedError):
            self.external_cp.delete()

        # 5. Source Opportunity cannot be deleted
        with self.assertRaises(ProtectedError):
            self.opp_external_qualified.delete()

    def test_model_clean_validation(self):
        """clean() enforces business rules at Django form/model layer."""
        # Both parties provided
        bad_both = Offer(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            external_counterparty=self.external_cp,
            created_by=self.supplier_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_both.clean()
        self.assertIn("exactly one economic party", str(ctx.exception))

        # Neither party provided
        bad_neither = Offer(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=None,
            external_counterparty=None,
            created_by=self.supplier_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_neither.clean()
        self.assertIn("exactly one economic party", str(ctx.exception))

        # Invalid role
        bad_role = Offer(
            rfq=self.published_rfq,
            offeror_role="TRADER",
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_role.clean()
        self.assertIn("Invalid offeror role", str(ctx.exception))
