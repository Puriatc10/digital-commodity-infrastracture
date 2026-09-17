from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import User
from matching.candidates.broker_organization import BrokerCandidateProvider
from matching.candidates.context import ActorScope, CandidateContext
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
from matching.rules.geography import GeographicEvidenceRole
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationOperatingArea,
)
from trade_hub.models.rfq import RFQ, RFQStatus


class ProviderBrokerTests(TestCase):
    """
    Test suite for BrokerCandidateProvider.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.user = User.objects.create(email="broker_user@test.com")

        self.commodity_bitumen = CommodityDefinition.objects.create(
            code="bitumen-broker-test",
            name_en="Bitumen Broker Test",
            name_fa="قیر بروکری",
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
        self.provider = BrokerCandidateProvider()

    def test_broker_capability_accepted_supplier_only_excluded(self):
        """Only organizations with Broker capability are discovered in the Broker Path lane."""
        # Broker
        broker = Organization.objects.create(name="Gulf Brokerage", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity_bitumen)

        # Supplier only
        supplier = Organization.objects.create(name="Supplier Only Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(broker.id))
        self.assertEqual(candidates[0].lane, CandidateLane.BROKER_PATH)
        self.assertEqual(candidates[0].candidate_kind, CandidateKind.BROKER_ORGANIZATION)

    def test_multi_capability_broker_accepted(self):
        """Organization with both Broker and Supplier capabilities is accepted in Broker lane."""
        multi = Organization.objects.create(name="Trading & Brokerage Co", is_active=True)
        OrganizationCapability.objects.create(
            organization=multi, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCapability.objects.create(
            organization=multi, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=multi, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(multi.id))
        self.assertIn("broker", candidates[0].evidence["capabilities"])

    def test_inactive_and_self_match_excluded(self):
        """Inactive brokers and self-matching RFQ owner are excluded."""
        # Inactive broker
        inactive = Organization.objects.create(name="Inactive Broker", is_active=False)
        OrganizationCapability.objects.create(
            organization=inactive, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=inactive, commodity=self.commodity_bitumen)

        # RFQ owner with broker capability
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(
            organization=self.buyer_org, commodity=self.commodity_bitumen
        )

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 0)

    def test_zero_inventory_claims(self):
        """Brokers are facilitators: snapshot must NEVER claim inventory or supply listings."""
        broker = Organization.objects.create(name="Pure Facilitator", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity_bitumen)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence
        self.assertIsNone(ev["quantity"])
        self.assertIsNone(ev["unit"])
        self.assertIsNone(ev["availability_window_start"])
        self.assertIsNone(ev["availability_window_end"])
        self.assertEqual(ev["specifications"], {})

    def test_explicit_operating_area_preserved(self):
        """Operating area is preserved without headquarters inference."""
        country = GeographicArea.objects.create(
            code="IR-BROKER-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        area = GeographicArea.objects.create(
            code="IR-HOR-BROKER",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Hormozgan",
            name_fa="هرمزگان",
            parent=country,
        )
        broker = Organization.objects.create(name="Bandar Broker", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity_bitumen)
        OrganizationOperatingArea.objects.create(organization=broker, area=area)

        candidates = self.provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)
        geo = candidates[0].evidence["geography"]
        self.assertEqual(geo["evidence_role"], GeographicEvidenceRole.OPERATING_AREA)
        self.assertEqual(len(geo["operating_areas"]), 1)
        self.assertEqual(geo["operating_areas"][0]["area_code"], "IR-HOR-BROKER")
