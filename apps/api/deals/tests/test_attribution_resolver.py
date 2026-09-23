from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealAttributionStatus,
)
from deals.services.attribution_resolver import (
    collect_deal_attribution_evidence,
    resolve_deal_attribution,
)
from deals.tests.base import BaseDealsTestCase
from matching.constants import DEFAULT_ENGINE_VERSION
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
)
from matching.models import (
    MatchingCandidate,
    MatchingPolicy,
    MatchingPolicyVersion,
    MatchingRun,
)
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import OrganizationCapability

User = get_user_model()


class DealAttributionResolverTests(BaseDealsTestCase):
    """
    Unit and domain tests for the central deterministic Deal attribution resolver (T0903).
    """

    def setUp(self):
        super().setUp()
        award, allocs = self.create_and_finalize_multi_award()
        self.award = award
        self.supplier_alloc, self.broker_alloc, self.ext_alloc = allocs

    def test_direct_supplier_resolved(self):
        """Internal Supplier directly participating in RFQ resolves to DIRECT_SUPPLIER."""
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertTrue(evidence["is_direct_participation"])

    def test_broker_offeror_role_resolved(self):
        """Offer submitted by Broker organization in BROKER role resolves to BROKER."""
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.broker_alloc,
            rfq=self.rfq,
            offer=self.broker_offer,
            offer_version=self.broker_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.broker_org,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.BROKER)
        self.assertIn(DealAttributionChannel.BROKER, evidence["detected_channels"])

    def test_broker_referral_opportunity_resolved(self):
        """Deal originating from a Broker Referral Supply Opportunity resolves to BROKER."""
        broker_supply_opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("200.000"),
            unit="MT",
            external_counterparty=self.ext_counterparty,
            created_by=self.operator_user,
        )
        self.ext_offer.source_opportunity = broker_supply_opp
        self.ext_offer.save(update_fields=["source_opportunity"])

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.BROKER)
        self.assertEqual(evidence["source_supply_opportunity_broker_id"], str(self.broker_org.id))

    def test_opportunity_desk_operator_sourcing_resolved(self):
        """Deal originating from Operator Sourcing Opportunity resolves to OPPORTUNITY_DESK."""
        # self.supply_opp in BaseDealsTestCase has source=OPERATOR_SOURCING
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.OPPORTUNITY_DESK)
        self.assertEqual(evidence["source_supply_opportunity_source"], OpportunitySource.OPERATOR_SOURCING)

    def test_buyer_existing_supplier_resolved(self):
        """Deal with explicit EXISTING_RELATIONSHIP provenance resolves to BUYER_EXISTING_SUPPLIER."""
        existing_rel_opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            source=OpportunitySource.EXISTING_RELATIONSHIP,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("200.000"),
            unit="MT",
            external_counterparty=self.ext_counterparty,
            created_by=self.operator_user,
        )
        self.ext_offer.source_opportunity = existing_rel_opp
        self.ext_offer.save(update_fields=["source_opportunity"])

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.BUYER_EXISTING_SUPPLIER)

    def test_exact_precedence_existing_supplier_beats_broker(self):
        """Priority 1 (BUYER_EXISTING_SUPPLIER) takes precedence over Priority 2 (BROKER)."""
        existing_opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            source=OpportunitySource.EXISTING_RELATIONSHIP,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("300.000"),
            unit="MT",
            organization=self.broker_org,
            created_by=self.operator_user,
        )
        # Offer has role BROKER, but source opportunity states EXISTING_RELATIONSHIP
        self.broker_offer.source_opportunity = existing_opp
        self.broker_offer.save(update_fields=["source_opportunity"])

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.broker_alloc,
            rfq=self.rfq,
            offer=self.broker_offer,
            offer_version=self.broker_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.broker_org,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.BUYER_EXISTING_SUPPLIER)
        # Both channels were detected in evidence
        self.assertIn(DealAttributionChannel.BUYER_EXISTING_SUPPLIER, evidence["detected_channels"])
        self.assertIn(DealAttributionChannel.BROKER, evidence["detected_channels"])

    def test_exact_precedence_broker_beats_opportunity_desk(self):
        """Priority 2 (BROKER) takes precedence over Priority 3 (OPPORTUNITY_DESK)."""
        broker_opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("200.000"),
            unit="MT",
            external_counterparty=self.ext_counterparty,
            created_by=self.operator_user,
        )
        self.ext_offer.source_opportunity = broker_opp
        self.ext_offer.save(update_fields=["source_opportunity"])

        # Also demand opportunity has operator sourcing
        Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            status=OpportunityStatus.CONVERTED,
            source=OpportunitySource.OPERATOR_SOURCING,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            organization=self.buyer_org,
            converted_rfq=self.rfq,
            created_by=self.operator_user,
        )

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.BROKER)
        self.assertIn(DealAttributionChannel.BROKER, evidence["detected_channels"])
        self.assertIn(DealAttributionChannel.OPPORTUNITY_DESK, evidence["detected_channels"])

    def test_exact_precedence_opportunity_desk_beats_direct_supplier(self):
        """Priority 3 (OPPORTUNITY_DESK) takes precedence over Priority 5 (DIRECT_SUPPLIER)."""
        # Internal supplier participating, but RFQ originated from Demand Opportunity
        Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            status=OpportunityStatus.CONVERTED,
            source=OpportunitySource.INBOUND_LEAD,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            organization=self.buyer_org,
            converted_rfq=self.rfq,
            created_by=self.operator_user,
        )

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        status, channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.RESOLVED)
        self.assertEqual(channel, DealAttributionChannel.OPPORTUNITY_DESK)

    def test_weak_evidence_previous_deal_does_not_imply_existing_supplier(self):
        """Previous deal history between buyer and supplier must NOT imply BUYER_EXISTING_SUPPLIER."""
        # Create an earlier historical deal between same buyer and supplier
        Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        # Prove previous deal exists between buyer and supplier
        self.assertEqual(
            Deal.objects.filter(buyer_organization=self.buyer_org, seller_organization=self.supplier_org).count(),
            1,
        )

        # New deal without source_opportunity with EXISTING_RELATIONSHIP
        deal2 = Deal(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        status, channel, _ = resolve_deal_attribution(deal2)
        # Should resolve to DIRECT_SUPPLIER, NOT BUYER_EXISTING_SUPPLIER
        self.assertEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertNotEqual(channel, DealAttributionChannel.BUYER_EXISTING_SUPPLIER)

    def test_weak_evidence_broker_capability_alone_does_not_imply_broker(self):
        """Organization having Broker capability alone does NOT imply BROKER attribution."""
        # Supplier organization additionally registers Broker capability
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        # But offer was submitted as SUPPLIER
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        status, channel, _ = resolve_deal_attribution(deal)
        self.assertEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertNotEqual(channel, DealAttributionChannel.BROKER)

    def test_weak_evidence_operator_touch_does_not_imply_opportunity_desk(self):
        """Deal or RFQ created/managed by an Operator does NOT imply OPPORTUNITY_DESK."""
        # Operator touches the RFQ and materializes the Deal, but no Opportunity Desk opportunity exists
        from trade_hub.models import RFQ
        RFQ.objects.filter(pk=self.rfq.pk).update(created_by_operator=True)
        self.rfq.refresh_from_db()

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.operator_user,  # Materialized by Operator
        )

        status, channel, _ = resolve_deal_attribution(deal)
        self.assertEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertNotEqual(channel, DealAttributionChannel.OPPORTUNITY_DESK)

    def test_weak_evidence_matching_candidate_alone_does_not_imply_platform_network(self):
        """Presence of a MatchingRun or candidate on RFQ does NOT imply PLATFORM_NETWORK."""
        policy = MatchingPolicy.objects.create(
            code=f"test_policy_{uuid.uuid4().hex[:6]}",
            name="Test Policy",
        )
        policy_ver = MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.PUBLISHED,
            configuration={"weights": {}},
        )
        m_run = MatchingRun.objects.create(
            rfq=self.rfq,
            rfq_version=1,
            audience=MatchingAudience.BUYER,
            policy_version=policy_ver,
            engine_version=DEFAULT_ENGINE_VERSION,
        )
        MatchingCandidate.objects.create(
            run=m_run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            supplier_organization=self.supplier_org,
            eligible=True,
            ranking_score=Decimal("95.00"),
        )

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        status, channel, _ = resolve_deal_attribution(deal)
        # Matching candidate alone does not classify as PLATFORM_NETWORK
        self.assertNotEqual(channel, DealAttributionChannel.PLATFORM_NETWORK)
        self.assertEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)

    def test_unknown_origin_resolves_to_pending(self):
        """Deal with off-platform External Counterparty and no Opportunity resolves to PENDING."""
        # Remove source opportunity from external offer to simulate unknown/unattributed origin
        self.ext_offer.source_opportunity = None
        self.ext_offer.save(update_fields=["source_opportunity"])

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, _ = resolve_deal_attribution(deal)
        self.assertEqual(status, DealAttributionStatus.PENDING)
        self.assertIsNone(channel)

    def test_direct_supplier_never_used_as_unknown_fallback(self):
        """DIRECT_SUPPLIER is never assigned when direct internal participation is not established."""
        self.ext_offer.source_opportunity = None
        self.ext_offer.save(update_fields=["source_opportunity"])

        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        status, channel, _ = resolve_deal_attribution(deal)
        self.assertNotEqual(channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertEqual(status, DealAttributionStatus.PENDING)

    def test_resolver_determinism(self):
        """Resolver returns identical result when run repeatedly on the same Deal."""
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        res1 = resolve_deal_attribution(deal)
        res2 = resolve_deal_attribution(deal)
        self.assertEqual(res1[0], res2[0])
        self.assertEqual(res1[1], res2[1])
        self.assertEqual(res1[2], res2[2])

    def test_evidence_snapshot_structure_and_privacy(self):
        """Evidence snapshot preserves structured IDs and omits sensitive personal details."""
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )

        evidence = collect_deal_attribution_evidence(deal)
        self.assertEqual(evidence["deal_id"], str(deal.id))
        self.assertEqual(evidence["award_id"], str(self.award.id))
        self.assertEqual(evidence["rfq_id"], str(self.rfq.id))
        self.assertEqual(evidence["buyer_organization_id"], str(self.buyer_org.id))
        self.assertEqual(evidence["seller_external_counterparty_id"], str(self.ext_counterparty.id))

        # Privacy checks: ensure phone, email, contact name, notes are NOT in snapshot
        snapshot_str = str(evidence)
        self.assertNotIn(self.ext_counterparty.phone, snapshot_str)
        self.assertNotIn(self.ext_counterparty.email, snapshot_str)
        self.assertNotIn(self.ext_counterparty.contact_name, snapshot_str)

    def test_source_mutation_does_not_rewrite_resolved_attribution(self):
        """Modifying source RFQ/Offer/Org after resolution does not alter resolved attribution record."""
        deal = Deal.objects.create(
            award=self.award,
            award_allocation=self.supplier_alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        status, channel, evidence = resolve_deal_attribution(deal)
        attr = DealAttribution.objects.create(
            deal=deal,
            status=status,
            primary_channel=channel,
            resolution_method="AUTOMATIC",
            resolved_at=deal.created_at,
            evidence_snapshot=evidence,
        )

        # Later mutate RFQ notes
        self.rfq.notes = "Updated notes after deal attribution."
        self.rfq.save(update_fields=["notes"])

        # Mutate Supplier Organization name
        self.supplier_org.name = "Apex Refineries Global"
        self.supplier_org.save(update_fields=["name"])

        attr.refresh_from_db()
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.primary_channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertEqual(attr.evidence_snapshot, evidence)
