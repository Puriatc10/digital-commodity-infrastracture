
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models

from deals.models import Deal
from deals.tests.base import BaseDealsTestCase


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
