from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import User
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.service import discover_candidates
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
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


class CandidateDeterminismTests(TestCase):
    """
    Mandatory tests for snapshot determinism, stable keys, deterministic ordering,
    and distinct preservation of different evidence artifacts under the same organization.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.buyer_user = User.objects.create(email="buyer_det@test.com")
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-det-test",
            name_en="Bitumen Determinism Test",
            name_fa="قیر دترمینیسم",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.BUYER,
        )
        self.actor_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org)

    def test_repeated_discovery_deterministic(self):
        """Running discovery multiple times over unchanged DB state yields exactly identical results."""
        # Create multiple candidate sources
        supplier = Organization.objects.create(name="Supplier Alpha", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)

        broker = Organization.objects.create(name="Broker Beta", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity)

        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("200.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run1 = discover_candidates(self.context, self.actor_scope)
        run2 = discover_candidates(self.context, self.actor_scope)
        run3 = discover_candidates(self.context, self.actor_scope)

        self.assertEqual(len(run1), 3)
        self.assertEqual(
            [c.stable_candidate_key for c in run1],
            [c.stable_candidate_key for c in run2],
        )
        self.assertEqual(
            [c.stable_candidate_key for c in run2],
            [c.stable_candidate_key for c in run3],
        )
        self.assertEqual(
            [c.to_dict() for c in run1],
            [c.to_dict() for c in run2],
        )

    def test_operating_areas_insertion_order_invariance(self):
        """Normalized snapshot operating areas order is deterministic regardless of DB insertion order."""
        country = GeographicArea.objects.create(
            code="IR-DET-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        area1 = GeographicArea.objects.create(
            code="IR-01-A",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Area A",
            name_fa="منطقه الف",
            parent=country,
        )
        area2 = GeographicArea.objects.create(
            code="IR-02-B",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Area B",
            name_fa="منطقه ب",
            parent=country,
        )
        area3 = GeographicArea.objects.create(
            code="IR-03-C",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Area C",
            name_fa="منطقه ج",
            parent=country,
        )

        # Org 1 inserted in order: C, A, B
        org1 = Organization.objects.create(name="Supplier CAB", is_active=True)
        OrganizationCapability.objects.create(
            organization=org1, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=org1, commodity=self.commodity)
        OrganizationOperatingArea.objects.create(organization=org1, area=area3)
        OrganizationOperatingArea.objects.create(organization=org1, area=area1)
        OrganizationOperatingArea.objects.create(organization=org1, area=area2)

        # Org 2 inserted in order: B, C, A
        org2 = Organization.objects.create(name="Supplier BCA", is_active=True)
        OrganizationCapability.objects.create(
            organization=org2, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=org2, commodity=self.commodity)
        OrganizationOperatingArea.objects.create(organization=org2, area=area2)
        OrganizationOperatingArea.objects.create(organization=org2, area=area3)
        OrganizationOperatingArea.objects.create(organization=org2, area=area1)

        provider = SupplierOrganizationCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 2)

        by_id = {c.source_id: c for c in candidates}
        org1_ops = [
            oa["area_code"]
            for oa in by_id[str(org1.id)].evidence["geography"]["operating_areas"]
        ]
        org2_ops = [
            oa["area_code"]
            for oa in by_id[str(org2.id)].evidence["geography"]["operating_areas"]
        ]

        # Both must be deterministically sorted by area code: IR-01-A, IR-02-B, IR-03-C
        expected = ["IR-01-A", "IR-02-B", "IR-03-C"]
        self.assertEqual(org1_ops, expected)
        self.assertEqual(org2_ops, expected)

    def test_no_blind_deduplication_by_organization(self):
        """
        CRITICAL REQUIREMENT:
        SupplierOrganization X and SupplyListing X1 and SupplyListing X2 are distinct candidates.
        They MUST NOT be deduplicated into a single candidate.
        """
        supplier_org = Organization.objects.create(name="Multi Listing Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=supplier_org, commodity=self.commodity
        )

        # Listing 1
        listing1 = SupplyListing.objects.create(
            organization=supplier_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("100.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        # Listing 2
        listing2 = SupplyListing.objects.create(
            organization=supplier_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("200.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        candidates = discover_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 3)

        source_ids = {c.source_id for c in candidates}
        self.assertIn(str(supplier_org.id), source_ids)
        self.assertIn(str(listing1.id), source_ids)
        self.assertIn(str(listing2.id), source_ids)

        kinds = [c.candidate_kind for c in candidates]
        self.assertEqual(kinds.count(CandidateKind.SUPPLY_LISTING), 2)
        self.assertEqual(kinds.count(CandidateKind.SUPPLIER_ORGANIZATION), 1)

        lanes = [c.lane for c in candidates]
        self.assertEqual(lanes.count(CandidateLane.DIRECT_SUPPLY), 2)
        self.assertEqual(lanes.count(CandidateLane.POTENTIAL_SUPPLIER), 1)
