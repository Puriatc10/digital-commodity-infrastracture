from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import User
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.supply_listing import SupplyListingCandidateProvider
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
from matching.rules.geography import GeographicEvidenceRole
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
)
from trade_hub.models.rfq import RFQ, RFQStatus
from trade_hub.models.supply import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


class ProviderSupplyListingTests(TestCase):
    """
    Test suite for SupplyListingCandidateProvider.
    """

    def setUp(self):
        # Buyer Organization and User
        self.buyer_org = Organization.objects.create(name="Petro Buyer Co", is_active=True)
        self.buyer_user = User.objects.create(email="buyer@petrobuyer.com")
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Supplier Organization and User
        self.supplier_org = Organization.objects.create(name="Refinery Direct Ltd", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user = User.objects.create(email="supplier@refinery.com")
        OrganizationMembership.objects.create(
            user=self.supplier_user,
            organization=self.supplier_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Commodities
        self.commodity_bitumen = CommodityDefinition.objects.create(
            code="bitumen-listing-test",
            name_en="Bitumen Test",
            name_fa="قیر تستی",
        )
        self.commodity_other = CommodityDefinition.objects.create(
            code="urea-listing-test",
            name_en="Urea Test",
            name_fa="اوره تستی",
        )

        # Schema version 1
        self.schema_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity_bitumen,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )
        # Schema version 2 (newer active schema)
        self.schema_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity_bitumen,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        # Geographic Area
        self.area_iran = GeographicArea.objects.create(
            code="IR-LISTING-TEST",
            name_en="Iran",
            name_fa="ایران",
            area_type=AreaType.COUNTRY,
            country_code="IR",
        )

        # RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("1000.000"),
            status=RFQStatus.PUBLISHED,
        )

        # Context and Scope
        self.context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity_bitumen.id,
            audience=MatchingAudience.BUYER,
        )
        self.actor_scope = ActorScope(
            user=self.buyer_user,
            organization=self.buyer_org,
            is_operator_or_admin=False,
        )
        self.provider = SupplyListingCandidateProvider()

    def test_usable_lifecycle_active_included_draft_expired_closed_excluded(self):
        """Only listings with active status are discovered; draft, expired, closed are excluded."""
        active_listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        # Inactive listings
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.DRAFT,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.EXPIRED,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.CLOSED,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(active_listing.id))
        self.assertEqual(candidates[0].lane, CandidateLane.DIRECT_SUPPLY)
        self.assertEqual(candidates[0].candidate_kind, CandidateKind.SUPPLY_LISTING)

    def test_commodity_filtering(self):
        """Listings for a different commodity are excluded from candidate discovery."""
        schema_other = CommoditySchemaVersion.objects.create(
            commodity=self.commodity_other,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_other,
            schema_version=schema_other,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 0)

    def test_self_match_exclusion(self):
        """Listings owned by the RFQ buyer organization must be excluded."""
        SupplyListing.objects.create(
            organization=self.buyer_org,  # Same as RFQ owner
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 0)

    def test_visibility_rules_network_and_private(self):
        """Network tier requires matching OrganizationCommodity, private is hidden from external."""
        # Public listing
        public_listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        # Private listing
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PRIVATE,
        )
        # Network listing without buyer having OrganizationCommodity
        network_listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.NETWORK,
        )

        # Before buyer has OrganizationCommodity for bitumen
        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        discovered_ids = {c.source_id for c in candidates}
        self.assertIn(str(public_listing.id), discovered_ids)
        self.assertNotIn(str(network_listing.id), discovered_ids)

        # Grant buyer OrganizationCommodity
        OrganizationCommodity.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity_bitumen,
        )
        candidates_after = self.provider.find_candidates(self.context, self.actor_scope)
        discovered_ids_after = {c.source_id for c in candidates_after}
        self.assertIn(str(public_listing.id), discovered_ids_after)
        self.assertIn(str(network_listing.id), discovered_ids_after)

    def test_schema_and_specifications_exactness(self):
        """Candidate snapshot preserves exact creation-time schema version and specs without active schema reinterpretation."""
        specs_v1 = {"penetration_grade": "60_70", "softening_point": 49}
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            specifications=specs_v1,
            quantity=Decimal("300.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence
        self.assertEqual(ev["schema_version_id"], str(self.schema_v1.id))
        self.assertEqual(ev["schema_version_number"], 1)
        self.assertEqual(ev["specifications"], {"penetration_grade": "60_70", "softening_point": 49})
        self.assertNotEqual(ev["schema_version_id"], str(self.schema_v2.id))

    def test_structured_geography_vs_legacy_free_text(self):
        """Structured area produces valid evidence; legacy string alone produces area=None and has_only_free_text=True."""
        # Listing with structured area
        listing_structured = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("200.000"),
            origin_area=self.area_iran,
            origin="Tehran Refinery",
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        geo = candidates[0].evidence["geography"]
        self.assertEqual(geo["evidence_role"], GeographicEvidenceRole.SUPPLY_LOCATION)
        self.assertEqual(geo["area_id"], str(self.area_iran.id))
        self.assertEqual(geo["area_code"], "IR-LISTING-TEST")
        self.assertFalse(geo["has_only_free_text"])

        # Listing with only free-text
        listing_structured.origin_area = None
        listing_structured.save()

        candidates_legacy = self.provider.find_candidates(self.context, self.actor_scope)
        geo_legacy = candidates_legacy[0].evidence["geography"]
        self.assertIsNone(geo_legacy["area_id"])
        self.assertEqual(geo_legacy["area_code"], "")
        self.assertTrue(geo_legacy["has_only_free_text"])

    def test_snapshot_privacy_omits_internal_notes_and_credentials(self):
        """Snapshot must NOT include internal notes, credentials, or sensitive metadata."""
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema_v1,
            quantity=Decimal("200.000"),
            notes="Secret operational note that should never leak to buyer",
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence
        self.assertNotIn("notes", ev)
        self.assertNotIn("created_by", ev)
        self.assertNotIn("credentials", ev)
