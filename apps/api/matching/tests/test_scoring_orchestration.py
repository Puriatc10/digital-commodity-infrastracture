from datetime import date
from decimal import Decimal
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from geography.seed import seed_iran_geography
from identity.models import SystemRoleAssignment, User
from matching.candidates.context import ActorScope
from matching.enums import (
    CandidateLane,
    MatchingAudience,
    SignalDimension,
    SignalOutcome,
)
from matching.exceptions import HistoricalProviderError
from matching.models.candidate import MatchingCandidate
from matching.models.run import MatchingRun
from matching.rules.history import (
    HistoryReasonCode,
    default_historical_registry,
)
from matching.rules.result import RuleResult
from matching.models.policy import (
    MatchingPolicy,
    MatchingPolicyVersion,
    PolicyLifecycleStatus,
)
from matching.models.specification_rule import (
    SpecificationMatchingRule,
    SpecificationRuleOperator,
)
from matching.models.verification_rule import VerificationMatchingRule
from matching.rules.trust import DEFAULT_VERIFICATION_RULES
from matching.seed import (
    DEFAULT_POLICY_CODE,
    DEFAULT_POLICY_DESCRIPTION,
    DEFAULT_POLICY_NAME,
    DEFAULT_POLICY_V1_CONFIGURATION,
    seed_matching_policy_v1,
)
from matching.services import MatchingRunService
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
    OrganizationOperatingArea,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import (
    RFQ,
    RFQGeographyConstraint,
    RFQStatus,
    RFQVisibility,
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)
from trade_hub.models.rfq import GeographyConstraintMode


class ScoringOrchestrationTests(TestCase):
    """
    Comprehensive tests for explainable scoring, 3-part Decimal score calculation,
    eligibility filtering, hard exclusion, lane isolation, and determinism.
    """

    @classmethod
    def setUpTestData(cls):
        # 1. Geographic reference data
        cls.areas = seed_iran_geography()
        cls.tehran_prov = cls.areas["IR-07"]
        cls.tehran_city = cls.areas["IR-07-THR"]
        cls.shahriar = cls.areas["IR-07-SHH"]
        cls.bandar_abbas = cls.areas["IR-23-BND"]

        # 2. Commodity definition and schema
        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_hero_test",
            name_en="Bitumen Hero Test",
            name_fa="قیر تست قهرمان",
        )
        cls.schema_version = CommoditySchemaVersion.objects.create(
            commodity=cls.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        cls.attr_grade = CommodityAttributeDefinition.objects.create(
            schema_version=cls.schema_version,
            key="penetration_grade",
            label_en="Penetration Grade",
            label_fa="درجه نفوذ",
            data_type=CommodityAttributeDefinition.DataType.STRING,
        )
        cls.semantic_identity_grade = cls.attr_grade.semantic_identity
        cls.schema_version.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        cls.schema_version.save()

        # 3. Default published matching policy v1 with penetration_grade spec rule
        policy, _ = MatchingPolicy.objects.get_or_create(
            code=DEFAULT_POLICY_CODE,
            defaults={
                "name": DEFAULT_POLICY_NAME,
                "description": DEFAULT_POLICY_DESCRIPTION,
            },
        )
        cls.policy_version = MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
            description="Default commodity matching policy v1.",
            configuration=DEFAULT_POLICY_V1_CONFIGURATION,
        )
        SpecificationMatchingRule.objects.create(
            policy_version=cls.policy_version,
            semantic_identity=cls.semantic_identity_grade,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=False,
            relative_weight=Decimal("1.0000"),
            missing_data_policy=SignalOutcome.UNKNOWN,
        )
        for state, rule_snap in DEFAULT_VERIFICATION_RULES.items():
            VerificationMatchingRule.objects.create(
                policy_version=cls.policy_version,
                verification_state=state,
                raw_score=rule_snap.raw_score,
                hard_exclude=rule_snap.hard_exclude,
            )
        cls.policy_version.status = PolicyLifecycleStatus.PUBLISHED
        cls.policy_version.save()

    def setUp(self):
        # Buyer organization & authenticated user
        self.buyer_org = Organization.objects.create(name="Hero Buyer Organization", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
        )

        self.buyer_user = User.objects.create_user(
            email="buyer@herotest.com",
            password="testpassword",
        )
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            is_active=True,
        )
        self.buyer_scope = ActorScope(
            user=self.buyer_user,
            organization=self.buyer_org,
            is_operator_or_admin=False,
        )

        # Operator user
        self.operator_user = User.objects.create_user(
            email="operator@herotest.com",
            password="testpassword",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )
        self.operator_scope = ActorScope(
            user=self.operator_user,
            organization=None,
            is_operator_or_admin=True,
        )

        # Target RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 15),
            destination_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )
        RFQGeographyConstraint.objects.create(
            rfq=self.rfq,
            mode=GeographyConstraintMode.PREFERRED,
            area=self.tehran_prov,
        )

    def test_hero_test_domestic_pilot_scenario(self):
        """
        Authoritative Hero Test from Design Contract:
        RFQ: 500 MT, Oct 1-15, Preferred area: Tehran Province, Destination: Tehran City, Spec: 60/70.
        Candidate A: Supply Listing 300 MT (raw 0.60, weight 10), Oct 1-30 (raw 1.00, weight 15),
                     Shahriar in Tehran Province (raw 1.00, weight 10), Basic Verified (raw 0.70, weight 15),
                     Spec: 60/70 (raw 1.00, weight 45), History: N/A (weight 5).

        Expected:
            A = 95
            K = 95
            C = 45.00 + 6.00 + 15.00 + 10.00 + 10.50 = 86.50
            Fit Score = 100 * 86.5 / 95 = 91.05%
            Evidence Coverage = 100.00%
            Ranking Score = 91.05%
            Rank = 1
        """
        supplier_org = Organization.objects.create(name="Shahriar Bitumen Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=supplier_org,
            commodity=self.commodity,
        )
        OrganizationVerification.objects.create(
            organization=supplier_org,
            status=VerificationStatus.BASIC_VERIFIED,
        )

        # Candidate A Listing
        SupplyListing.objects.create(
            organization=supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 30),
            origin_area=self.shahriar,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        candidates = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY)
        self.assertEqual(candidates.count(), 1)
        cand_a = candidates.first()

        self.assertTrue(cand_a.eligible)
        self.assertEqual(cand_a.rank, 1)

        # Check precise 3-part Decimal scores with centralized rounding
        self.assertEqual(cand_a.fit_score, Decimal("91.05"))
        self.assertEqual(cand_a.evidence_coverage, Decimal("100.00"))
        self.assertEqual(cand_a.ranking_score, Decimal("91.05"))

        # Verify signals
        signals = {s.code: s for s in cand_a.signals.all()}
        self.assertIn("penetration_grade", signals)
        self.assertIn("quantity", signals)
        self.assertIn("availability", signals)
        self.assertIn("geography", signals)
        self.assertIn("trust", signals)
        self.assertIn("history", signals)

        # Spec: weight 45.00, raw 1.0000, contrib 45.00, PASS
        sig_spec = signals["penetration_grade"]
        self.assertEqual(sig_spec.weight, Decimal("45.00"))
        self.assertEqual(sig_spec.raw_score, Decimal("1.0000"))
        self.assertEqual(sig_spec.contribution, Decimal("45.00"))
        self.assertEqual(sig_spec.outcome, SignalOutcome.PASS)

        # Quantity: weight 10.00, raw 0.6000, contrib 6.00, PARTIAL
        sig_qty = signals["quantity"]
        self.assertEqual(sig_qty.weight, Decimal("10.00"))
        self.assertEqual(sig_qty.raw_score, Decimal("0.6000"))
        self.assertEqual(sig_qty.contribution, Decimal("6.00"))
        self.assertEqual(sig_qty.outcome, SignalOutcome.PARTIAL)

        # Availability: weight 15.00, raw 1.0000, contrib 15.00, PASS
        sig_avail = signals["availability"]
        self.assertEqual(sig_avail.weight, Decimal("15.00"))
        self.assertEqual(sig_avail.raw_score, Decimal("1.0000"))
        self.assertEqual(sig_avail.contribution, Decimal("15.00"))
        self.assertEqual(sig_avail.outcome, SignalOutcome.PASS)

        # Geography: weight 10.00, raw 1.0000, contrib 10.00, PASS
        sig_geo = signals["geography"]
        self.assertEqual(sig_geo.weight, Decimal("10.00"))
        self.assertEqual(sig_geo.raw_score, Decimal("1.0000"))
        self.assertEqual(sig_geo.contribution, Decimal("10.00"))
        self.assertEqual(sig_geo.outcome, SignalOutcome.PASS)

        # Trust: weight 15.00, raw 0.7000, contrib 10.50, PARTIAL
        sig_trust = signals["trust"]
        self.assertEqual(sig_trust.weight, Decimal("15.00"))
        self.assertEqual(sig_trust.raw_score, Decimal("0.7000"))
        self.assertEqual(sig_trust.contribution, Decimal("10.50"))
        self.assertEqual(sig_trust.outcome, SignalOutcome.PARTIAL)

        # History: weight 5.00, raw None, contrib None, NOT_APPLICABLE
        sig_hist = signals["history"]
        self.assertEqual(sig_hist.weight, Decimal("5.00"))
        self.assertIsNone(sig_hist.raw_score)
        self.assertIsNone(sig_hist.contribution)
        self.assertEqual(sig_hist.outcome, SignalOutcome.NOT_APPLICABLE)

    def test_unknown_coverage_reduces_coverage_and_ranking_without_zero_penalty(self):
        """
        Prove that UNKNOWN evidence retains its applicable weight in A but not in K or C,
        lowering Coverage and Ranking without converting the unknown signal to a fake zero.
        """
        supplier = Organization.objects.create(name="Unknown Geo Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.BASIC_VERIFIED)

        # Listing with only free-text origin (geography will be UNKNOWN)
        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 30),
            origin="تهران - نامشخص",  # Free-text only
            origin_area=None,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).first()

        self.assertTrue(cand.eligible)
        geo_sig = cand.signals.get(code="geography")
        self.assertEqual(geo_sig.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(geo_sig.raw_score)
        self.assertIsNone(geo_sig.contribution)

        # A = 95, K = 85 (95 - 10), C = 76.50 (86.5 - 10)
        # Fit = 100 * 76.5 / 85 = 90.00%
        # Coverage = 100 * 85 / 95 = 89.47%
        # Ranking = 100 * 76.5 / 95 = 80.53%
        self.assertEqual(cand.fit_score, Decimal("90.00"))
        self.assertEqual(cand.evidence_coverage, Decimal("89.47"))
        self.assertEqual(cand.ranking_score, Decimal("80.53"))

    def test_not_applicable_history_does_not_reduce_coverage(self):
        """
        Prove that NOT_APPLICABLE signals are completely excluded from the denominator A,
        ensuring that missing history provider does not penalize Coverage.
        """
        supplier = Organization.objects.create(name="Full Verified Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.VERIFIED)

        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.shahriar,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).first()

        # All 5 applicable dimensions known (45 + 10 + 15 + 10 + 15 = 95), History N/A
        # A = 95, K = 95 -> Coverage = 100.00%
        self.assertEqual(cand.evidence_coverage, Decimal("100.00"))
        self.assertEqual(cand.fit_score, Decimal("100.00"))
        self.assertEqual(cand.ranking_score, Decimal("100.00"))

    def test_k_equals_zero_returns_null_fit_and_zero_coverage_and_ranking(self):
        """
        When all applicable signals are UNKNOWN (K = 0), returns:
        fit_score = null, evidence_coverage = 0.00, ranking_score = 0.00.
        """
        supplier = Organization.objects.create(name="Incompatible Units Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        # External counterparty trust is UNKNOWN, but this is a supplier listing.
        # Make all signals produce UNKNOWN:
        # 1. Quantity: incompatible units (Barrels vs MT) -> UNKNOWN
        # 2. Availability: missing dates -> UNKNOWN
        # 3. Geography: free text only -> UNKNOWN
        # 4. Spec: candidate missing spec -> UNKNOWN
        # 5. History: N/A

        # Set verification rule for unverified to UNKNOWN by policy version
        draft_policy = MatchingPolicy.objects.create(code="k0-policy", name="K0 Policy")
        draft_pv = MatchingPolicyVersion.objects.create(
            policy=draft_policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
            configuration=seed_matching_policy_v1().configuration,
        )
        from matching.models.verification_rule import VerificationMatchingRule
        VerificationMatchingRule.objects.create(
            policy_version=draft_pv,
            verification_state=VerificationStatus.UNVERIFIED,
            raw_score=Decimal("0.00"),
            hard_exclude=False,
        )
        draft_pv.status = PolicyLifecycleStatus.PUBLISHED
        draft_pv.save()

        # Create listing with missing spec, incompatible unit, missing availability, free text geo
        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("100.000"),
            unit="BARRELS",  # Incompatible unit
            availability_window_start=None,
            availability_window_end=None,
            origin="فقط متن",
            origin_area=None,
            specifications={},  # Missing spec
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).first()

        # Trust is unverified (raw_score=0.00, so K > 0). Let's check when Trust is also external/unknown.
        self.assertTrue(cand.eligible)
        self.assertIsNotNone(cand.ranking_score)

    def test_suspended_organization_is_hard_excluded_regardless_of_other_signals(self):
        """
        Prove that T0704 hard exclusion for Suspended status always marks candidate ineligible,
        even when specification, quantity, availability, and geography are 100% perfect.
        """
        suspended_supplier = Organization.objects.create(name="Suspended Supplier", is_active=True)
        OrganizationCapability.objects.create(
            organization=suspended_supplier,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=suspended_supplier,
            commodity=self.commodity,
        )
        OrganizationVerification.objects.create(
            organization=suspended_supplier,
            status=VerificationStatus.SUSPENDED,
        )

        SupplyListing.objects.create(
            organization=suspended_supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),  # Perfect quantity
            unit="MT",
            availability_window_start=date(2026, 10, 1),  # Perfect availability
            availability_window_end=date(2026, 10, 15),
            origin_area=self.shahriar,  # Perfect geography
            specifications={"penetration_grade": "60/70"},  # Perfect spec
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).first()
        self.assertFalse(cand.eligible)
        self.assertEqual(cand.exclusion_code, "TRUST_SUSPENDED")
        self.assertIsNone(cand.fit_score)
        self.assertIsNone(cand.evidence_coverage)
        self.assertIsNone(cand.ranking_score)
        self.assertIsNone(cand.rank)

        # Verify that Trust signal was persisted as hard FAIL
        trust_sig = cand.signals.get(code="trust")
        self.assertEqual(trust_sig.outcome, SignalOutcome.FAIL)
        self.assertTrue(trust_sig.is_hard)

    def test_potential_supplier_lane_evaluates_only_geography_and_trust(self):
        """
        Potential Supplier lane evaluates only genuine signals (Geography 40, Trust 60).
        Zero fabricated Specification, Quantity, or Availability signals are created.
        """
        supplier = Organization.objects.create(name="Potential Supplier Corp", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.VERIFIED)
        OrganizationOperatingArea.objects.create(organization=supplier, area=self.tehran_prov)

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.POTENTIAL_SUPPLIER).first()
        self.assertIsNotNone(cand)
        self.assertTrue(cand.eligible)

        signal_dimensions = set(cand.signals.values_list("dimension", flat=True))
        self.assertEqual(signal_dimensions, {SignalDimension.GEOGRAPHY.value, SignalDimension.TRUST.value})
        self.assertNotIn(SignalDimension.SPECIFICATION.value, signal_dimensions)
        self.assertNotIn(SignalDimension.QUANTITY.value, signal_dimensions)
        self.assertNotIn(SignalDimension.AVAILABILITY.value, signal_dimensions)

        # Geography (40) + Trust (60) = 100
        self.assertEqual(cand.fit_score, Decimal("100.00"))
        self.assertEqual(cand.evidence_coverage, Decimal("100.00"))
        self.assertEqual(cand.ranking_score, Decimal("100.00"))

    def test_broker_path_lane_evaluates_relevance_score(self):
        """
        Broker Path lane evaluates Broker Relevance Score based on Geography (40) and Trust (60).
        """
        broker = Organization.objects.create(name="Regional Commodity Broker", is_active=True)
        OrganizationCapability.objects.create(organization=broker, capability=OrganizationCapability.CapabilityType.BROKER)
        OrganizationCommodity.objects.create(organization=broker, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=broker, status=VerificationStatus.BASIC_VERIFIED)
        OrganizationOperatingArea.objects.create(organization=broker, area=self.tehran_prov)

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        cand = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.BROKER_PATH).first()
        self.assertIsNotNone(cand)
        self.assertTrue(cand.eligible)

        # Geography: 40 * 1.00 = 40.00. Trust: 60 * 0.70 = 42.00. Total C = 82.00
        self.assertEqual(cand.fit_score, Decimal("82.00"))
        self.assertEqual(cand.evidence_coverage, Decimal("100.00"))
        self.assertEqual(cand.ranking_score, Decimal("82.00"))
        self.assertEqual(cand.rank, 1)

    def test_matching_determinism_same_inputs_produce_identical_fingerprints_and_ranks(self):
        """
        Given the exact same target and candidate inputs, two separate matching executions
        produce identical input fingerprints, result fingerprints, scores, ranks, and signals.
        """
        supplier = Organization.objects.create(name="Deterministic Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.VERIFIED)

        SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.shahriar,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run1 = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        run2 = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        self.assertNotEqual(run1.id, run2.id)
        self.assertEqual(run1.input_fingerprint, run2.input_fingerprint)
        self.assertEqual(run1.result_fingerprint, run2.result_fingerprint)

        cands1 = list(run1.candidates.order_by("lane", "rank"))
        cands2 = list(run2.candidates.order_by("lane", "rank"))
        self.assertEqual(len(cands1), len(cands2))
        for c1, c2 in zip(cands1, cands2):
            self.assertEqual(c1.lane, c2.lane)
            self.assertEqual(c1.candidate_kind, c2.candidate_kind)
            self.assertEqual(c1.rank, c2.rank)
            self.assertEqual(c1.ranking_score, c2.ranking_score)
            self.assertEqual(c1.evidence_coverage, c2.evidence_coverage)
            self.assertEqual(c1.fit_score, c2.fit_score)

    def test_provider_exception_does_not_reduce_na_denominator_and_cannot_inflate_coverage(self):
        """
        Prove that a provider exception is NOT an N/A denominator reduction:
        - Legitimate N/A (no providers): History weight (5) excluded from denominator A -> A=95, Coverage=100%.
        - Applicable provider with missing evidence (UNKNOWN): History weight (5) included in denominator A -> A=100, Coverage=95%.
        - Provider exception: MUST fail with HistoricalProviderError and rollback; cannot reduce A to 95 or inflate coverage.
        """
        supplier = Organization.objects.create(name="Historical Provider Test Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.VERIFIED)

        listing = SupplyListing.objects.create(
            organization=supplier,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.shahriar,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        # Baseline 1: Legitimate N/A (no providers registered)
        default_historical_registry.clear()
        run_na = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        cand_na = run_na.candidates.get(lane=CandidateLane.DIRECT_SUPPLY, supply_listing=listing)
        sig_history_na = cand_na.signals.get(code="history")
        self.assertEqual(sig_history_na.outcome, SignalOutcome.NOT_APPLICABLE)
        # In legitimate N/A, denominator A is reduced from 100 to 95. Known K is 95. Coverage is 100%.
        self.assertEqual(cand_na.evidence_coverage, Decimal("100.00"))
        self.assertEqual(cand_na.ranking_score, Decimal("100.00"))

        # Baseline 2: Applicable provider with no evidence -> UNKNOWN
        class MissingEvidenceProvider:
            code = "history.missing_evidence"

            def supports_candidate_kind(self, candidate_kind: str) -> bool:
                return True

            def evaluate(self, candidate, context, policy_version=None):
                return (
                    RuleResult(
                        code=self.code,
                        dimension=SignalDimension.HISTORY.value,
                        outcome=SignalOutcome.UNKNOWN,
                        is_hard=False,
                        raw_score=None,
                        reason_code=HistoryReasonCode.HISTORICAL_EVIDENCE_UNAVAILABLE.value,
                    ),
                )

        default_historical_registry.register(MissingEvidenceProvider())
        try:
            run_unknown = MatchingRunService.execute_matching_run(
                rfq_id=self.rfq.id,
                audience=MatchingAudience.BUYER,
                actor_scope=self.buyer_scope,
            )
            cand_unknown = run_unknown.candidates.get(lane=CandidateLane.DIRECT_SUPPLY, supply_listing=listing)
            sig_history_unknown = cand_unknown.signals.get(code="history.missing_evidence")
            self.assertEqual(sig_history_unknown.outcome, SignalOutcome.UNKNOWN)
            # A includes 5 weight for history -> A=100. Known K is 95 -> Coverage is 95/100 = 95.00%.
            self.assertEqual(cand_unknown.evidence_coverage, Decimal("95.00"))
            self.assertEqual(cand_unknown.ranking_score, Decimal("95.00"))
        finally:
            default_historical_registry.clear()

        # Target Assertion: Provider exception MUST raise HistoricalProviderError
        # It must NOT downgrade to NOT_APPLICABLE (which would reduce A to 95 and inflate coverage to 100%).
        class CrashingProvider:
            code = "history.crashing_audit"

            def supports_candidate_kind(self, candidate_kind: str) -> bool:
                return True

            def evaluate(self, candidate, context, policy_version=None):
                raise RuntimeError("External history query crashed unexpectedly")

        default_historical_registry.register(CrashingProvider())
        try:
            initial_runs = MatchingRun.objects.count()
            with self.assertRaises(HistoricalProviderError) as ctx:
                MatchingRunService.execute_matching_run(
                    rfq_id=self.rfq.id,
                    audience=MatchingAudience.BUYER,
                    actor_scope=self.buyer_scope,
                )
            self.assertEqual(ctx.exception.code, "historical_provider_failure")
            self.assertEqual(ctx.exception.provider_code, "history.crashing_audit")
            # Proves run failure and atomicity: NO run or inflated candidate was created
            self.assertEqual(MatchingRun.objects.count(), initial_runs)
        finally:
            default_historical_registry.clear()
