from decimal import Decimal
import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import models
from django.test import TestCase, override_settings

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealBrokerAttribution,
    DealOpportunityAttribution,
    DealPartySnapshot,
    DealTermsSnapshot,
    PartyRole,
)
from execution.enums import ExecutionStatus, MilestoneStatus
from execution.models.execution import Execution
from execution.models.milestone import ExecutionMilestone
from identity.seed_dataset import DEMO_SEED_VERSION, seed_demo_dataset
from offers.enums import OfferVersionStatus
from offers.models import Offer, OfferVersion
from opportunities.models import (
    Opportunity,
    OpportunityStatus,
)
from organizations.models import Organization, OrganizationCapability
from organizations.verification.models import VerificationStatus
from trade_hub.models import RFQ, RFQStatus


@override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
class RealisticSeedDatasetTests(TestCase):
    """Integration test suite for T1301 Realistic Seed Dataset."""

    def setUp(self):
        super().setUp()
        self.out = io.StringIO()
        self.summary = seed_demo_dataset(stdout=self.out)

    def test_minimum_counts(self):
        """Verify the seeded dataset satisfies all roadmap minimum quantity gates."""
        buyers_count = OrganizationCapability.objects.filter(capability="buyer").count()
        suppliers_count = OrganizationCapability.objects.filter(capability="supplier").count()
        brokers_count = OrganizationCapability.objects.filter(capability="broker").count()
        rfqs_count = RFQ.objects.count()
        offers_count = Offer.objects.count()
        deals_count = Deal.objects.count()
        opps_count = Opportunity.objects.count()
        executions_count = Execution.objects.count()

        self.assertGreaterEqual(buyers_count, 4, "Must contain at least 4 Buyers")
        self.assertGreaterEqual(suppliers_count, 8, "Must contain at least 8 Suppliers")
        self.assertGreaterEqual(brokers_count, 5, "Must contain at least 5 Brokers")
        self.assertGreaterEqual(rfqs_count, 20, "Must contain at least 20 RFQs")
        self.assertGreaterEqual(offers_count, 40, "Must contain at least 40 Offers")
        self.assertGreaterEqual(deals_count, 10, "Must contain at least 10 Deals")
        self.assertGreater(opps_count, 0, "Must contain Opportunities")
        self.assertGreater(executions_count, 0, "Must contain Execution histories")

        self.assertEqual(self.summary["version"], DEMO_SEED_VERSION)
        self.assertEqual(self.summary["deals_count"], 10)

    def test_procurement_relationships(self):
        """Verify coherent procurement lifecycle relationships across seeded entities."""
        deals = Deal.objects.all().select_related(
            "rfq", "offer", "offer_version", "buyer_organization", "seller_organization", "seller_external_counterparty"
        )
        self.assertEqual(deals.count(), 10)

        for deal in deals:
            # 1. RFQ link
            self.assertIsNotNone(deal.rfq)
            self.assertEqual(deal.rfq.status, RFQStatus.AWARDED)
            self.assertEqual(deal.rfq.organization, deal.buyer_organization)

            # 2. Offer link
            self.assertIsNotNone(deal.offer)
            self.assertEqual(deal.offer.rfq, deal.rfq)
            self.assertIsNotNone(deal.offer_version)
            self.assertEqual(deal.offer_version.status, OfferVersionStatus.SUBMITTED)

            # 3. Deal terms snapshot
            terms = DealTermsSnapshot.objects.filter(deal=deal).first()
            self.assertIsNotNone(terms, f"Deal {deal.id} must have an immutable DealTermsSnapshot")
            self.assertGreater(terms.quantity, Decimal("0"))
            self.assertGreater(terms.unit_price, Decimal("0"))
            self.assertEqual(terms.product_cost_snapshot, terms.quantity * terms.unit_price)

            # 4. Deal party snapshots
            buyer_snapshot = DealPartySnapshot.objects.filter(deal=deal, role=PartyRole.BUYER).first()
            self.assertIsNotNone(buyer_snapshot)
            self.assertEqual(buyer_snapshot.organization, deal.buyer_organization)

            seller_snapshot = DealPartySnapshot.objects.filter(deal=deal, role=PartyRole.SELLER).first()
            self.assertIsNotNone(seller_snapshot)
            if deal.seller_organization:
                self.assertEqual(seller_snapshot.organization, deal.seller_organization)
            else:
                self.assertEqual(seller_snapshot.external_counterparty, deal.seller_external_counterparty)

            # 5. Deal Attribution
            attribution = DealAttribution.objects.filter(deal=deal).first()
            self.assertIsNotNone(attribution, f"Deal {deal.id} must have a DealAttribution record")
            self.assertIsNotNone(attribution.primary_channel)

            # 6. Execution link
            execution = Execution.objects.filter(deal=deal).first()
            self.assertIsNotNone(execution, f"Deal {deal.id} must have an Execution instance")
            self.assertEqual(execution.milestones.count(), 10)

        # Verify Brokered Deal Attribution (Deal 8)
        brokered_deal = deals.filter(seller_organization__capabilities__capability="broker").first()
        self.assertIsNotNone(brokered_deal, "Must have at least one Deal with Broker as seller")
        broker_attr = DealBrokerAttribution.objects.filter(deal=brokered_deal).first()
        self.assertIsNotNone(broker_attr, "Brokered deal must have DealBrokerAttribution")
        self.assertEqual(brokered_deal.attribution.primary_channel, DealAttributionChannel.BROKER)

        # Verify External Counterparty Deal (Deal 10)
        ext_deal = deals.filter(seller_external_counterparty__isnull=False).first()
        self.assertIsNotNone(ext_deal, "Must have at least one Deal with External Counterparty seller")
        self.assertIsNone(ext_deal.seller_organization)
        self.assertEqual(ext_deal.seller_external_counterparty.company_name, "Oman Bitumen Terminals LLC")
        opp_attr = DealOpportunityAttribution.objects.filter(deal=ext_deal).first()
        self.assertIsNotNone(opp_attr, "External counterparty deal must have DealOpportunityAttribution")
        self.assertEqual(ext_deal.attribution.primary_channel, DealAttributionChannel.OPPORTUNITY_DESK)

    def test_lifecycle_diversity(self):
        """Verify the seeded dataset contains multiple valid lifecycle states."""
        # 1. RFQ statuses
        rfq_statuses = set(RFQ.objects.values_list("status", flat=True))
        expected_rfq_statuses = {
            RFQStatus.DRAFT,
            RFQStatus.PUBLISHED,
            RFQStatus.COLLECTING_OFFERS,
            RFQStatus.NEGOTIATING,
            RFQStatus.AWARDED,
            RFQStatus.CLOSED,
            RFQStatus.CANCELLED,
        }
        self.assertTrue(
            expected_rfq_statuses.issubset(rfq_statuses),
            f"Missing RFQ statuses: {expected_rfq_statuses - rfq_statuses}",
        )

        # 2. OfferVersion statuses (Only DRAFT and SUBMITTED exist; SUPERSEDED is derived)
        version_statuses = set(OfferVersion.objects.values_list("status", flat=True))
        expected_version_statuses = {
            OfferVersionStatus.DRAFT,
            OfferVersionStatus.SUBMITTED,
        }
        self.assertTrue(
            expected_version_statuses.issubset(version_statuses),
            f"Missing OfferVersion statuses: {expected_version_statuses - version_statuses}",
        )
        self.assertTrue(
            OfferVersion.objects.filter(version_number__gt=1).exists(),
            "Expected at least one multi-version (revised) offer version.",
        )

        # 3. Opportunity statuses
        opp_statuses = set(Opportunity.objects.values_list("status", flat=True))
        expected_opp_statuses = {
            OpportunityStatus.CAPTURED,
            OpportunityStatus.CONTACTED,
            OpportunityStatus.QUALIFIED,
            OpportunityStatus.MATCHING,
            OpportunityStatus.CONVERTED,
            OpportunityStatus.ON_HOLD,
            OpportunityStatus.LOST,
        }
        self.assertTrue(
            expected_opp_statuses.issubset(opp_statuses),
            f"Missing Opportunity statuses: {expected_opp_statuses - opp_statuses}",
        )

        # 4. Verification statuses (all 6 statuses)
        verif_statuses = set(Organization.objects.values_list("verification__status", flat=True))
        expected_verif_statuses = {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.DOCUMENTS_SUBMITTED,
            VerificationStatus.UNDER_REVIEW,
            VerificationStatus.BASIC_VERIFIED,
            VerificationStatus.VERIFIED,
            VerificationStatus.SUSPENDED,
        }
        self.assertTrue(
            expected_verif_statuses.issubset(verif_statuses),
            f"Missing Verification statuses: {expected_verif_statuses - verif_statuses}",
        )

        # 5. Execution statuses & milestone histories
        exec_statuses = set(Execution.objects.values_list("status", flat=True))
        self.assertIn(ExecutionStatus.OPEN, exec_statuses)
        self.assertIn(ExecutionStatus.CLOSED, exec_statuses)

        # Diverse milestone progress
        completed_milestone_codes = set(
            ExecutionMilestone.objects.filter(status=MilestoneStatus.COMPLETED).values_list(
                "definition__code", flat=True
            )
        )
        expected_milestone_codes = {
            "AWARDED",
            "CONTRACT_SIGNED",
            "PAYMENT_REPORTED",
            "LOADING_SCHEDULED",
            "LOADED",
            "INSPECTION_COMPLETED",
            "IN_TRANSIT",
            "DELIVERED",
            "ACCEPTED",
            "CLOSED",
        }
        self.assertTrue(
            expected_milestone_codes.issubset(completed_milestone_codes),
            f"Missing completed milestone codes: {expected_milestone_codes - completed_milestone_codes}",
        )

    def test_determinism_and_idempotency(self):
        """Verify that running the seed multiple times produces identical output without duplicating rows."""
        # Capture baseline counts
        counts_run_1 = {
            "orgs": Organization.objects.count(),
            "capabilities": OrganizationCapability.objects.count(),
            "memberships": Organization.objects.filter(memberships__isnull=False).count(),
            "rfqs": RFQ.objects.count(),
            "offers": Offer.objects.count(),
            "offer_versions": OfferVersion.objects.count(),
            "deals": Deal.objects.count(),
            "opps": Opportunity.objects.count(),
            "executions": Execution.objects.count(),
            "milestones": ExecutionMilestone.objects.count(),
        }

        # Run seed second time
        out_2 = io.StringIO()
        summary_2 = seed_demo_dataset(stdout=out_2)

        counts_run_2 = {
            "orgs": Organization.objects.count(),
            "capabilities": OrganizationCapability.objects.count(),
            "memberships": Organization.objects.filter(memberships__isnull=False).count(),
            "rfqs": RFQ.objects.count(),
            "offers": Offer.objects.count(),
            "offer_versions": OfferVersion.objects.count(),
            "deals": Deal.objects.count(),
            "opps": Opportunity.objects.count(),
            "executions": Execution.objects.count(),
            "milestones": ExecutionMilestone.objects.count(),
        }

        self.assertEqual(counts_run_1, counts_run_2, "Idempotency violation: count changed on second seed run")
        self.assertEqual(self.summary["deals_count"], summary_2["deals_count"])
        self.assertEqual(self.summary["rfqs_count"], summary_2["rfqs_count"])
        self.assertEqual(self.summary["offers_count"], summary_2["offers_count"])

    def test_analytics_compatibility(self):
        """Verify seeded data supports Epic 12 analytics queries without hardcoding."""
        # 1. Procurement Metrics (T1201)
        total_rfqs = RFQ.objects.count()
        total_offers = Offer.objects.count()
        awarded_rfqs = RFQ.objects.filter(status=RFQStatus.AWARDED).count()
        award_rate = awarded_rfqs / total_rfqs if total_rfqs else 0
        self.assertGreater(award_rate, 0.3)

        # Average offers per RFQ for RFQs that received offers
        rfqs_with_offers = RFQ.objects.filter(offers__isnull=False).distinct().count()
        avg_offers = total_offers / rfqs_with_offers
        self.assertGreaterEqual(avg_offers, 2.0)

        # Quote spread for Bitumen 60/70 RFQ 1
        rfq_1_offers = OfferVersion.objects.filter(
            offer__rfq__notes__contains="[DEMO-RFQ-01]", status=OfferVersionStatus.SUBMITTED
        )
        min_price = rfq_1_offers.aggregate(min_p=models.Min("unit_price"))["min_p"]
        max_price = rfq_1_offers.aggregate(max_p=models.Max("unit_price"))["max_p"]
        self.assertIsNotNone(min_price)
        self.assertIsNotNone(max_price)
        self.assertGreater(max_price, min_price, "Competitive RFQ must have non-zero quote spread")

        # 2. Deal Metrics (T1202)
        total_deals = Deal.objects.count()
        total_awarded_volume = DealTermsSnapshot.objects.aggregate(total_vol=models.Sum("quantity"))["total_vol"]
        total_completed_value = DealTermsSnapshot.objects.filter(
            deal__execution__status=ExecutionStatus.CLOSED
        ).aggregate(total_val=models.Sum("product_cost_snapshot"))["total_val"]

        self.assertEqual(total_deals, 10)
        self.assertGreater(total_awarded_volume, Decimal("5000.000"))
        self.assertGreater(total_completed_value, Decimal("0.00"))

        # 3. Supplier Performance (T1203)
        supplier_offers = Offer.objects.filter(offering_organization__capabilities__capability="supplier").count()
        self.assertGreater(supplier_offers, 20)
        won_deals = Deal.objects.filter(seller_organization__capabilities__capability="supplier").count()
        self.assertGreater(won_deals, 5)

        # 4. Broker Performance (T1204)
        brokered_opps = Opportunity.objects.filter(broker__isnull=False).count()
        self.assertGreaterEqual(brokered_opps, 3)
        brokered_deals = Deal.objects.filter(attribution__primary_channel=DealAttributionChannel.BROKER).count()
        self.assertGreaterEqual(brokered_deals, 1)

        # 5. Opportunity Metrics (T1205)
        converted_opps = Opportunity.objects.filter(status=OpportunityStatus.CONVERTED).count()
        self.assertGreaterEqual(converted_opps, 1)
        qualified_opps = Opportunity.objects.filter(status=OpportunityStatus.QUALIFIED).count()
        self.assertGreaterEqual(qualified_opps, 2)

        # 6. Market Activity & Insufficient Data Guard (T1206, T1207)
        # Bitumen has active quotes
        bitumen_quotes = OfferVersion.objects.filter(
            offer__rfq__commodity__code="bitumen", status=OfferVersionStatus.SUBMITTED
        )
        self.assertGreaterEqual(bitumen_quotes.count(), 30)

        # Base Oil has zero quotes (insufficient data guard must hold)
        base_oil_quotes = OfferVersion.objects.filter(
            offer__rfq__commodity__code="base_oil", status=OfferVersionStatus.SUBMITTED
        )
        self.assertEqual(
            base_oil_quotes.count(),
            0,
            "Base Oil must have zero quotes to verify insufficient-data benchmark guard.",
        )

    def test_management_command(self):
        """Verify the seed_demo_dataset management command executes cleanly."""
        out = io.StringIO()
        call_command("seed_demo_dataset", stdout=out)
        output = out.getvalue()
        self.assertIn("Starting realistic demo dataset seed (T1301)...", output)
        self.assertIn("Successfully completed realistic demo dataset seed.", output)


class RealisticSeedDatasetDisabledGuardTests(TestCase):
    """Verify that seed_demo_dataset rejects disabled environments."""

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=False)
    def test_command_requires_demo_flag(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_demo_dataset", stdout=io.StringIO())
        self.assertIn("DEMO_PERSONA_SWITCHER_ENABLED must be enabled", str(ctx.exception))
