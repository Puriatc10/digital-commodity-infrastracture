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

    def test_t0903_to_t0904_upgrade_deterministic_provenance_backfill(self):
        """Simulate T0903 Deals and verify migration 0004 backfills only explicit provenance."""
        import uuid
        from opportunities.models import (
            Opportunity,
            OpportunityDirection,
            OpportunitySource,
            OpportunityStatus,
        )
        from deals.models import (
            DealBrokerAttribution,
            DealBrokerRole,
            DealOpportunityAttribution,
            DealOpportunityRole,
        )
        migration_0004 = importlib.import_module(
            "deals.migrations.0004_dealbrokerattribution_dealopportunityattribution"
        )
        backfill_existing_deals_provenance = migration_0004.backfill_existing_deals_provenance

        # Setup supply opp with broker referral
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-MIG-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.ext_counterparty,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.ext_offer.source_opportunity = supply_opp
        self.ext_offer.save(update_fields=["source_opportunity"])

        award, allocs = self.create_and_finalize_multi_award()
        supplier_alloc, broker_alloc, ext_alloc = allocs

        # Create raw Deal from ext_alloc (has broker referral via supply_opp)
        deal_with_provenance = Deal.objects.create(
            award=award,
            award_allocation=ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        # Create raw Deal from supplier_alloc (direct supplier, NO broker referral, NO opp)
        deal_without_provenance = Deal.objects.create(
            award=award,
            award_allocation=supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        # Ensure no provenance rows yet
        DealBrokerAttribution.objects.filter(deal__in=[deal_with_provenance, deal_without_provenance]).delete()
        DealOpportunityAttribution.objects.filter(deal__in=[deal_with_provenance, deal_without_provenance]).delete()

        # Run migration 0004 backfill
        backfill_existing_deals_provenance(apps, None)

        # Deal with provenance has exact rows
        self.assertEqual(deal_with_provenance.broker_attributions.count(), 1)
        b_row = deal_with_provenance.broker_attributions.first()
        self.assertEqual(b_row.broker_organization, self.broker_org)
        self.assertEqual(b_row.role, DealBrokerRole.SUPPLY_ORIGINATOR)
        self.assertEqual(b_row.related_opportunity, supply_opp)

        self.assertEqual(deal_with_provenance.opportunity_attributions.count(), 1)
        o_row = deal_with_provenance.opportunity_attributions.first()
        self.assertEqual(o_row.opportunity, supply_opp)
        self.assertEqual(o_row.role, DealOpportunityRole.SUPPLY_ORIGIN)

        # Deal without provenance has ZERO rows (no guessing, no fabrication)
        self.assertEqual(deal_without_provenance.broker_attributions.count(), 0)
        self.assertEqual(deal_without_provenance.opportunity_attributions.count(), 0)
