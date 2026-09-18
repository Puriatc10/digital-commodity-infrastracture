from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import SystemRoleAssignment, User
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.service import discover_candidates
from matching.enums import MatchingAudience
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
    OrganizationOperatingArea,
)
from trade_hub.models.rfq import RFQ, RFQStatus
from trade_hub.models.supply import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


class CandidateQueryEfficiencyTests(TestCase):
    """
    Query efficiency regression tests proving the absence of per-row N+1 database queries.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.buyer_user = User.objects.create(email="buyer_eff@test.com")
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        self.operator_user = User.objects.create(email="op_eff@test.com")
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-eff-test",
            name_en="Bitumen Efficiency Test",
            name_fa="قیر کارایی کوئری",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        country = GeographicArea.objects.create(
            code="IR-EFF-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        self.area = GeographicArea.objects.create(
            code="IR-EFF-AREA",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Efficiency Area",
            name_fa="منطقه کارایی",
            parent=country,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.operator_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.OPERATOR,
        )
        self.operator_scope = ActorScope(
            user=self.operator_user,
            is_operator_or_admin=True,
        )

    def test_query_count_does_not_scale_linearly_with_candidates(self):
        """
        Verify that discovering 20 candidates across all 4 source types executes
        a bounded constant number of queries rather than an N+1 query per entity.
        """
        # Create 5 Supply Listings
        for i in range(5):
            supplier = Organization.objects.create(name=f"Listing Supplier {i}", is_active=True)
            OrganizationCapability.objects.create(
                organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
            )
            SupplyListing.objects.create(
                organization=supplier,
                commodity=self.commodity,
                schema_version=self.schema,
                quantity=Decimal("100.000"),
                origin_area=self.area,
                status=SupplyListingStatus.ACTIVE,
                visibility=SupplyListingVisibility.PUBLIC,
            )

        # Create 5 Qualified Supply Opportunities
        for i in range(5):
            opp_org = Organization.objects.create(name=f"Opp Supplier {i}", is_active=True)
            Opportunity.objects.create(
                identifier=f"OPP-2026-EFF{i:03d}",
                direction=OpportunityDirection.SUPPLY,
                status=OpportunityStatus.QUALIFIED,
                commodity=self.commodity,
                schema_version=self.schema,
                organization=opp_org,
                quantity=Decimal("200.000"),
                origin_area=self.area,
            )

        # Create 5 Supplier Organizations with Operating Areas
        for i in range(5):
            s_org = Organization.objects.create(name=f"Potential Supplier {i}", is_active=True)
            OrganizationCapability.objects.create(
                organization=s_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
            )
            OrganizationCommodity.objects.create(
                organization=s_org, commodity=self.commodity
            )
            OrganizationOperatingArea.objects.create(organization=s_org, area=self.area)

        # Create 5 Broker Organizations with Operating Areas
        for i in range(5):
            b_org = Organization.objects.create(name=f"Broker {i}", is_active=True)
            OrganizationCapability.objects.create(
                organization=b_org, capability=OrganizationCapability.CapabilityType.BROKER
            )
            OrganizationCommodity.objects.create(
                organization=b_org, commodity=self.commodity
            )
            OrganizationOperatingArea.objects.create(organization=b_org, area=self.area)

        # Total 20 candidate records across 4 providers
        with self.assertNumQueries(13):  # 1 auth check + 1 listing + 1 opp + 5 supplier relations batch-prefetched + 5 broker relations batch-prefetched
            candidates = discover_candidates(self.operator_context, self.operator_scope)
            self.assertEqual(len(candidates), 20)
