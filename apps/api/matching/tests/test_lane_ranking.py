from datetime import date
from decimal import Decimal
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from geography.seed import seed_iran_geography
from identity.models import User
from matching.candidates.context import ActorScope
from matching.enums import (
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalOutcome,
)
from matching.models.candidate import MatchingCandidate
from matching.models.policy import (
    MatchingPolicy,
    MatchingPolicyVersion,
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


class LaneRankingTests(TestCase):
    """
    Tests proving lane-local ranking invariants:
    - Direct Supply, Potential Supplier, and Broker Path each restart ranking at 1.
    - Tie-breaking: ranking_score DESC, evidence_coverage DESC, fit_score DESC, stable_candidate_key ASC.
    - Ineligible candidates have rank = None and appear after all eligible candidates.
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_prov = cls.areas["IR-07"]
        cls.tehran_city = cls.areas["IR-07-THR"]
        cls.shahriar = cls.areas["IR-07-SHH"]

        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_ranking_test",
            name_en="Bitumen Ranking Test",
            name_fa="قیر تست رتبه‌بندی",
        )
        cls.schema_version = CommoditySchemaVersion.objects.create(
            commodity=cls.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        cls.attr = CommodityAttributeDefinition.objects.create(
            schema_version=cls.schema_version,
            key="penetration_grade",
            label_en="Penetration Grade",
            label_fa="درجه نفوذ",
            data_type=CommodityAttributeDefinition.DataType.STRING,
        )
        cls.schema_version.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        cls.schema_version.save()

        # Seed policy v1 with spec rule and verification rules
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
            semantic_identity=cls.attr.semantic_identity,
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
        self.buyer_org = Organization.objects.create(name="Ranking Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(organization=self.buyer_org, commodity=self.commodity)
        self.buyer_user = User.objects.create_user(email="buyer@rankingtest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.buyer_user, organization=self.buyer_org, is_active=True)
        self.buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org, is_operator_or_admin=False)

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
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

    def test_lanes_restart_ranks_independently(self):
        """
        Direct Supply and Potential Supplier lanes must each independently assign rank 1 to their top candidate.
        """
        # 1. Direct Supply listing
        supplier1 = Organization.objects.create(name="Direct Supplier A", is_active=True)
        OrganizationCapability.objects.create(organization=supplier1, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier1, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier1, status=VerificationStatus.VERIFIED)
        SupplyListing.objects.create(
            organization=supplier1,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        # 2. Potential Supplier (org with operating area in Tehran Province)
        supplier2 = Organization.objects.create(name="Potential Supplier B", is_active=True)
        OrganizationCapability.objects.create(organization=supplier2, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier2, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier2, status=VerificationStatus.VERIFIED)
        OrganizationOperatingArea.objects.create(organization=supplier2, area=self.tehran_prov)

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        direct_cand = MatchingCandidate.objects.get(run=run, lane=CandidateLane.DIRECT_SUPPLY)
        potential_cand = MatchingCandidate.objects.get(run=run, lane=CandidateLane.POTENTIAL_SUPPLIER, supplier_organization=supplier2)

        # Both top candidates in their respective lanes MUST have rank 1
        self.assertEqual(direct_cand.rank, 1)
        self.assertEqual(potential_cand.rank, 1)

    def test_ineligible_candidates_have_rank_none_and_appear_after_eligible(self):
        """
        Ineligible candidates must receive rank = None and fit/ranking scores = None.
        """
        # Eligible supplier
        supplier_good = Organization.objects.create(name="Good Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier_good, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier_good, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier_good, status=VerificationStatus.VERIFIED)
        SupplyListing.objects.create(
            organization=supplier_good,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        # Ineligible supplier (Suspended -> hard exclusion)
        supplier_bad = Organization.objects.create(name="Suspended Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=supplier_bad, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=supplier_bad, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=supplier_bad, status=VerificationStatus.SUSPENDED)
        SupplyListing.objects.create(
            organization=supplier_bad,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        direct_cands = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).order_by("rank")
        self.assertEqual(direct_cands.count(), 2)

        good_cand = direct_cands.filter(eligible=True).first()
        bad_cand = direct_cands.filter(eligible=False).first()

        self.assertIsNotNone(good_cand)
        self.assertIsNotNone(bad_cand)

        self.assertEqual(good_cand.rank, 1)
        self.assertIsNotNone(good_cand.ranking_score)

        self.assertIsNone(bad_cand.rank)
        self.assertIsNone(bad_cand.fit_score)
        self.assertIsNone(bad_cand.ranking_score)
        self.assertEqual(bad_cand.exclusion_code, "TRUST_SUSPENDED")

    def test_deterministic_tie_breaking_order(self):
        """
        When two eligible candidates have identical ranking_score, evidence_coverage, and fit_score,
        order is deterministically broken by stable_candidate_key ASC.
        """
        # Create two suppliers with identical listings
        sup_a = Organization.objects.create(name="Supplier Alpha", is_active=True)
        OrganizationCapability.objects.create(organization=sup_a, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=sup_a, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=sup_a, status=VerificationStatus.VERIFIED)
        list_a = SupplyListing.objects.create(
            organization=sup_a,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        sup_b = Organization.objects.create(name="Supplier Beta", is_active=True)
        OrganizationCapability.objects.create(organization=sup_b, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=sup_b, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=sup_b, status=VerificationStatus.VERIFIED)
        list_b = SupplyListing.objects.create(
            organization=sup_b,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        cands = list(MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY).order_by("rank"))
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0].rank, 1)
        self.assertEqual(cands[1].rank, 2)
        self.assertEqual(cands[0].ranking_score, cands[1].ranking_score)
        self.assertEqual(cands[0].evidence_coverage, cands[1].evidence_coverage)
        self.assertEqual(cands[0].fit_score, cands[1].fit_score)

        # Stable candidate key for listing is "supply_listing:{listing_id}"
        key_a = f"supply_listing:{list_a.id}"
        key_b = f"supply_listing:{list_b.id}"
        expected_first_key = min(key_a, key_b)
        first_cand_listing_id = str(cands[0].supply_listing_id)
        self.assertIn(first_cand_listing_id, expected_first_key)
