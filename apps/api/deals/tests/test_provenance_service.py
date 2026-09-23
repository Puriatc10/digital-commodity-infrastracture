from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model

from deals.models import (
    Deal,
    DealAttributionChannel,
    DealBrokerRole,
    DealOpportunityRole,
)
from deals.services.attribution_resolver import resolve_deal_attribution
from deals.services.provenance import persist_deal_provenance
from deals.tests.base import BaseDealsTestCase
from offers.enums import OfferorRole
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import Organization, OrganizationCapability

User = get_user_model()


class DealProvenanceServiceTests(BaseDealsTestCase):
    """
    Unit and integration tests for DealBrokerAttribution and DealOpportunityAttribution
    provenance extraction and persistence (Epic 9 Contract §50-§59, T0904).
    """

    def setUp(self):
        super().setUp()
        award, allocs = self.create_and_finalize_multi_award()
        self.award = award
        self.supplier_alloc, self.broker_alloc, self.ext_alloc = allocs

        # Second broker organization for multi-broker scenarios
        self.broker_org_2 = Organization.objects.create(
            name="Alpha Broker Corp",
            country="SG",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org_2,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

    # -------------------------------------------------------------------------
    # 1. Supply Originator
    # -------------------------------------------------------------------------
    def test_supply_originator_from_broker_offer(self):
        """Offer submitted by Broker creates SUPPLY_ORIGINATOR broker row."""
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
        opp_rows, broker_rows = persist_deal_provenance(deal)
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.SUPPLY_ORIGINATOR)
        self.assertIsNone(broker_rows[0].related_opportunity)

    def test_supply_originator_from_supply_opportunity_referral(self):
        """Supply Opportunity with BROKER_REFERRAL creates SUPPLY_ORIGINATOR linked to Opportunity."""
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.supplier_offer.source_opportunity = supply_opp
        self.supplier_offer.save(update_fields=["source_opportunity"])

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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        # 1 Opportunity row (SUPPLY_ORIGIN)
        self.assertEqual(len(opp_rows), 1)
        self.assertEqual(opp_rows[0].opportunity, supply_opp)
        self.assertEqual(opp_rows[0].role, DealOpportunityRole.SUPPLY_ORIGIN)

        # 1 Broker row (SUPPLY_ORIGINATOR linked to supply_opp)
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.SUPPLY_ORIGINATOR)
        self.assertEqual(broker_rows[0].related_opportunity, supply_opp)

    # -------------------------------------------------------------------------
    # 2. Demand Originator
    # -------------------------------------------------------------------------
    def test_demand_originator_from_rfq_source_opportunity(self):
        """RFQ converted from Broker-referred Demand Opportunity creates DEMAND_ORIGINATOR broker row."""
        demand_opp = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org_2,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        # 1 Opportunity row (DEMAND_ORIGIN)
        self.assertEqual(len(opp_rows), 1)
        self.assertEqual(opp_rows[0].opportunity, demand_opp)
        self.assertEqual(opp_rows[0].role, DealOpportunityRole.DEMAND_ORIGIN)

        # 1 Broker row (DEMAND_ORIGINATOR)
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org_2)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.DEMAND_ORIGINATOR)
        self.assertEqual(broker_rows[0].related_opportunity, demand_opp)

    # -------------------------------------------------------------------------
    # 3. Both Distinct Brokers on One Deal
    # -------------------------------------------------------------------------
    def test_both_distinct_brokers_both_roles(self):
        """Deal with distinct brokers for Demand and Supply originators."""
        demand_opp = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org_2,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
        )

        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.supplier_offer.source_opportunity = supply_opp
        self.supplier_offer.save(update_fields=["source_opportunity"])

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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        self.assertEqual(len(opp_rows), 2)
        self.assertEqual(len(broker_rows), 2)

        demand_broker = next(b for b in broker_rows if b.role == DealBrokerRole.DEMAND_ORIGINATOR)
        supply_broker = next(b for b in broker_rows if b.role == DealBrokerRole.SUPPLY_ORIGINATOR)

        self.assertEqual(demand_broker.broker_organization, self.broker_org_2)
        self.assertEqual(demand_broker.related_opportunity, demand_opp)
        self.assertEqual(supply_broker.broker_organization, self.broker_org)
        self.assertEqual(supply_broker.related_opportunity, supply_opp)

    # -------------------------------------------------------------------------
    # 4. Same Broker Both Roles
    # -------------------------------------------------------------------------
    def test_same_broker_both_roles_allowed(self):
        """The same Broker organization can be both DEMAND_ORIGINATOR and SUPPLY_ORIGINATOR."""
        demand_opp = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
        )

        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.supplier_offer.source_opportunity = supply_opp
        self.supplier_offer.save(update_fields=["source_opportunity"])

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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        self.assertEqual(len(broker_rows), 2)
        roles = {b.role for b in broker_rows}
        self.assertEqual(roles, {DealBrokerRole.DEMAND_ORIGINATOR, DealBrokerRole.SUPPLY_ORIGINATOR})
        self.assertTrue(all(b.broker_organization == self.broker_org for b in broker_rows))
        self.assertEqual({b.related_opportunity for b in broker_rows}, {demand_opp, supply_opp})

    # -------------------------------------------------------------------------
    # 5. Multiple Brokers from Multi-Source Evidence
    # -------------------------------------------------------------------------
    def test_multiple_brokers_from_offer_and_referral(self):
        """Broker offer thread with a separate Broker referral opportunity creates both rows."""
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org_2,
            status=OpportunityStatus.QUALIFIED,
        )
        self.broker_offer.source_opportunity = supply_opp
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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        # Both broker organizations are SUPPLY_ORIGINATOR with distinct broker orgs
        self.assertEqual(len(broker_rows), 2)
        broker_orgs = {b.broker_organization for b in broker_rows}
        self.assertEqual(broker_orgs, {self.broker_org, self.broker_org_2})

    # -------------------------------------------------------------------------
    # 6. Broker Capability False Positive (NO Capability Inference)
    # -------------------------------------------------------------------------
    def test_no_capability_inference(self):
        """An organization possessing Broker capability WITHOUT explicit provenance gets NO broker row."""
        # Add Broker capability to the supplier organization
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        # Ensure supplier offer was acting in SUPPLIER role and no opportunities exist
        self.assertEqual(self.supplier_offer.offeror_role, OfferorRole.SUPPLIER)
        self.assertIsNone(self.supplier_offer.source_opportunity)

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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        self.assertEqual(len(broker_rows), 0)
        self.assertEqual(len(opp_rows), 0)

    # -------------------------------------------------------------------------
    # 7. External Referral Hero Case
    # -------------------------------------------------------------------------
    def test_external_referral_hero_case(self):
        """
        Hero case:
        Broker Referral -> Qualified Supply Opportunity -> Operator-entered External Supplier Offer -> Award -> Deal.
        Expected:
        - Commercial Seller = ExternalCounterparty
        - Broker attribution: broker = actual Broker Org, role = SUPPLY_ORIGINATOR, related opp = Supply Opportunity.
        - Seller is NOT changed to the broker.
        """
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-HERO-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.ext_counterparty,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.ext_offer.source_opportunity = supply_opp
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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        # Deal party remains strictly ExternalCounterparty
        self.assertIsNone(deal.seller_organization)
        self.assertEqual(deal.seller_external_counterparty, self.ext_counterparty)

        # Broker row captures the referring broker
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.SUPPLY_ORIGINATOR)
        self.assertEqual(broker_rows[0].related_opportunity, supply_opp)

        # Opportunity row captures the supply opportunity
        self.assertEqual(len(opp_rows), 1)
        self.assertEqual(opp_rows[0].opportunity, supply_opp)
        self.assertEqual(opp_rows[0].role, DealOpportunityRole.SUPPLY_ORIGIN)

    # -------------------------------------------------------------------------
    # 8. Broker-as-Seller Independence
    # -------------------------------------------------------------------------
    def test_broker_as_seller_independence(self):
        """When Offer economic party is a Broker, Seller is Broker Organization independently of provenance."""
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
        opp_rows, broker_rows = persist_deal_provenance(deal)

        self.assertEqual(deal.seller_organization, self.broker_org)
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.SUPPLY_ORIGINATOR)

    # -------------------------------------------------------------------------
    # 9. Historical Stability (Capability & Opportunity Changes)
    # -------------------------------------------------------------------------
    def test_broker_capability_removal_preserves_historical_attribution(self):
        """Removing Broker capability from an organization does NOT erase or mutate historical Deal attribution."""
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
        persist_deal_provenance(deal)

        # Deactivate / remove Broker capability
        OrganizationCapability.objects.filter(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        ).delete()

        # Historical row still exists unchanged
        self.assertEqual(deal.broker_attributions.count(), 1)
        row = deal.broker_attributions.first()
        self.assertEqual(row.broker_organization, self.broker_org)
        self.assertEqual(row.role, DealBrokerRole.SUPPLY_ORIGINATOR)

    def test_opportunity_mutation_preserves_historical_linkage(self):
        """Editing Opportunity metadata does NOT rewrite or alter historical Deal attribution rows."""
        supply_opp = Opportunity.objects.create(
            identifier=f"OPP-MUT-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
            notes="Initial notes",
        )
        self.supplier_offer.source_opportunity = supply_opp
        self.supplier_offer.save(update_fields=["source_opportunity"])

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
        persist_deal_provenance(deal)

        # Mutate Opportunity
        supply_opp.notes = "Updated internal operational notes that must not leak"
        supply_opp.indicative_price = Decimal("999.99")
        supply_opp.save()

        # Deal provenance remains rock-solid
        b_row = deal.broker_attributions.first()
        self.assertEqual(b_row.related_opportunity_id, supply_opp.id)
        o_row = deal.opportunity_attributions.first()
        self.assertEqual(o_row.opportunity_id, supply_opp.id)

    # -------------------------------------------------------------------------
    # 10. Primary Attribution Consistency (T0903 + T0904)
    # -------------------------------------------------------------------------
    def test_primary_attribution_consistency(self):
        """When T0903 primary channel is BROKER, T0904 detailed rows match and do not contradict."""
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
        status, primary_channel, evidence = resolve_deal_attribution(deal)
        self.assertEqual(primary_channel, DealAttributionChannel.BROKER)

        opp_rows, broker_rows = persist_deal_provenance(deal)
        self.assertEqual(len(broker_rows), 1)
        self.assertEqual(broker_rows[0].broker_organization, self.broker_org)
        self.assertEqual(broker_rows[0].role, DealBrokerRole.SUPPLY_ORIGINATOR)
