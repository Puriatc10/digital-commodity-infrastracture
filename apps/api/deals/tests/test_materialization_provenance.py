from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model

from deals.models import (
    Deal,
    DealAttribution,
    DealBrokerAttribution,
    DealOpportunityAttribution,
    DealPartySnapshot,
    DealTermsSnapshot,
)
from deals.services.materialization import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)

User = get_user_model()


class DealMaterializationProvenanceTests(BaseDealsTestCase):
    """
    Integration and atomicity tests for Deal provenance materialization (T0904).
    """

    def setUp(self):
        super().setUp()
        award, allocs = self.create_and_finalize_multi_award()
        self.award = award
        self.allocs = allocs

    def test_materialization_atomicity_failure_in_provenance_rolls_back_entire_deal(self):
        """
        Atomic failure injection:
        If provenance creation fails, the atomic transaction must rollback the entire
        new Deal graph (Deal, Terms, Parties, Attribution, Broker/Opportunity rows).
        No partial Deal records are persisted.
        """
        # Inject simulated failure during persist_deal_provenance
        with patch(
            "deals.services.materialization.persist_deal_provenance",
            side_effect=RuntimeError("Simulated provenance failure!"),
        ):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(self.award.id, actor=self.buyer_owner)

        # Assert database is completely clean of any Deal or child records
        self.assertEqual(Deal.objects.filter(award=self.award).count(), 0)
        self.assertEqual(DealTermsSnapshot.objects.count(), 0)
        self.assertEqual(DealPartySnapshot.objects.count(), 0)
        self.assertEqual(DealAttribution.objects.count(), 0)
        self.assertEqual(DealBrokerAttribution.objects.count(), 0)
        self.assertEqual(DealOpportunityAttribution.objects.count(), 0)

    def test_materialization_idempotency_preserves_broker_and_opportunity_rows(self):
        """
        Idempotent repeat:
        Calling materialize_deals_from_award a second time returns existing Deals
        without creating duplicate DealBrokerAttribution or DealOpportunityAttribution rows.
        """
        # Set up a supply opportunity on external offer
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.ext_counterparty,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.ext_offer.source_opportunity = supply_opp
        self.ext_offer.save(update_fields=["source_opportunity"])

        # First materialization
        deals_1, created_1 = materialize_deals_from_award(self.award.id, actor=self.buyer_owner)
        self.assertTrue(created_1)
        self.assertEqual(len(deals_1), 3)

        initial_broker_count = DealBrokerAttribution.objects.count()
        initial_opp_count = DealOpportunityAttribution.objects.count()

        # Must have created broker attribution for broker offer and supply opp referral
        self.assertGreater(initial_broker_count, 0)
        self.assertGreater(initial_opp_count, 0)

        # Second materialization (idempotent)
        deals_2, created_2 = materialize_deals_from_award(self.award.id, actor=self.buyer_owner)
        self.assertFalse(created_2)
        self.assertEqual(len(deals_2), 3)

        # Counts must remain strictly identical (zero duplicate rows)
        self.assertEqual(DealBrokerAttribution.objects.count(), initial_broker_count)
        self.assertEqual(DealOpportunityAttribution.objects.count(), initial_opp_count)
