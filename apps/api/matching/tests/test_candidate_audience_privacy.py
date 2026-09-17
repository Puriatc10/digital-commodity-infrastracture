from decimal import Decimal

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from identity.models import SystemRoleAssignment, User
from matching.candidates.authorization import MatchingAuthorizationError
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.service import discover_candidates, get_candidate_providers
from matching.candidates.supply_opportunity import SupplyOpportunityCandidateProvider
from matching.enums import MatchingAudience
from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    Opportunity,
    OpportunityContactAttempt,
    OpportunityDirection,
    OpportunityStatus,
)
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


class CandidateAudiencePrivacyTests(TestCase):
    """
    Test suite enforcing strict audience boundaries, privacy guarantees,
    regression tests against hidden count inference, and actor authorization.
    """

    def setUp(self):
        # Buyer Organization and Users
        self.buyer_org = Organization.objects.create(name="Authorized Buyer Co", is_active=True)
        self.buyer_user = User.objects.create(email="buyer_mgr@buyer.com")
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Unrelated Third-Party Organization (Supplier)
        self.unrelated_org = Organization.objects.create(name="Third Party Supplier", is_active=True)
        self.unrelated_user = User.objects.create(email="thirdparty@supplier.com")
        OrganizationMembership.objects.create(
            user=self.unrelated_user,
            organization=self.unrelated_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Operator User
        self.operator_user = User.objects.create(email="platform_op@platform.com")
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # Product Admin User
        self.admin_user = User.objects.create(email="platform_admin@platform.com")
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Django staff-only (no SystemRole)
        self.django_staff_user = User.objects.create(
            email="staff_only@django.com", is_staff=True
        )

        # Django superuser-only (no SystemRole)
        self.django_superuser = User.objects.create(
            email="superuser_only@django.com", is_staff=True, is_superuser=True
        )

        # Anonymous user (None)
        self.anonymous_user = None

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-privacy-test",
            name_en="Bitumen Privacy Test",
            name_fa="قیر تست حریم خصوصی",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        # Target RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.buyer_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.BUYER,
        )
        self.operator_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.OPERATOR,
        )

    def test_provider_suites_by_audience(self):
        """Buyer provider suite excludes Opportunity provider; Operator suite includes it."""
        buyer_providers = get_candidate_providers(MatchingAudience.BUYER)
        operator_providers = get_candidate_providers(MatchingAudience.OPERATOR)

        # Buyer suite must never contain SupplyOpportunityCandidateProvider
        buyer_provider_types = [type(p) for p in buyer_providers]
        self.assertNotIn(SupplyOpportunityCandidateProvider, buyer_provider_types)

        # Operator suite must contain SupplyOpportunityCandidateProvider
        operator_provider_types = [type(p) for p in operator_providers]
        self.assertIn(SupplyOpportunityCandidateProvider, operator_provider_types)

    def test_hidden_opportunity_count_regression(self):
        """
        REGRESSION TEST:
        Buyer output must be IDENTICAL before and after adding 5 internal Qualified Supply Opportunities.
        No count, metadata, or ranking inference is possible.
        """
        # Set up baseline: 1 Supply Listing, 1 Supplier Org, 1 Broker Org
        listing_org = Organization.objects.create(name="Public Supplier Co", is_active=True)
        OrganizationCapability.objects.create(
            organization=listing_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        SupplyListing.objects.create(
            organization=listing_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("300.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        supplier_org = Organization.objects.create(name="Potential Supplier Co", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationCommodity.objects.create(
            organization=supplier_org, commodity=self.commodity
        )

        broker_org = Organization.objects.create(name="Broker Co", is_active=True)
        OrganizationCapability.objects.create(
            organization=broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationCommodity.objects.create(
            organization=broker_org, commodity=self.commodity
        )

        buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org)

        # Initial Buyer Discovery
        baseline_candidates = discover_candidates(self.buyer_context, buyer_scope)
        self.assertEqual(len(baseline_candidates), 3)
        baseline_keys = [c.stable_candidate_key for c in baseline_candidates]
        baseline_dicts = [c.to_dict() for c in baseline_candidates]

        # Add 5 internal Qualified Supply Opportunities (some with ExternalCounterparties)
        for i in range(5):
            ext_cp = ExternalCounterparty.objects.create(
                company_name=f"Internal Lead CP {i}",
                phone=f"+12345678{i}",
                email=f"lead_{i}@hidden.com",
            )
            opp = Opportunity.objects.create(
                identifier=f"OPP-2026-PRIV{i:03d}",
                direction=OpportunityDirection.SUPPLY,
                status=OpportunityStatus.QUALIFIED,
                commodity=self.commodity,
                schema_version=self.schema,
                external_counterparty=ext_cp,
                quantity=Decimal(f"100{i}.000"),
                notes="Confidential pipeline opportunity",
            )
            OpportunityContactAttempt.objects.create(
                opportunity=opp,
                type=ContactAttemptType.CALL,
                notes=f"Attempt {i}",
                recorded_by=self.operator_user,
            )

        # Run Buyer Discovery again
        after_candidates = discover_candidates(self.buyer_context, buyer_scope)

        # Assert zero leakage and exact identity
        self.assertEqual(len(after_candidates), len(baseline_candidates))
        after_keys = [c.stable_candidate_key for c in after_candidates]
        self.assertEqual(after_keys, baseline_keys)
        after_dicts = [c.to_dict() for c in after_candidates]
        self.assertEqual(after_dicts, baseline_dicts)

    def test_opportunity_data_leakage_prevention(self):
        """Buyer candidate output never contains any Opportunity identifiers or external counterparty data."""
        ext_cp = ExternalCounterparty.objects.create(
            company_name="Confidential Middleman AG",
            contact_name="Mr. Leak",
            phone="+41790000000",
            email="leak@confidential.ch",
            notes="Private high-risk lead",
        )
        opp = Opportunity.objects.create(
            identifier="OPP-2026-LEAK001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            external_counterparty=ext_cp,
            quantity=Decimal("5000.000"),
        )

        buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org)
        candidates = discover_candidates(self.buyer_context, buyer_scope)

        serialized = str([c.to_dict() for c in candidates])
        self.assertNotIn(str(opp.id), serialized)
        self.assertNotIn(opp.identifier, serialized)
        self.assertNotIn(str(ext_cp.id), serialized)
        self.assertNotIn("Confidential Middleman", serialized)
        self.assertNotIn("Mr. Leak", serialized)
        self.assertNotIn("+41790000000", serialized)
        self.assertNotIn("leak@confidential.ch", serialized)

    def test_actor_entry_point_authorization(self):
        """Verify strict authorization checks for all actor personas."""
        # 1. Authorized Buyer-side RFQ manager -> allowed for Buyer
        buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org)
        res_buyer = discover_candidates(self.buyer_context, buyer_scope)
        self.assertIsInstance(res_buyer, tuple)

        # 2. Operator -> allowed for Operator
        op_scope = ActorScope(user=self.operator_user, is_operator_or_admin=True)
        res_op = discover_candidates(self.operator_context, op_scope)
        self.assertIsInstance(res_op, tuple)

        # 3. Product Admin -> allowed for Operator
        admin_scope = ActorScope(user=self.admin_user, is_operator_or_admin=True)
        res_admin = discover_candidates(self.operator_context, admin_scope)
        self.assertIsInstance(res_admin, tuple)

        # 4. Supplier / Broker / Unrelated third-party organization -> rejected
        unrelated_scope = ActorScope(user=self.unrelated_user, organization=self.unrelated_org)
        with self.assertRaises(MatchingAuthorizationError):
            discover_candidates(self.buyer_context, unrelated_scope)
        with self.assertRaises(MatchingAuthorizationError):
            discover_candidates(self.operator_context, unrelated_scope)

        # 5. Django staff-only (without SystemRole) -> rejected from Operator
        staff_scope = ActorScope(user=self.django_staff_user, is_operator_or_admin=False)
        with self.assertRaises(MatchingAuthorizationError):
            discover_candidates(self.operator_context, staff_scope)

        # 6. Django superuser-only (without SystemRole) -> rejected from Operator
        superuser_scope = ActorScope(user=self.django_superuser, is_operator_or_admin=False)
        with self.assertRaises(MatchingAuthorizationError):
            discover_candidates(self.operator_context, superuser_scope)

        # 7. Anonymous user -> rejected
        anon_scope = ActorScope(user=None)
        with self.assertRaises(MatchingAuthorizationError):
            discover_candidates(self.buyer_context, anon_scope)
