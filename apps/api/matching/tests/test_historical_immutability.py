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
from matching.models.run import MatchingRun
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
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import (
    RFQ,
    RFQStatus,
    RFQVisibility,
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


class HistoricalImmutabilityTests(TestCase):
    """
    Tests proving matching run historical immutability:
    A persisted MatchingRun and its candidates/signals represent an immutable historical snapshot.
    Subsequent mutations to RFQs, listings, organizations, verification statuses, policy versions,
    or commodity schemas NEVER alter the persisted run data.
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_city = cls.areas["IR-07-THR"]

        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_history_test",
            name_en="Bitumen History Test",
            name_fa="قیر تست تاریخچه",
        )
        cls.schema_v1 = CommoditySchemaVersion.objects.create(
            commodity=cls.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        cls.attr = CommodityAttributeDefinition.objects.create(
            schema_version=cls.schema_v1,
            key="penetration_grade",
            label_en="Penetration Grade",
            label_fa="درجه نفوذ",
            data_type=CommodityAttributeDefinition.DataType.STRING,
        )
        cls.schema_v1.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        cls.schema_v1.save()

        policy, _ = MatchingPolicy.objects.get_or_create(
            code=DEFAULT_POLICY_CODE,
            defaults={
                "name": DEFAULT_POLICY_NAME,
                "description": DEFAULT_POLICY_DESCRIPTION,
            },
        )
        cls.policy_v1 = MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
            description="Default commodity matching policy v1.",
            configuration=DEFAULT_POLICY_V1_CONFIGURATION,
        )
        SpecificationMatchingRule.objects.create(
            policy_version=cls.policy_v1,
            semantic_identity=cls.attr.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=False,
            relative_weight=Decimal("1.0000"),
            missing_data_policy=SignalOutcome.UNKNOWN,
        )
        for state, rule_snap in DEFAULT_VERIFICATION_RULES.items():
            VerificationMatchingRule.objects.create(
                policy_version=cls.policy_v1,
                verification_state=state,
                raw_score=rule_snap.raw_score,
                hard_exclude=rule_snap.hard_exclude,
            )
        cls.policy_v1.status = PolicyLifecycleStatus.PUBLISHED
        cls.policy_v1.save()

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Immutability Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(organization=self.buyer_org, commodity=self.commodity)
        self.buyer_user = User.objects.create_user(email="buyer@historytest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.buyer_user, organization=self.buyer_org, is_active=True)
        self.buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org, is_operator_or_admin=False)

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            unit="MT",
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 15),
            destination_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        self.supplier = Organization.objects.create(name="Immutability Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=self.supplier, commodity=self.commodity)
        self.verification = OrganizationVerification.objects.create(organization=self.supplier, status=VerificationStatus.VERIFIED)
        self.listing = SupplyListing.objects.create(
            organization=self.supplier,
            commodity=self.commodity,
            schema_version=self.schema_v1,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

    def test_run_and_candidate_immutable_across_source_mutations(self):
        """
        Execute matching run, then mutate RFQ, Listing, Verification, and Policy.
        Verify that past MatchingRun, candidate score/rank, and fingerprints remain identical.
        """
        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        cand = MatchingCandidate.objects.get(run=run, lane=CandidateLane.DIRECT_SUPPLY)
        orig_run_fingerprint = run.result_fingerprint
        orig_cand_fit_score = cand.fit_score
        orig_cand_rank = cand.rank
        orig_cand_eligible = cand.eligible

        # 1. Mutate RFQ status to CLOSED (simulating closed RFQ after matching)
        RFQ.objects.filter(pk=self.rfq.pk).update(quantity=Decimal("9999.000"), specifications={"penetration_grade": "40/50"})

        # 2. Mutate Supply Listing
        SupplyListing.objects.filter(pk=self.listing.pk).update(quantity=Decimal("1.000"), status=SupplyListingStatus.CLOSED)

        # 3. Mutate Organization Verification to SUSPENDED
        self.verification.status = VerificationStatus.SUSPENDED
        self.verification.save()

        # Reload from DB and verify complete historical preservation
        reloaded_run = MatchingRun.objects.get(pk=run.pk)
        reloaded_cand = MatchingCandidate.objects.get(pk=cand.pk)

        self.assertEqual(reloaded_run.result_fingerprint, orig_run_fingerprint)
        self.assertEqual(reloaded_run.target_snapshot["quantity"], "500.000")
        self.assertEqual(reloaded_run.target_snapshot["specifications"], {"penetration_grade": "60/70"})

        self.assertEqual(reloaded_cand.fit_score, orig_cand_fit_score)
        self.assertEqual(reloaded_cand.rank, orig_cand_rank)
        self.assertEqual(reloaded_cand.eligible, orig_cand_eligible)
        self.assertEqual(reloaded_cand.candidate_snapshot["quantity"], "500.000")
        self.assertEqual(reloaded_cand.candidate_snapshot["verification_status"], "verified")
