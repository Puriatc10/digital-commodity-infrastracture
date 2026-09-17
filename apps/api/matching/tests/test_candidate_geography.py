from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import User
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.candidates.supply_listing import SupplyListingCandidateProvider
from matching.enums import MatchingAudience, SignalOutcome
from matching.rules.geography import (
    GeographicEvidenceRole,
    GeographyConstraintMode,
    GeographyConstraintSnapshot,
    TargetGeographySnapshot,
    evaluate_geography,
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


class CandidateGeographyTests(TestCase):
    """
    Mandatory tests verifying structured geography invariants:
    - Registered HQ / country never inferred as operating area
    - Explicit OrganizationOperatingArea produces structured OPERATING_AREA
    - Legacy free-text string without structured area produces NO structured area (no string guessing)
    - Snapshots seamlessly evaluate with T0702 evaluate_geography engine rule
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.user = User.objects.create(email="user@test.com")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-geo-test",
            name_en="Bitumen Geo Test",
            name_fa="قیر جغرافیایی",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        # Hierarchy: Country (Iran) -> Province (Tehran) -> City (Tehran City)
        self.country_iran = GeographicArea.objects.create(
            code="IR",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        self.province_tehran = GeographicArea.objects.create(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Tehran Province",
            name_fa="استان تهران",
            parent=self.country_iran,
        )
        self.city_tehran = GeographicArea.objects.create(
            code="IR-07-TEH",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Tehran City",
            name_fa="شهر تهران",
            parent=self.province_tehran,
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
        self.actor_scope = ActorScope(user=self.user, organization=self.buyer_org)

    def test_hq_tehran_without_operating_area_produces_no_geography_evidence(self):
        """Organization with registered country='IR' and no operating areas produces empty operating_areas and organization_hq_only=True."""
        supplier_hq_only = Organization.objects.create(
            name="HQ In Tehran Org",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=supplier_hq_only, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=supplier_hq_only, commodity=self.commodity
        )

        provider = SupplierOrganizationCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        geo = candidates[0].evidence["geography"]
        self.assertEqual(geo["evidence_role"], GeographicEvidenceRole.OPERATING_AREA)
        self.assertEqual(geo["operating_areas"], [])
        self.assertTrue(geo["organization_hq_only"])

        # Directly evaluate with T0702 engine rule
        cand_geo_snap = candidates[0].to_candidate_geography_snapshot()
        target_geo_snap = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.province_tehran,
                    area_code="IR-07",
                ),
            )
        )
        rule_result = evaluate_geography(target_geo_snap, cand_geo_snap)
        self.assertEqual(rule_result.outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(rule_result.reason_code, "GEOGRAPHY_NO_EXPLICIT_OPERATING_AREA")

    def test_explicit_operating_area_produces_structured_operating_area_snapshot(self):
        """Organization with explicit OrganizationOperatingArea produces valid OPERATING_AREA snapshot."""
        supplier = Organization.objects.create(name="Regional Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationOperatingArea.objects.create(
            organization=supplier,
            area=self.province_tehran,
        )

        provider = SupplierOrganizationCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        geo = candidates[0].evidence["geography"]
        self.assertEqual(geo["evidence_role"], GeographicEvidenceRole.OPERATING_AREA)
        self.assertEqual(len(geo["operating_areas"]), 1)
        self.assertEqual(geo["operating_areas"][0]["area_code"], "IR-07")
        self.assertFalse(geo["organization_hq_only"])

        # Directly evaluate with T0702 engine rule
        cand_geo_snap = candidates[0].to_candidate_geography_snapshot()
        target_geo_snap = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.city_tehran,
                    area_code="IR-07-TEH",
                ),
            )
        )
        rule_result = evaluate_geography(target_geo_snap, cand_geo_snap)
        # Operating area (province) covering city -> PASS
        self.assertEqual(rule_result.outcome, SignalOutcome.PASS)

    def test_legacy_string_without_structured_area_never_infers_authoritative_geography(self):
        """Listing with free-text origin='تهران' and origin_area=None produces NO structured SUPPLY_LOCATION."""
        supplier = Organization.objects.create(name="Free Text Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("100.000"),
            origin="تهران",  # Legacy string
            origin_area=None,  # No structured area
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        provider = SupplyListingCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        geo = candidates[0].evidence["geography"]
        self.assertEqual(geo["evidence_role"], GeographicEvidenceRole.SUPPLY_LOCATION)
        self.assertIsNone(geo["area_id"])
        self.assertEqual(geo["area_code"], "")
        self.assertTrue(geo["has_only_free_text"])

        # Directly evaluate with T0702 engine rule
        cand_geo_snap = candidates[0].to_candidate_geography_snapshot()
        target_geo_snap = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.province_tehran,
                    area_code="IR-07",
                ),
            )
        )
        rule_result = evaluate_geography(target_geo_snap, cand_geo_snap)
        self.assertEqual(rule_result.outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(rule_result.reason_code, "GEOGRAPHY_FREE_TEXT_ONLY")
