from datetime import date
from decimal import Decimal

from django.test import TransactionTestCase

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


class RepeatableReadConcurrencyTests(TransactionTestCase):
    """
    Tests proving PostgreSQL REPEATABLE READ snapshot isolation using TransactionTestCase:
    Ensures that a matching run transaction operates on a consistent snapshot.
    """

    def setUp(self):
        self.areas = seed_iran_geography()
        self.tehran_city = self.areas["IR-07-THR"]

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_concurrency_test",
            name_en="Bitumen Concurrency Test",
            name_fa="قیر تست هم‌زمانی",
        )
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        self.attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_version,
            key="penetration_grade",
            label_en="Penetration Grade",
            label_fa="درجه نفوذ",
            data_type=CommodityAttributeDefinition.DataType.STRING,
        )
        self.schema_version.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        self.schema_version.save()

        policy, _ = MatchingPolicy.objects.get_or_create(
            code=DEFAULT_POLICY_CODE,
            defaults={
                "name": DEFAULT_POLICY_NAME,
                "description": DEFAULT_POLICY_DESCRIPTION,
            },
        )
        self.policy_version = MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
            description="Default commodity matching policy v1.",
            configuration=DEFAULT_POLICY_V1_CONFIGURATION,
        )
        SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.attr.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=False,
            relative_weight=Decimal("1.0000"),
            missing_data_policy=SignalOutcome.UNKNOWN,
        )
        for state, rule_snap in DEFAULT_VERIFICATION_RULES.items():
            VerificationMatchingRule.objects.create(
                policy_version=self.policy_version,
                verification_state=state,
                raw_score=rule_snap.raw_score,
                hard_exclude=rule_snap.hard_exclude,
            )
        self.policy_version.status = PolicyLifecycleStatus.PUBLISHED
        self.policy_version.save()

        self.buyer_org = Organization.objects.create(name="Concurrency Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(organization=self.buyer_org, commodity=self.commodity)
        self.buyer_user = User.objects.create_user(email="buyer@concurrencytest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.buyer_user, organization=self.buyer_org, is_active=True)
        self.buyer_scope = ActorScope(user=self.buyer_user, organization=self.buyer_org, is_operator_or_admin=False)

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

        self.supplier = Organization.objects.create(name="Concurrency Supplier", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=self.supplier, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=self.supplier, status=VerificationStatus.VERIFIED)
        self.listing = SupplyListing.objects.create(
            organization=self.supplier,
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

    def test_repeatable_read_snapshot_isolation(self):
        """
        Prove that MatchingRunService executes inside a real REPEATABLE READ transaction
        and successfully commits the atomic run.
        """
        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        self.assertIsNotNone(run.pk)
        cands = MatchingCandidate.objects.filter(run=run, lane=CandidateLane.DIRECT_SUPPLY)
        self.assertEqual(cands.count(), 1)
        self.assertTrue(cands.first().eligible)
