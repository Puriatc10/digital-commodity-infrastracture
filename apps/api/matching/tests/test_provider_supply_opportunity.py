from decimal import Decimal

from django.test import TestCase

from django.utils import timezone

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from identity.models import SystemRoleAssignment, User
from matching.candidates.authorization import (
    MatchingAuthorizationError,
    MatchingPrivacyViolationError,
)
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.supply_opportunity import SupplyOpportunityCandidateProvider
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    Opportunity,
    OpportunityContactAttempt,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
    OpportunityTask,
    OpportunityTaskStatus,
)
from organizations.models import Organization, OrganizationCapability, OrganizationMembership
from trade_hub.models.rfq import RFQ, RFQStatus
from trade_hub.models.supply import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)



class ProviderSupplyOpportunityTests(TestCase):
    """
    Test suite for SupplyOpportunityCandidateProvider.
    """

    def setUp(self):
        # Buyer Organization
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.buyer_user = User.objects.create(email="buyer@test.com")
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Operator User
        self.operator_user = User.objects.create(email="operator@test.com")
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # Broker Organization
        self.broker_org = Organization.objects.create(name="Middle East Brokerage", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-opp-test",
            name_en="Bitumen Opp Test",
            name_fa="قیر فرصت",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        # Geography
        self.country = GeographicArea.objects.create(
            code="IR-OPP-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        self.area = GeographicArea.objects.create(
            code="IR-OPP-TEST",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Isfahan",
            name_fa="اصفهان",
            parent=self.country,
        )

        # Target RFQ
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
        self.provider = SupplyOpportunityCandidateProvider()

    def test_operator_discovers_qualified_supply_opportunity(self):
        """Operator discovers qualified supply opportunity with correct lane and kind."""
        opp = Opportunity.objects.create(
            identifier="OPP-2026-OP001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("600.000"),
            origin_area=self.area,
            organization=Organization.objects.create(name="Opp Supplier Ltd", is_active=True),
        )

        candidates = self.provider.find_candidates(self.operator_context, self.operator_scope)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source_id, str(opp.id))
        self.assertEqual(candidates[0].lane, CandidateLane.DIRECT_SUPPLY)
        self.assertEqual(candidates[0].candidate_kind, CandidateKind.SUPPLY_OPPORTUNITY)
        self.assertEqual(candidates[0].stable_candidate_key, f"SUPPLY_OPPORTUNITY:{opp.id}")

    def test_buyer_audience_hard_privacy_rejection(self):
        """Executing provider under BUYER audience immediately raises MatchingPrivacyViolationError."""
        buyer_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.BUYER,
        )
        buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org)

        with self.assertRaises(MatchingPrivacyViolationError):
            self.provider.find_candidates(buyer_context, buyer_scope)

    def test_non_operator_actor_rejection(self):
        """Non-operator user cannot execute Opportunity candidate discovery even with Operator audience context."""
        non_op_scope = ActorScope(user=self.buyer_user, is_operator_or_admin=False)
        with self.assertRaises(MatchingAuthorizationError):
            self.provider.find_candidates(self.operator_context, non_op_scope)

    def test_direction_and_status_lifecycle_exclusions(self):
        """Qualified Demand, Captured Supply, Contacted Supply, Converted Supply must be excluded."""
        # 1. Qualified Demand (wrong direction)
        Opportunity.objects.create(
            identifier="OPP-2026-EXC001",
            direction=OpportunityDirection.DEMAND,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=Organization.objects.create(name="Demand Org"),
        )
        # 2. Captured Supply (not qualified)
        Opportunity.objects.create(
            identifier="OPP-2026-EXC002",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.CAPTURED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=Organization.objects.create(name="Captured Org"),
        )
        # 3. Contacted Supply (not qualified)
        Opportunity.objects.create(
            identifier="OPP-2026-EXC003",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.CONTACTED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=Organization.objects.create(name="Contacted Org"),
        )
        # 4. Converted Supply (terminal state)
        converted_org = Organization.objects.create(name="Converted Org")
        converted_listing = SupplyListing.objects.create(
            organization=converted_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            origin_area=self.area,
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        Opportunity.objects.create(
            identifier="OPP-2026-EXC004",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.CONVERTED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=converted_org,
            converted_supply_listing=converted_listing,
        )

        candidates = self.provider.find_candidates(self.operator_context, self.operator_scope)
        self.assertEqual(len(candidates), 0)

    def test_external_counterparty_sanitization(self):
        """External counterparty phone, email, contact name, contact attempts, notes are stripped."""
        external_cp = ExternalCounterparty.objects.create(
            company_name="Private Foreign Trader S.A.",
            contact_name="Secret Agent Smith",
            phone="+989120000000",
            email="smith@secrettrader.com",
            notes="Extremely confidential counterparty operational notes",
        )
        opp = Opportunity.objects.create(
            identifier="OPP-2026-SAN001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            external_counterparty=external_cp,
            quantity=Decimal("1500.000"),
            notes="Internal qualification note by operator",
        )
        OpportunityContactAttempt.objects.create(
            opportunity=opp,
            type=ContactAttemptType.CALL,
            notes="Attempted phone negotiation",
            recorded_by=self.operator_user,
        )
        OpportunityTask.objects.create(
            opportunity=opp,
            title="Follow-up call",
            status=OpportunityTaskStatus.OPEN,
            assigned_to=self.operator_user,
            created_by=self.operator_user,
            due_at=timezone.now(),
        )

        candidates = self.provider.find_candidates(self.operator_context, self.operator_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence

        # Check counterparty projection
        cp_data = ev["counterparty"]
        self.assertTrue(cp_data["is_external"])
        self.assertEqual(cp_data["external_counterparty_id"], str(external_cp.id))
        self.assertEqual(cp_data["counterparty_name"], "Private Foreign Trader S.A.")
        self.assertNotIn("phone", cp_data)
        self.assertNotIn("email", cp_data)
        self.assertNotIn("contact_name", cp_data)

        # Check internal note and operational leak prevention
        self.assertNotIn("notes", ev)
        self.assertNotIn("contact_attempts", ev)
        self.assertNotIn("tasks", ev)

    def test_broker_attribution_preservation_without_trust_score(self):
        """Broker attribution is preserved for Operator without computing or fabricating trust score."""
        Opportunity.objects.create(
            identifier="OPP-2026-BRK001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            organization=Organization.objects.create(name="Referred Supplier Ltd"),
        )

        candidates = self.provider.find_candidates(self.operator_context, self.operator_scope)
        self.assertEqual(len(candidates), 1)
        ev = candidates[0].evidence
        self.assertIsNotNone(ev["broker_attribution"])
        self.assertEqual(ev["broker_attribution"]["broker_id"], str(self.broker_org.id))
        self.assertEqual(ev["broker_attribution"]["broker_name"], "Middle East Brokerage")
        self.assertNotIn("trust_score", ev)
        self.assertNotIn("broker_trust", ev)

    def test_opportunity_is_never_mutated(self):
        """Discovery is read-only and never mutates Opportunity state, version, or timestamps."""
        opp = Opportunity.objects.create(
            identifier="OPP-2026-MUT001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=Organization.objects.create(name="Immutable Opp Supplier"),
        )
        initial_version = opp.version
        initial_status = opp.status

        self.provider.find_candidates(self.operator_context, self.operator_scope)

        opp.refresh_from_db()
        self.assertEqual(opp.version, initial_version)
        self.assertEqual(opp.status, initial_status)
