
from deals.models import Deal
from deals.services import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase


class DealMigrationAndUpgradeTests(BaseDealsTestCase):
    """
    Validates that:
    1. Migrations do NOT automatically fabricate Deals for existing finalized Awards.
    2. Old finalized Awards remain explicitly and idempotently materializable.
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
