from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
from matching.exceptions import HistoricalProviderError
from matching.models.candidate import MatchingCandidate
from matching.models.policy import (
    MatchingPolicy,
    MatchingPolicyVersion,
)
from matching.rules.history import default_historical_registry
from matching.models.run import MatchingRun
from matching.models.signal import MatchingSignal
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


class PersistenceAtomicityTests(TestCase):
    """
    Tests proving matching run atomicity:
    - Entire matching result (run, candidates, signals) commits atomically.
    - Any failure during candidate or signal persistence rolls back completely,
      leaving 0 partial records in the database.
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_prov = cls.areas["IR-07"]
        cls.tehran_city = cls.areas["IR-07-THR"]

        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_atomicity_test",
            name_en="Bitumen Atomicity Test",
            name_fa="قیر تست اتمیک",
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
        self.buyer_org = Organization.objects.create(name="Atomicity Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCommodity.objects.create(organization=self.buyer_org, commodity=self.commodity)
        self.buyer_user = User.objects.create_user(email="buyer@atomicitytest.com", password="testpassword")
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

        supplier = Organization.objects.create(name="Atomicity Supplier", is_active=True)
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
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

    def test_successful_run_persists_run_candidates_and_signals_cohesively(self):
        """A normal matching run atomically creates MatchingRun, MatchingCandidate, and MatchingSignals."""
        initial_runs = MatchingRun.objects.count()
        initial_candidates = MatchingCandidate.objects.count()
        initial_signals = MatchingSignal.objects.count()

        run = MatchingRunService.execute_matching_run(
            rfq_id=self.rfq.id,
            audience=MatchingAudience.BUYER,
            actor_scope=self.buyer_scope,
        )

        self.assertIsNotNone(run.id)
        self.assertEqual(MatchingRun.objects.count(), initial_runs + 1)
        self.assertGreater(MatchingCandidate.objects.count(), initial_candidates)
        self.assertGreater(MatchingSignal.objects.count(), initial_signals)

    def test_failure_during_signal_persistence_rolls_back_entire_run(self):
        """
        If an unhandled database or persistence error occurs while creating signals,
        the entire transaction must roll back, ensuring zero orphan runs or candidates.
        """
        initial_runs = MatchingRun.objects.count()
        initial_candidates = MatchingCandidate.objects.count()
        initial_signals = MatchingSignal.objects.count()

        with patch.object(MatchingSignal, "save", side_effect=RuntimeError("Simulated disk error")):
            with self.assertRaises(RuntimeError):
                MatchingRunService.execute_matching_run(
                    rfq_id=self.rfq.id,
                    audience=MatchingAudience.BUYER,
                    actor_scope=self.buyer_scope,
                )

        # Assert clean rollback: absolutely no rows were persisted
        self.assertEqual(MatchingRun.objects.count(), initial_runs)
        self.assertEqual(MatchingCandidate.objects.count(), initial_candidates)
        self.assertEqual(MatchingSignal.objects.count(), initial_signals)

    def test_provider_runtime_exception_rolls_back_entire_run_atomically(self):
        """
        Prove atomicity on provider runtime failure:
        When an active historical provider raises an exception during candidate evaluation,
        the run fails with HistoricalProviderError, the transaction rolls back completely,
        and zero partial MatchingRun, MatchingCandidate, or MatchingSignal records are created.
        """
        initial_runs = MatchingRun.objects.count()
        initial_candidates = MatchingCandidate.objects.count()
        initial_signals = MatchingSignal.objects.count()

        class FailingHistoricalProvider:
            code = "history.failing_atomicity"

            def supports_candidate_kind(self, candidate_kind: str) -> bool:
                return True

            def evaluate(self, candidate, context, policy_version=None):
                raise RuntimeError("Database connection dropped during historical query")

        default_historical_registry.register(FailingHistoricalProvider())
        try:
            with self.assertRaises(HistoricalProviderError) as ctx:
                MatchingRunService.execute_matching_run(
                    rfq_id=self.rfq.id,
                    audience=MatchingAudience.BUYER,
                    actor_scope=self.buyer_scope,
                )

            self.assertEqual(ctx.exception.code, "historical_provider_failure")
            self.assertEqual(ctx.exception.provider_code, "history.failing_atomicity")

            # Assert clean rollback: zero orphan/partial records
            self.assertEqual(MatchingRun.objects.count(), initial_runs)
            self.assertEqual(MatchingCandidate.objects.count(), initial_candidates)
            self.assertEqual(MatchingSignal.objects.count(), initial_signals)
        finally:
            default_historical_registry.clear()
