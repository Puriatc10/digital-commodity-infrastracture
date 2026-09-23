from decimal import Decimal
import importlib

from django.apps import apps

from deals.models import Deal, DealPartySnapshot, DealTermsSnapshot, PartyRole
from deals.services import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase

migration_0002 = importlib.import_module(
    "deals.migrations.0002_dealtermssnapshot_dealcostsnapshot_dealpartysnapshot_and_more"
)
backfill_existing_deals = migration_0002.backfill_existing_deals


class DealMigrationAndUpgradeTests(BaseDealsTestCase):
    """
    Validates that:
    1. Migrations do NOT automatically fabricate Deals for existing finalized Awards.
    2. Old finalized Awards remain explicitly and idempotently materializable.
    3. Pre-existing T0901 Deals without snapshots are deterministically backfilled upon upgrade.
    """

    def test_preexisting_finalized_award_has_no_automatic_deal_backfill(self):
        """Finalized Awards in the database do not automatically have Deals fabricated."""
        award, alloc = self.create_and_finalize_single_award()

        # Prior to explicit materialization, zero Deals exist for this Award
        self.assertEqual(Deal.objects.filter(award=award).count(), 0)

        # The old finalized Award remains explicitly and idempotently materializable
        deals, newly_created = materialize_deals_from_award(
            award.id,
            actor=self.buyer_owner,
        )

        self.assertTrue(newly_created)
        self.assertEqual(len(deals), 1)
        self.assertEqual(Deal.objects.filter(award=award).count(), 1)
        self.assertEqual(deals[0].award_allocation, alloc)

    def test_t0901_to_t0902_upgrade_deterministic_backfill(self):
        """Simulate a T0901 Deal without snapshots; verify migration backfills exact source data."""
        award, alloc = self.create_and_finalize_single_award()

        # Create raw Deal without snapshots (simulating T0901 state)
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

        # Assert no snapshots exist yet
        self.assertFalse(DealTermsSnapshot.objects.filter(deal=deal).exists())
        self.assertFalse(DealPartySnapshot.objects.filter(deal=deal).exists())

        # Run migration backfill
        backfill_existing_deals(apps, None)

        # Assert snapshots were created deterministically
        self.assertTrue(DealTermsSnapshot.objects.filter(deal=deal).exists())
        terms = DealTermsSnapshot.objects.get(deal=deal)
        self.assertEqual(terms.quantity, alloc.awarded_quantity)
        self.assertEqual(terms.unit_price, self.supplier_v1.unit_price)
        self.assertEqual(terms.product_cost_snapshot, (alloc.awarded_quantity * self.supplier_v1.unit_price).quantize(Decimal("0.01")))

        self.assertEqual(DealPartySnapshot.objects.filter(deal=deal).count(), 2)
        buyer_party = DealPartySnapshot.objects.get(deal=deal, role=PartyRole.BUYER)
        self.assertEqual(buyer_party.name_snapshot, self.buyer_org.name)
        seller_party = DealPartySnapshot.objects.get(deal=deal, role=PartyRole.SELLER)
        self.assertEqual(seller_party.name_snapshot, self.supplier_org.name)
