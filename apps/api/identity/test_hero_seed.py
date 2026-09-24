from decimal import Decimal
import io

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from commodities.services import validate_commodity_payload
from deals.models import Deal
from execution.models.execution import Execution
from identity.seed_hero import (
    HERO_OPP_IDENTIFIER,
    HERO_RFQ_TAG,
    seed_hero_scenario,
)
from matching.candidates.context import ActorScope
from matching.enums import CandidateLane, MatchingAudience
from matching.models.run import MatchingRun
from matching.services import MatchingRunService
from offers.enums import LogisticsCostStatus, OfferorRole
from offers.models import Offer
from offers.services.operator_submission import submit_operator_external_offer
from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    mark_opportunity_contacted,
    qualify_opportunity,
    record_contact_attempt,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import RFQLifecycleService
from trade_hub.services.rfq_service import RFQService

User = get_user_model()


@override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
class HeroScenarioSeedTests(TestCase):
    """
    Test suite for T1302 Hero Scenario Seed.

    Verifies all acceptance criteria:
    - Actor existence (canonical & supporting)
    - Dynamic commodity model resolution (Bitumen 60/70)
    - Matching engine candidate universe (7 Suppliers, 3 Brokers)
    - ExternalCounterparty boundary (strictly off-network)
    - Opportunity prerequisites (OPP-2026-000124, Broker Referral, Supply)
    - Determinism of logical identities
    - Idempotency across repeated executions
    - Boundary invariants (no pre-completed Hero transactions)
    """

    def setUp(self):
        super().setUp()
        self.out = io.StringIO()
        self.summary = seed_hero_scenario(stdout=self.out)

    def test_actor_existence(self):
        """Verify deterministic existence of canonical participants and supporting network actors."""
        # 1. Canonical Buyer
        buyer_user = User.objects.filter(email="buyer@demo.local").first()
        self.assertIsNotNone(buyer_user, "Canonical buyer user must exist.")
        buyer_org = Organization.objects.filter(name="Demo Buyer Corp").first()
        self.assertIsNotNone(buyer_org, "Canonical buyer organization must exist.")
        self.assertTrue(
            OrganizationCapability.objects.filter(
                organization=buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
            ).exists()
        )
        self.assertEqual(buyer_org.verification.status, VerificationStatus.VERIFIED)

        # 2. Canonical Suppliers (Supplier 1 and Supplier 2)
        sup1_user = User.objects.filter(email="supplier@demo.local").first()
        self.assertIsNotNone(sup1_user)
        sup1_org = Organization.objects.filter(name="Demo Supplier LLC").first()
        self.assertIsNotNone(sup1_org)
        self.assertTrue(
            OrganizationCapability.objects.filter(
                organization=sup1_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
            ).exists()
        )
        self.assertEqual(sup1_org.verification.status, VerificationStatus.VERIFIED)

        sup2_user = User.objects.filter(email="supplier.isfahan@demo.local").first()
        self.assertIsNotNone(sup2_user)
        sup2_org = Organization.objects.filter(name="Isfahan Bitumen Refining Co.").first()
        self.assertIsNotNone(sup2_org)
        self.assertTrue(
            OrganizationCapability.objects.filter(
                organization=sup2_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
            ).exists()
        )
        self.assertEqual(sup2_org.verification.status, VerificationStatus.VERIFIED)

        # 3. Canonical Broker
        broker_user = User.objects.filter(email="broker@demo.local").first()
        self.assertIsNotNone(broker_user)
        broker_org = Organization.objects.filter(name="Demo Brokerage").first()
        self.assertIsNotNone(broker_org)
        self.assertTrue(
            OrganizationCapability.objects.filter(
                organization=broker_org, capability=OrganizationCapability.CapabilityType.BROKER
            ).exists()
        )
        self.assertEqual(broker_org.verification.status, VerificationStatus.VERIFIED)

        # 4. Operator Context
        operator_user = User.objects.filter(email="operator@demo.local").first()
        self.assertIsNotNone(operator_user)
        self.assertTrue(
            operator_user.system_roles.filter(role="operator").exists(),
            "Operator user must hold operator system role.",
        )

        # 5. Supporting Matching Distribution
        bitumen = CommodityDefinition.objects.get(code="bitumen")
        bitumen_suppliers = Organization.objects.filter(
            is_active=True,
            capabilities__capability=OrganizationCapability.CapabilityType.SUPPLIER,
            commodities__commodity=bitumen,
        ).distinct()
        self.assertEqual(
            bitumen_suppliers.count(),
            7,
            "Must have exactly 7 active Bitumen Suppliers for candidate discovery.",
        )

        bitumen_brokers = Organization.objects.filter(
            is_active=True,
            capabilities__capability=OrganizationCapability.CapabilityType.BROKER,
            commodities__commodity=bitumen,
        ).distinct()
        self.assertEqual(
            bitumen_brokers.count(),
            3,
            "Must have exactly 3 active Bitumen Brokers for candidate discovery.",
        )

        # 6. Overall Platform Totals (meets roadmap minimum gates)
        total_suppliers = OrganizationCapability.objects.filter(capability="supplier").count()
        total_brokers = OrganizationCapability.objects.filter(capability="broker").count()
        self.assertGreaterEqual(total_suppliers, 8, "Must contain at least 8 Suppliers across platform.")
        self.assertGreaterEqual(total_brokers, 5, "Must contain at least 5 Brokers across platform.")

    def test_commodity_dynamic_resolution(self):
        """Verify Bitumen 60/70 resolves from the real versioned commodity/schema infrastructure."""
        bitumen = CommodityDefinition.objects.filter(code="bitumen", is_active=True).first()
        self.assertIsNotNone(bitumen, "Bitumen commodity definition must exist.")

        schema_version = bitumen.active_schema_version
        self.assertIsNotNone(schema_version, "Bitumen must have an active published schema version.")
        self.assertEqual(schema_version.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)

        # Schema JSON validation on canonical grade 60/70
        valid_payload = {"penetration_grade": "60/70"}
        # Must pass without ValidationError
        validate_commodity_payload(schema_version, valid_payload)

        # Schema rejects invalid grade
        invalid_payload = {"penetration_grade": "999/999"}
        with self.assertRaises(ValidationError):
            validate_commodity_payload(schema_version, invalid_payload)

    def test_matching_candidate_universe(self):
        """Verify the seeded data produces exactly 7 Suppliers and 3 Brokers using the real matching engine."""
        hero_rfq = RFQ.objects.filter(notes__contains=HERO_RFQ_TAG).first()
        self.assertIsNotNone(hero_rfq, "Canonical Hero RFQ must exist.")
        self.assertEqual(hero_rfq.status, RFQStatus.PUBLISHED)
        self.assertEqual(hero_rfq.quantity, Decimal("500.000"))
        self.assertEqual(hero_rfq.specifications.get("penetration_grade"), "60/70")

        # Inspect pre-seeded matching run
        matching_run = MatchingRun.objects.filter(rfq=hero_rfq, audience=MatchingAudience.BUYER).first()
        self.assertIsNotNone(matching_run, "Hero RFQ must have an executed matching run.")

        candidates = list(matching_run.candidates.all())
        supplier_candidates = [c for c in candidates if c.lane == CandidateLane.POTENTIAL_SUPPLIER]
        broker_candidates = [c for c in candidates if c.lane == CandidateLane.BROKER_PATH]
        direct_supply_candidates = [c for c in candidates if c.lane == CandidateLane.DIRECT_SUPPLY]

        self.assertEqual(len(supplier_candidates), 7, "Matching must discover exactly 7 Supplier candidates.")
        self.assertEqual(len(broker_candidates), 3, "Matching must discover exactly 3 Broker candidates.")
        self.assertEqual(len(direct_supply_candidates), 0, "No pre-seeded supply listings in Direct Supply.")

        # Test on a freshly created Bitumen RFQ by Buyer to confirm result is generated purely by matching logic
        buyer_user = User.objects.get(email="buyer@demo.local")
        buyer_org = Organization.objects.get(name="Demo Buyer Corp")
        bitumen = CommodityDefinition.objects.get(code="bitumen")

        fresh_rfq = RFQService.create_draft(
            user=buyer_user,
            data={
                "commodity_id": bitumen.id,
                "schema_version_id": bitumen.active_schema_version.id,
                "specifications": {"penetration_grade": "60/70"},
                "quantity": Decimal("500.000"),
                "unit": "MT",
                "target_price": Decimal("380.00"),
                "currency": "USD",
                "payment_terms": "LC 30 Days",
                "incoterm": "FOB",
                "origin": "Iran",
                "destination": "Bandar Abbas",
                "delivery_window_start": hero_rfq.delivery_window_start,
                "delivery_window_end": hero_rfq.delivery_window_end,
                "visibility": RFQVisibility.PUBLIC,
                "notes": "Test ad-hoc buyer RFQ",
            },
            organization_hint=buyer_org.id,
        )
        fresh_rfq = RFQLifecycleService.publish(fresh_rfq.id, expected_version=fresh_rfq.version, actor=buyer_user)

        actor_scope = ActorScope(user=buyer_user, organization=buyer_org)
        fresh_run = MatchingRunService.execute_matching_run(
            rfq_id=fresh_rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=actor_scope,
        )

        fresh_suppliers = fresh_run.candidates.filter(lane=CandidateLane.POTENTIAL_SUPPLIER).count()
        fresh_brokers = fresh_run.candidates.filter(lane=CandidateLane.BROKER_PATH).count()

        self.assertEqual(fresh_suppliers, 7, "Fresh RFQ matching must also find 7 Suppliers.")
        self.assertEqual(fresh_brokers, 3, "Fresh RFQ matching must also find 3 Brokers.")

    def test_external_counterparty_stays_external(self):
        """Verify the external supplier is strictly an ExternalCounterparty without User/Organization."""
        ext_cp = ExternalCounterparty.objects.filter(company_name="Gulf Petrochemicals FZE").first()
        self.assertIsNotNone(ext_cp, "Gulf Petrochemicals FZE must exist as ExternalCounterparty.")
        self.assertEqual(ext_cp.contact_name, "Tariq Al-Mansoor")
        self.assertEqual(ext_cp.email, "tariq@gulfpetro.demo.ae")

        # Enforce that no platform User or Organization exists for the external counterparty
        self.assertFalse(
            User.objects.filter(email=ext_cp.email).exists(),
            "External counterparty must NOT have a platform User record.",
        )
        self.assertFalse(
            Organization.objects.filter(name=ext_cp.company_name).exists(),
            "External counterparty must NOT have an Organization record.",
        )
        self.assertFalse(
            OrganizationMembership.objects.filter(organization__name=ext_cp.company_name).exists()
        )

    def test_opportunity_prerequisites_and_lifecycle(self):
        """Verify Opportunity OPP-2026-000124 semantics, broker referral attribution, and qualification."""
        opp = Opportunity.objects.filter(identifier=HERO_OPP_IDENTIFIER).first()
        self.assertIsNotNone(opp, f"Opportunity {HERO_OPP_IDENTIFIER} must exist.")

        self.assertEqual(opp.direction, OpportunityDirection.SUPPLY)
        self.assertEqual(opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(opp.broker.name, "Demo Brokerage")
        self.assertIsNotNone(opp.external_counterparty)
        self.assertEqual(opp.external_counterparty.company_name, "Gulf Petrochemicals FZE")
        self.assertIsNone(opp.organization, "External supply must have null organization.")
        self.assertEqual(opp.commodity.code, "bitumen")
        self.assertEqual(opp.specifications.get("penetration_grade"), "60/70")
        self.assertEqual(opp.quantity, Decimal("500.000"))
        self.assertEqual(opp.status, OpportunityStatus.CAPTURED)

        # Test operator qualification flow through domain service
        operator = User.objects.get(email="operator@demo.local")
        record_contact_attempt(
            opp.id,
            type=ContactAttemptType.CALL,
            notes="Contacted Tariq at Gulf Petrochemicals FZE regarding 500 MT Bitumen 60/70 quote.",
            actor=operator,
        )
        opp = mark_opportunity_contacted(opp.id, expected_version=opp.version, actor=operator)
        self.assertEqual(opp.status, OpportunityStatus.CONTACTED)

        opp = qualify_opportunity(opp.id, expected_version=opp.version, actor=operator)
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)

        # Verify that qualified opportunity allows Operator to submit external offer on behalf
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        offer, version = submit_operator_external_offer(
            actor=operator,
            rfq=hero_rfq,
            opportunity=opp,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("375.00"),
            currency="USD",
            payment_terms="LC 30 Days",
            delivery_terms="FOB Port Terminal",
            incoterm="FOB",
            delivery_start=hero_rfq.delivery_window_start,
            delivery_end=hero_rfq.delivery_window_end,
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.assertIsNotNone(offer)
        self.assertEqual(offer.offeror_role, OfferorRole.SUPPLIER)
        self.assertEqual(offer.external_counterparty, opp.external_counterparty)
        self.assertEqual(version.unit_price, Decimal("375.00"))

    def test_determinism(self):
        """Verify deterministic logical identities and metadata."""
        opp = Opportunity.objects.filter(identifier=HERO_OPP_IDENTIFIER).first()
        self.assertIsNotNone(opp)
        self.assertEqual(opp.identifier, "OPP-2026-000124")
        self.assertIn("[OPP-2026-00124]", opp.notes)

        # Check candidate ordering determinism in matching run
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        run = MatchingRun.objects.filter(rfq=hero_rfq, audience=MatchingAudience.BUYER).first()
        ranked_candidates = list(run.candidates.filter(lane=CandidateLane.POTENTIAL_SUPPLIER).order_by("rank"))
        self.assertEqual(len(ranked_candidates), 7)
        self.assertIsNotNone(ranked_candidates[0].ranking_score)

    def test_idempotency(self):
        """Verify repeated seed execution does not duplicate entities or corrupt state."""
        rfq_count_before = RFQ.objects.count()
        opp_count_before = Opportunity.objects.count()
        org_count_before = Organization.objects.count()
        runs_count_before = MatchingRun.objects.count()

        # Execute second time
        second_out = io.StringIO()
        second_summary = seed_hero_scenario(stdout=second_out)

        self.assertEqual(RFQ.objects.count(), rfq_count_before)
        self.assertEqual(Opportunity.objects.count(), opp_count_before)
        self.assertEqual(Organization.objects.count(), org_count_before)
        self.assertEqual(MatchingRun.objects.count(), runs_count_before)
        self.assertEqual(second_summary["matching_suppliers_count"], 7)
        self.assertEqual(second_summary["matching_brokers_count"], 3)

    def test_boundary_invariants(self):
        """Verify T1302 does not create a fake completed Hero lifecycle."""
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)

        # Hero RFQ must NOT have pre-seeded offers
        self.assertEqual(Offer.objects.filter(rfq=hero_rfq).count(), 0)

        # Hero RFQ must NOT have pre-seeded deals
        self.assertEqual(Deal.objects.filter(rfq=hero_rfq).count(), 0)

        # No Execution record associated with Hero RFQ
        self.assertEqual(Execution.objects.filter(deal__rfq=hero_rfq).count(), 0)

        # Hero RFQ status must be PUBLISHED, not AWARDED or CLOSED
        self.assertEqual(hero_rfq.status, RFQStatus.PUBLISHED)
