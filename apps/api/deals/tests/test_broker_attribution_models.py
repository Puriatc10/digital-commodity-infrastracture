import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from deals.models import (
    Deal,
    DealBrokerAttribution,
    DealBrokerRole,
    DealOpportunityAttribution,
    DealOpportunityRole,
)
from deals.tests.base import BaseDealsTestCase
from opportunities.models import Opportunity, OpportunityDirection, OpportunitySource, OpportunityStatus
from organizations.models import Organization, OrganizationCapability


class DealBrokerAttributionModelTests(BaseDealsTestCase):
    """
    Model, constraint, and PostgreSQL uniqueness tests for DealBrokerAttribution
    and DealOpportunityAttribution (Epic 9 Contract §50-§59, T0904).
    """

    def setUp(self):
        super().setUp()
        award, alloc = self.create_and_finalize_single_award()
        self.deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        # Second broker organization for multi-broker tests
        self.broker_org_2 = Organization.objects.create(
            name="Second Broker Corp",
            country="CH",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org_2,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        # Opportunities for linkage tests
        self.opportunity_1 = Opportunity.objects.create(
            identifier=f"OPP-SUPPLY-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
        )
        self.opportunity_2 = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org_2,
            status=OpportunityStatus.QUALIFIED,
        )

    # -------------------------------------------------------------------------
    # Role Constraint Tests
    # -------------------------------------------------------------------------
    def test_broker_attribution_valid_roles(self):
        """SUPPLY_ORIGINATOR and DEMAND_ORIGINATOR are both valid broker roles."""
        attr_supply = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=self.opportunity_1,
        )
        self.assertEqual(attr_supply.role, DealBrokerRole.SUPPLY_ORIGINATOR)

        attr_demand = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org_2,
            role=DealBrokerRole.DEMAND_ORIGINATOR,
            related_opportunity=self.opportunity_2,
        )
        self.assertEqual(attr_demand.role, DealBrokerRole.DEMAND_ORIGINATOR)

    def test_broker_attribution_invalid_role_rejected(self):
        """Generic or fabricated roles like 'BROKER' or 'TRADER' violate CheckConstraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealBrokerAttribution.objects.create(
                    deal=self.deal,
                    broker_organization=self.broker_org,
                    role="GENERIC_BROKER",
                )

    def test_opportunity_attribution_valid_roles(self):
        """DEMAND_ORIGIN and SUPPLY_ORIGIN are both valid opportunity roles."""
        opp_attr_supply = DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_1,
            role=DealOpportunityRole.SUPPLY_ORIGIN,
        )
        self.assertEqual(opp_attr_supply.role, DealOpportunityRole.SUPPLY_ORIGIN)

        opp_attr_demand = DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_2,
            role=DealOpportunityRole.DEMAND_ORIGIN,
        )
        self.assertEqual(opp_attr_demand.role, DealOpportunityRole.DEMAND_ORIGIN)

    def test_opportunity_attribution_invalid_role_rejected(self):
        """Invalid opportunity role string violates CheckConstraint."""
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealOpportunityAttribution.objects.create(
                    deal=self.deal,
                    opportunity=self.opportunity_1,
                    role="INVALID_ROLE",
                )

    # -------------------------------------------------------------------------
    # Multi-Broker & Multi-Role Support
    # -------------------------------------------------------------------------
    def test_distinct_brokers_on_both_roles(self):
        """One Deal can have two distinct Brokers in Demand and Supply originator roles."""
        b1 = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=self.opportunity_1,
        )
        b2 = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org_2,
            role=DealBrokerRole.DEMAND_ORIGINATOR,
            related_opportunity=self.opportunity_2,
        )
        self.assertEqual(self.deal.broker_attributions.count(), 2)
        self.assertIn(b1, self.deal.broker_attributions.all())
        self.assertIn(b2, self.deal.broker_attributions.all())

    def test_same_broker_both_roles(self):
        """The same Broker organization can hold both SUPPLY_ORIGINATOR and DEMAND_ORIGINATOR roles."""
        b_supply = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=self.opportunity_1,
        )
        b_demand = DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.DEMAND_ORIGINATOR,
            related_opportunity=self.opportunity_2,
        )
        self.assertEqual(self.deal.broker_attributions.count(), 2)
        self.assertEqual(b_supply.broker_organization, b_demand.broker_organization)
        self.assertNotEqual(b_supply.role, b_demand.role)

    def test_both_opportunities_coexist(self):
        """One Deal can have both DEMAND_ORIGIN and SUPPLY_ORIGIN opportunities."""
        o_supply = DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_1,
            role=DealOpportunityRole.SUPPLY_ORIGIN,
        )
        o_demand = DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_2,
            role=DealOpportunityRole.DEMAND_ORIGIN,
        )
        self.assertEqual(self.deal.opportunity_attributions.count(), 2)
        self.assertIn(o_supply, self.deal.opportunity_attributions.all())
        self.assertIn(o_demand, self.deal.opportunity_attributions.all())

    # -------------------------------------------------------------------------
    # Deduplication & PostgreSQL NULL Uniqueness
    # -------------------------------------------------------------------------
    def test_duplicate_opportunity_tuple_rejected(self):
        """Duplicate (deal, opportunity, role) violates database uniqueness."""
        DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_1,
            role=DealOpportunityRole.SUPPLY_ORIGIN,
        )
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealOpportunityAttribution.objects.create(
                    deal=self.deal,
                    opportunity=self.opportunity_1,
                    role=DealOpportunityRole.SUPPLY_ORIGIN,
                )

    def test_duplicate_broker_tuple_with_opportunity_rejected(self):
        """Duplicate (deal, broker, role, related_opportunity) violates database uniqueness."""
        DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=self.opportunity_1,
        )
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealBrokerAttribution.objects.create(
                    deal=self.deal,
                    broker_organization=self.broker_org,
                    role=DealBrokerRole.SUPPLY_ORIGINATOR,
                    related_opportunity=self.opportunity_1,
                )

    def test_duplicate_broker_tuple_with_null_opportunity_rejected(self):
        """
        PostgreSQL 15+ nulls_distinct=False guarantee:
        Duplicate (deal, broker, role, NULL) is strictly rejected at the DB level.
        NULLs compare equal under the unique constraint.
        """
        DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=None,
        )
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                DealBrokerAttribution.objects.create(
                    deal=self.deal,
                    broker_organization=self.broker_org,
                    role=DealBrokerRole.SUPPLY_ORIGINATOR,
                    related_opportunity=None,
                )

    # -------------------------------------------------------------------------
    # Deletion Protection
    # -------------------------------------------------------------------------
    def test_deletion_protection_on_broker_and_opportunity(self):
        """Source Broker Organization and Opportunity are protected from deletion."""
        DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
            related_opportunity=self.opportunity_1,
        )
        DealOpportunityAttribution.objects.create(
            deal=self.deal,
            opportunity=self.opportunity_1,
            role=DealOpportunityRole.SUPPLY_ORIGIN,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.broker_org.delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.opportunity_1.delete()
