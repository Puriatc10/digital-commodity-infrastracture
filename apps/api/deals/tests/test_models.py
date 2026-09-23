from decimal import Decimal
import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from deals.models import (
    Deal,
    DealCostSnapshot,
    DealPartySnapshot,
    DealTermsSnapshot,
    PartyRole,
    PartyType,
)
from deals.tests.base import BaseDealsTestCase
from offers.enums import CostComponentKind, LogisticsCostStatus


class DealModelTests(BaseDealsTestCase):
    """Unit tests for the Deal aggregate root model and DB constraints."""

    def test_deal_creation_minimal_success(self):
        """Minimal durable Deal aggregate can be created with valid references."""
        award, alloc = self.create_and_finalize_single_award()

        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        self.assertIsNotNone(deal.id)
        self.assertEqual(deal.award, award)
        self.assertEqual(deal.award_allocation, alloc)
        self.assertEqual(deal.rfq, self.rfq)
        self.assertEqual(deal.offer, self.supplier_offer)
        self.assertEqual(deal.offer_version, self.supplier_v1)
        self.assertEqual(deal.buyer_organization, self.buyer_org)
        self.assertEqual(deal.seller_organization, self.supplier_org)
        self.assertIsNone(deal.seller_external_counterparty)
        self.assertFalse(deal.is_external)
        self.assertEqual(deal.seller, self.supplier_org)
        self.assertEqual(deal.seller_display_name, self.supplier_org.name)

    def test_deal_cardinality_one_allocation_exactly_one_deal(self):
        """1 AwardAllocation -> exactly 1 Deal. Second Deal for same allocation fails DB constraint."""
        award, alloc = self.create_and_finalize_single_award()

        Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        # Attempting to create a second Deal for the same allocation must fail with IntegrityError
        with self.assertRaises(IntegrityError):
            Deal.objects.create(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.supplier_v1,
                buyer_organization=self.buyer_org,
                seller_organization=self.supplier_org,
                created_by=self.buyer_owner,
            )

    def test_deal_seller_xor_constraint_both_set_rejected(self):
        """Setting both seller_organization AND seller_external_counterparty violates DB check constraint."""
        award, alloc = self.create_and_finalize_single_award()

        with self.assertRaises((IntegrityError, ValidationError)):
            Deal.objects.create(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.supplier_v1,
                buyer_organization=self.buyer_org,
                seller_organization=self.supplier_org,
                seller_external_counterparty=self.ext_counterparty,
                created_by=self.buyer_owner,
            )

    def test_deal_seller_xor_constraint_neither_set_rejected(self):
        """Setting neither seller_organization NOR seller_external_counterparty violates DB check constraint."""
        award, alloc = self.create_and_finalize_single_award()

        with self.assertRaises((IntegrityError, ValidationError)):
            Deal.objects.create(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.supplier_v1,
                buyer_organization=self.buyer_org,
                seller_organization=None,
                seller_external_counterparty=None,
                created_by=self.buyer_owner,
            )

    def test_deal_external_seller_creation_success(self):
        """Deal with ExternalCounterparty seller is valid and sets is_external to True."""
        award, allocs = self.create_and_finalize_multi_award()
        ext_alloc = allocs[2]

        deal = Deal.objects.create(
            award=award,
            award_allocation=ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_organization=None,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.operator_user,
        )

        self.assertTrue(deal.is_external)
        self.assertEqual(deal.seller, self.ext_counterparty)
        self.assertEqual(deal.seller_display_name, self.ext_counterparty.company_name)

    def test_historical_safety_protected_foreign_keys(self):
        """All source entities use on_delete=PROTECT and cannot cascade-delete a Deal."""
        award, alloc = self.create_and_finalize_single_award()

        _deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        with self.assertRaises(models.ProtectedError):
            award.delete()

        with self.assertRaises(models.ProtectedError):
            alloc.delete()

        with self.assertRaises(models.ProtectedError):
            self.rfq.delete()

        with self.assertRaises(models.ProtectedError):
            self.supplier_offer.delete()

        with self.assertRaises((models.ProtectedError, ValidationError)):
            self.supplier_v1.delete()

        with self.assertRaises(models.ProtectedError):
            self.buyer_org.delete()

        with self.assertRaises(models.ProtectedError):
            self.supplier_org.delete()

        with self.assertRaises(models.ProtectedError):
            self.buyer_owner.delete()

    def test_deal_clean_graph_integrity_validation(self):
        """Model clean() rejects mismatched graph references."""
        award, alloc = self.create_and_finalize_single_award()

        # 1. Buyer organization mismatch with RFQ
        with self.assertRaises(ValidationError) as ctx:
            deal = Deal(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.supplier_v1,
                buyer_organization=self.foreign_buyer_org,  # mismatch!
                seller_organization=self.supplier_org,
                created_by=self.buyer_owner,
            )
            deal.clean()
        self.assertIn("buyer_organization", ctx.exception.message_dict)

        # 2. Offer version mismatch with Offer
        with self.assertRaises(ValidationError) as ctx:
            deal = Deal(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.broker_v1,  # mismatch!
                buyer_organization=self.buyer_org,
                seller_organization=self.supplier_org,
                created_by=self.buyer_owner,
            )
            deal.clean()
        self.assertIn("offer_version", ctx.exception.message_dict)

        # 3. Seller organization mismatch with Offer
        with self.assertRaises(ValidationError) as ctx:
            deal = Deal(
                award=award,
                award_allocation=alloc,
                rfq=self.rfq,
                offer=self.supplier_offer,
                offer_version=self.supplier_v1,
                buyer_organization=self.buyer_org,
                seller_organization=self.broker_org,  # mismatch!
                created_by=self.buyer_owner,
            )
            deal.clean()
        self.assertIn("seller_organization", ctx.exception.message_dict)

    # =========================================================================
    # DealTermsSnapshot Tests (T0902)
    # =========================================================================

    def _create_test_deal(self) -> Deal:
        award, alloc = self.create_and_finalize_single_award()
        return Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

    def test_deal_terms_snapshot_model_success(self):
        """DealTermsSnapshot created with full source commercial snapshot."""
        deal = self._create_test_deal()
        terms = DealTermsSnapshot.objects.create(
            deal=deal,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            product_cost_snapshot=Decimal("175000.00"),
            payment_terms="LC at sight",
            delivery_terms="CIF Bandar Abbas",
            incoterm="CIF",
            delivery_start=datetime.date(2026, 10, 1),
            delivery_end=datetime.date(2026, 10, 31),
            origin="Bandar Abbas",
            destination="Dubai",
            origin_area=None,
            destination_area=None,
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("15000.00"),
        )

        self.assertIsNotNone(terms.id)
        self.assertEqual(terms.deal, deal)
        self.assertEqual(deal.terms_snapshot, terms)
        self.assertEqual(terms.quantity, Decimal("500.000"))
        self.assertEqual(terms.product_cost_snapshot, Decimal("175000.00"))
        self.assertIn("DealTermsSnapshot for Deal", str(terms))

    def test_deal_terms_snapshot_quantity_positive_constraint(self):
        """DealTermsSnapshot requires quantity > 0."""
        deal = self._create_test_deal()
        with self.assertRaises((IntegrityError, ValidationError)):
            DealTermsSnapshot.objects.create(
                deal=deal,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("0.000"),  # invalid!
                quantity_unit="MT",
                unit_price=Decimal("100.00"),
                currency="USD",
                product_cost_snapshot=Decimal("100.00"),
            )

    def test_deal_terms_snapshot_unit_price_positive_constraint(self):
        """DealTermsSnapshot requires unit_price > 0."""
        deal = self._create_test_deal()
        with self.assertRaises((IntegrityError, ValidationError)):
            DealTermsSnapshot.objects.create(
                deal=deal,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("0.00"),  # invalid!
                currency="USD",
                product_cost_snapshot=Decimal("100.00"),
            )

    def test_deal_terms_snapshot_delivery_window_valid_constraint(self):
        """DealTermsSnapshot requires delivery_start <= delivery_end."""
        deal = self._create_test_deal()
        with self.assertRaises((IntegrityError, ValidationError)):
            DealTermsSnapshot.objects.create(
                deal=deal,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("100.00"),
                currency="USD",
                product_cost_snapshot=Decimal("10000.00"),
                delivery_start=datetime.date(2026, 11, 1),
                delivery_end=datetime.date(2026, 10, 1),  # earlier than start!
            )

    def test_deal_terms_snapshot_logistics_cost_consistency(self):
        """KNOWN_SEPARATE requires amount >= 0; other statuses require amount is None."""
        deal = self._create_test_deal()

        # KNOWN_SEPARATE without amount fails
        with self.assertRaises((IntegrityError, ValidationError)):
            DealTermsSnapshot.objects.create(
                deal=deal,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("100.00"),
                currency="USD",
                product_cost_snapshot=Decimal("10000.00"),
                logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
                logistics_cost_amount=None,  # missing!
            )

    def test_deal_terms_snapshot_immutability(self):
        """DealTermsSnapshot rejects updates and deletion once persisted."""
        deal = self._create_test_deal()
        terms = DealTermsSnapshot.objects.create(
            deal=deal,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            product_cost_snapshot=Decimal("175000.00"),
        )

        # Attempt to mutate terms must fail ValidationError
        terms.quantity = Decimal("600.000")
        with self.assertRaises(ValidationError):
            terms.save()

        # Attempt to delete must fail ValidationError
        with self.assertRaises(ValidationError):
            terms.delete()

    # =========================================================================
    # DealCostSnapshot Tests (T0902)
    # =========================================================================

    def test_deal_cost_snapshot_model_success_and_immutability(self):
        """DealCostSnapshot created and protected against mutation/deletion."""
        deal = self._create_test_deal()
        terms = DealTermsSnapshot.objects.create(
            deal=deal,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            product_cost_snapshot=Decimal("175000.00"),
        )

        cost = DealCostSnapshot.objects.create(
            deal_terms_snapshot=terms,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("12000.00"),
            currency="USD",
            description_snapshot="Ocean freight to destination",
        )

        self.assertIsNotNone(cost.id)
        self.assertEqual(cost.amount, Decimal("12000.00"))
        self.assertEqual(terms.cost_snapshots.count(), 1)

        # Immutability: update rejected
        cost.amount = Decimal("15000.00")
        with self.assertRaises(ValidationError):
            cost.save()

        # Immutability: delete rejected
        with self.assertRaises(ValidationError):
            cost.delete()

    def test_deal_cost_snapshot_positive_amount_and_kind_constraints(self):
        """DealCostSnapshot requires positive amount and valid kind."""
        deal = self._create_test_deal()
        terms = DealTermsSnapshot.objects.create(
            deal=deal,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            product_cost_snapshot=Decimal("175000.00"),
        )

        # Non-positive amount
        with self.assertRaises((IntegrityError, ValidationError)):
            DealCostSnapshot.objects.create(
                deal_terms_snapshot=terms,
                kind=CostComponentKind.LOGISTICS,
                amount=Decimal("0.00"),
                currency="USD",
            )

        # Invalid kind
        with self.assertRaises((IntegrityError, ValidationError)):
            DealCostSnapshot.objects.create(
                deal_terms_snapshot=terms,
                kind="INVALID_KIND",
                amount=Decimal("100.00"),
                currency="USD",
            )

    # =========================================================================
    # DealPartySnapshot Tests (T0902)
    # =========================================================================

    def test_deal_party_snapshot_uniqueness_and_immutability(self):
        """Exactly one BUYER and one SELLER per Deal; immutable once created."""
        deal = self._create_test_deal()

        buyer_party = DealPartySnapshot.objects.create(
            deal=deal,
            role=PartyRole.BUYER,
            party_type=PartyType.ORGANIZATION,
            organization=self.buyer_org,
            name_snapshot=self.buyer_org.name,
            country_snapshot="AE",
            registration_identifier_snapshot="REG-BUYER-01",
        )

        seller_party = DealPartySnapshot.objects.create(
            deal=deal,
            role=PartyRole.SELLER,
            party_type=PartyType.ORGANIZATION,
            organization=self.supplier_org,
            name_snapshot=self.supplier_org.name,
            country_snapshot="IR",
            registration_identifier_snapshot="REG-SUPP-01",
        )

        self.assertEqual(deal.party_snapshots.count(), 2)

        # Attempting to create a second BUYER fails UniqueConstraint
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DealPartySnapshot.objects.create(
                    deal=deal,
                    role=PartyRole.BUYER,
                    party_type=PartyType.ORGANIZATION,
                    organization=self.buyer_org,
                    name_snapshot="Second Buyer",
                )

        # Immutability: update rejected
        buyer_party.name_snapshot = "Mutated Name"
        with self.assertRaises(ValidationError):
            buyer_party.save()

        # Immutability: delete rejected
        with self.assertRaises(ValidationError):
            seller_party.delete()

    def test_deal_party_snapshot_backing_xor_constraints(self):
        """Backing reference XOR enforced at DB check constraint and model clean()."""
        deal = self._create_test_deal()

        # 1. ORGANIZATION party_type with organization=None fails
        with transaction.atomic():
            with self.assertRaises((IntegrityError, ValidationError)):
                DealPartySnapshot.objects.create(
                    deal=deal,
                    role=PartyRole.BUYER,
                    party_type=PartyType.ORGANIZATION,
                    organization=None,
                    name_snapshot="No Org",
                )

        # 2. ORGANIZATION party_type with both organization AND external_counterparty fails
        with transaction.atomic():
            with self.assertRaises((IntegrityError, ValidationError)):
                DealPartySnapshot.objects.create(
                    deal=deal,
                    role=PartyRole.BUYER,
                    party_type=PartyType.ORGANIZATION,
                    organization=self.buyer_org,
                    external_counterparty=self.ext_counterparty,
                    name_snapshot="Both Backings",
                )

        # 3. EXTERNAL_COUNTERPARTY party_type with external_counterparty=None fails
        with transaction.atomic():
            with self.assertRaises((IntegrityError, ValidationError)):
                DealPartySnapshot.objects.create(
                    deal=deal,
                    role=PartyRole.SELLER,
                    party_type=PartyType.EXTERNAL_COUNTERPARTY,
                    organization=None,
                    external_counterparty=None,
                    name_snapshot="No Counterparty",
                )

        # 4. EXTERNAL_COUNTERPARTY party_type with both organization AND external_counterparty fails
        with transaction.atomic():
            with self.assertRaises((IntegrityError, ValidationError)):
                DealPartySnapshot.objects.create(
                    deal=deal,
                    role=PartyRole.SELLER,
                    party_type=PartyType.EXTERNAL_COUNTERPARTY,
                    organization=self.supplier_org,
                    external_counterparty=self.ext_counterparty,
                    name_snapshot="Both Set",
                )

        # 5. Empty name_snapshot fails clean()
        with self.assertRaises(ValidationError):
            party = DealPartySnapshot(
                deal=deal,
                role=PartyRole.BUYER,
                party_type=PartyType.ORGANIZATION,
                organization=self.buyer_org,
                name_snapshot="",
            )
            party.clean()
