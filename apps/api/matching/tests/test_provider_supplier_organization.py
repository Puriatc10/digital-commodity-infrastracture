from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import User
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
from matching.rules.geography import GeographicEvidenceRole
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationOperatingArea,
)
from trade_hub.models.rfq import RFQ, RFQStatus


class ProviderSupplierOrganizationTests(TestCase):
    """
    Test suite for SupplierOrganizationCandidateProvider.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.user = User.objects.create(email="user@test.com")

        self.commodity_bitumen = CommodityDefinition.objects.create(
            code="bitumen-supplier-test",
            name_en="Bitumen Supplier Test",
            name_fa="قیر تأمین‌کننده",
        )
        self.commodity_other = CommodityDefinition.objects.create(
            code="petcoke-supplier-test",
            name_en="Petcoke Supplier Test",
            name_fa="پت‌کک تستی",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity_bitumen,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity_bitumen,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity_bitumen.id,
            audience=MatchingAudience.BUYER,
        )
        self.actor_scope = ActorScope(user=self.user, organization=self.buyer_org)
        self.provider = SupplierOrganizationCandidateProvider()

    def test_supplier_capability_accepted_broker_only_buyer_only_excluded(self):
        """Only organizations with Supplier capability are included in Potential Supplier lane."""
        # 1. Supplier only
        supplier = Organization.objects.create(name="Valid Supplier Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity_bitumen)

        # 2. Broker only
        broker = Organization.objects.create(name="Broker Only Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity_bitumen)

        # 3. Buyer only
        buyer_other = Organization.objects.create(name="Buyer Only Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=buyer_other, capability=OrganizationCapability.CapabilityType.BUYER
        )
        OrganizationCommodity.objects.create(organization=buyer_other, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(supplier.id))
        self.assertEqual(candidates[0].lane, CandidateLane.POTENTIAL_SUPPLIER)
        self.assertEqual(candidates[0].candidate_kind, CandidateKind.SUPPLIER_ORGANIZATION)

    def test_multi_capability_organization_accepted(self):
        """Organization with both Supplier and Buyer/Broker capabilities is accepted."""
        multi = Organization.objects.create(name="Multi Capability Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=multi, capability=OrganizationCapability.CapabilityType.BUYER
        )
        OrganizationCapability.objects.create(
            organization=multi, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=multi, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(multi.id))
        self.assertIn("buyer", candidates[0].evidence["capabilities"])
        self.assertIn("supplier", candidates[0].evidence["capabilities"])

    def test_inactive_organization_and_self_match_excluded(self):
        """Inactive organizations and the RFQ buyer organization itself must be excluded."""
        # Inactive supplier
        inactive = Organization.objects.create(name="Inactive Supplier", is_active=False)
        OrganizationCapability.objects.create(
            organization=inactive, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=inactive, commodity=self.commodity_bitumen)

        # Self-match (RFQ buyer with supplier capability)
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=self.buyer_org, commodity=self.commodity_bitumen
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 0)

    def test_commodity_association_required(self):
        """Organization trading a different commodity without the target commodity is excluded."""
        other_supplier = Organization.objects.create(name="Petcoke Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=other_supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=other_supplier, commodity=self.commodity_other
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 0)

    def test_zero_inventory_claims_invariant(self):
        """Potential Supplier snapshot must NEVER claim inventory (quantity, availability, specs remain empty)."""
        supplier = Organization.objects.create(name="Pure Supplier Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence
        self.assertIsNone(ev["quantity"])
        self.assertIsNone(ev["unit"])
        self.assertIsNone(ev["availability_window_start"])
        self.assertIsNone(ev["availability_window_end"])
        self.assertEqual(ev["specifications"], {})

    def test_operating_area_vs_headquarters_invariant(self):
        """Operating area is derived strictly from OrganizationOperatingArea; HQ country does NOT become operating area."""
        country = GeographicArea.objects.create(
            code="IR-SUPP-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        area_tehran = GeographicArea.objects.create(
            code="IR-TEH-SUPP",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Tehran Province",
            name_fa="استان تهران",
            parent=country,
        )
        # Supplier with country but NO operating areas
        hq_only_supplier = Organization.objects.create(
            name="HQ Only Supplier",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=hq_only_supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=hq_only_supplier, commodity=self.commodity_bitumen
        )

        # Supplier with explicit operating area
        active_supplier = Organization.objects.create(
            name="Active Area Supplier",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=active_supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=active_supplier, commodity=self.commodity_bitumen
        )
        OrganizationOperatingArea.objects.create(
            organization=active_supplier,
            area=area_tehran,
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 2)

        by_id = {c.source_id: c for c in candidates}

        # 1. HQ-only supplier has empty operating_areas and organization_hq_only=True
        hq_geo = by_id[str(hq_only_supplier.id)].evidence["geography"]
        self.assertEqual(hq_geo["evidence_role"], GeographicEvidenceRole.OPERATING_AREA)
        self.assertEqual(hq_geo["operating_areas"], [])
        self.assertTrue(hq_geo["organization_hq_only"])

        # 2. Active area supplier has structured operating_areas and organization_hq_only=False
        active_geo = by_id[str(active_supplier.id)].evidence["geography"]
        self.assertEqual(active_geo["evidence_role"], GeographicEvidenceRole.OPERATING_AREA)
        self.assertEqual(len(active_geo["operating_areas"]), 1)
        self.assertEqual(active_geo["operating_areas"][0]["area_code"], "IR-TEH-SUPP")
        self.assertFalse(active_geo["organization_hq_only"])
