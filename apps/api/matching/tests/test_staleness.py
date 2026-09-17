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
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalOutcome,
)
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
from trade_hub.models import (
    RFQ,
    RFQStatus,
    RFQVisibility,
)


class MatchingStalenessTests(TestCase):
    """
    Tests proving matching run staleness detection when target RFQ version progresses.
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_city = cls.areas["IR-07-THR"]

        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_staleness_test",
            name_en="Bitumen Staleness Test",
            name_fa="قیر تست کهنگی",
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
        self.buyer_org = Organization.objects.create(name="Staleness Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(organization=self.buyer_org, commodity=self.commodity)
        self.buyer_user = User.objects.create_user(email="buyer@stalenesstest.com", password="testpassword")
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

    def test_rfq_version_progression_marks_prior_run_stale(self):
        """When an RFQ version advances, previous runs are recognized as stale."""
        # Initial run at RFQ version 1
        self.assertEqual(self.rfq.version, 1)
        run_v1 = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        self.assertEqual(run_v1.rfq_version, 1)
        self.assertFalse(run_v1.is_stale)

        # Increment RFQ version to 2
        RFQ.objects.filter(pk=self.rfq.pk).update(version=2)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.version, 2)

        # Reload run_v1: must now be marked stale
        reloaded_v1 = MatchingRun.objects.get(pk=run_v1.pk)
        self.assertTrue(reloaded_v1.is_stale)

        # Execute new matching run at RFQ version 2
        run_v2 = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )
        self.assertEqual(run_v2.rfq_version, 2)
        self.assertFalse(run_v2.is_stale)
