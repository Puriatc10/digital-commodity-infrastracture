from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from matching.candidates.snapshot import CandidateTrustSnapshot
from matching.enums import CandidateKind, PolicyLifecycleStatus, SignalOutcome
from matching.models import (
    MatchingPolicy,
    MatchingPolicyVersion,
    VerificationMatchingRule,
)
from matching.rules.trust import (
    evaluate_trust,
)
from organizations.verification.models import VerificationStatus


class VerificationMatchingRuleDBConstraintsTests(TestCase):
    """
    Database integrity and constraint tests for VerificationMatchingRule.
    """

    def setUp(self):
        self.policy = MatchingPolicy.objects.create(
            code="test-trust-policy",
            name="Test Trust Policy",
        )
        self.draft_version = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
        )

    def test_unique_policy_version_and_verification_state(self):
        """A policy version cannot have duplicate rules for the same verification state."""
        VerificationMatchingRule.objects.create(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.VERIFIED,
            raw_score=Decimal("1.00"),
        )
        duplicate = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.VERIFIED,
            raw_score=Decimal("0.90"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_negative_score_rejected(self):
        """Scores < 0 must be rejected by clean() and CheckConstraint."""
        rule = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.BASIC_VERIFIED,
            raw_score=Decimal("-0.01"),
        )
        with self.assertRaises(ValidationError):
            rule.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VerificationMatchingRule.objects.bulk_create([rule])

    def test_score_greater_than_one_rejected(self):
        """Scores > 1 must be rejected by clean() and CheckConstraint."""
        rule = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.BASIC_VERIFIED,
            raw_score=Decimal("1.01"),
        )
        with self.assertRaises(ValidationError):
            rule.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VerificationMatchingRule.objects.bulk_create([rule])

    def test_hard_exclude_requires_null_score(self):
        """When hard_exclude is True, raw_score must be null."""
        rule = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.SUSPENDED,
            hard_exclude=True,
            raw_score=Decimal("0.50"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("raw_score", ctx.exception.message_dict)

    def test_non_hard_exclude_requires_score(self):
        """When hard_exclude is False, raw_score is required."""
        rule = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state=VerificationStatus.VERIFIED,
            hard_exclude=False,
            raw_score=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("raw_score", ctx.exception.message_dict)

    def test_invalid_verification_state_rejected(self):
        """Invalid state strings must be rejected."""
        rule = VerificationMatchingRule(
            policy_version=self.draft_version,
            verification_state="completely_fake_state",
            raw_score=Decimal("0.50"),
        )
        with self.assertRaises(ValidationError):
            rule.clean()


class VerificationMatchingRuleImmutabilityTests(TestCase):
    """
    Tests ensuring rules under Published or Retired policies are strictly immutable.
    """

    def setUp(self):
        self.policy = MatchingPolicy.objects.create(
            code="immutability-policy",
            name="Immutability Policy",
        )
        self.v1 = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
        )
        self.rule_verified = VerificationMatchingRule.objects.create(
            policy_version=self.v1,
            verification_state=VerificationStatus.VERIFIED,
            raw_score=Decimal("1.00"),
        )
        self.rule_suspended = VerificationMatchingRule.objects.create(
            policy_version=self.v1,
            verification_state=VerificationStatus.SUSPENDED,
            raw_score=None,
            hard_exclude=True,
        )
        # Publish v1
        self.v1.status = PolicyLifecycleStatus.PUBLISHED
        self.v1.save()

    def test_published_rule_modification_rejected(self):
        """Rules belonging to a Published policy cannot be modified."""
        self.rule_verified.raw_score = Decimal("0.85")
        with self.assertRaises(ValidationError):
            self.rule_verified.save()

        self.rule_suspended.hard_exclude = False
        self.rule_suspended.raw_score = Decimal("0.10")
        with self.assertRaises(ValidationError):
            self.rule_suspended.save()

    def test_published_rule_deletion_rejected(self):
        """Rules belonging to a Published policy cannot be deleted."""
        with self.assertRaises(ValidationError):
            self.rule_verified.delete()

    def test_create_rule_under_published_policy_rejected(self):
        """New rules cannot be added directly to a Published policy version."""
        new_rule = VerificationMatchingRule(
            policy_version=self.v1,
            verification_state=VerificationStatus.UNDER_REVIEW,
            raw_score=Decimal("0.30"),
        )
        with self.assertRaises(ValidationError):
            new_rule.save()

    def test_retired_rule_modification_and_deletion_rejected(self):
        """Retiring a published policy retains strict immutability."""
        self.v1.status = PolicyLifecycleStatus.RETIRED
        self.v1.save()

        self.rule_verified.raw_score = Decimal("0.50")
        with self.assertRaises(ValidationError):
            self.rule_verified.save()

        with self.assertRaises(ValidationError):
            self.rule_verified.delete()

    def test_draft_v2_can_differ_and_historical_v1_remains_unchanged(self):
        """
        Draft v2 can have custom rules differing from v1, while published v1 remains intact.
        """
        v2 = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=2,
            status=PolicyLifecycleStatus.DRAFT,
        )
        # In v2, basic_verified is valued higher (0.85 instead of default 0.70)
        VerificationMatchingRule.objects.create(
            policy_version=v2,
            verification_state=VerificationStatus.BASIC_VERIFIED,
            raw_score=Decimal("0.85"),
        )

        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="basic_verified",
        )

        # Evaluated against v1 (uses default 0.70 since not customized in v1)
        res_v1 = evaluate_trust(cand, policy_version=self.v1)
        self.assertEqual(res_v1.raw_score, Decimal("0.70"))

        # Evaluated against v2 (uses custom 0.85)
        res_v2 = evaluate_trust(cand, policy_version=v2)
        self.assertEqual(res_v2.raw_score, Decimal("0.85"))

        # v1 historical rules are unchanged
        self.rule_verified.refresh_from_db()
        self.assertEqual(self.rule_verified.raw_score, Decimal("1.00"))


class TrustPolicyVersionLookupTests(TestCase):
    """
    Verify that materialize_verification_rules and evaluate_trust strictly respect the policy_version.
    """

    def setUp(self):
        self.policy = MatchingPolicy.objects.create(
            code="version-lookup-policy",
            name="Version Lookup Policy",
        )
        self.v1 = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
        )
        # Custom rule where under_review is hard excluded
        VerificationMatchingRule.objects.create(
            policy_version=self.v1,
            verification_state=VerificationStatus.UNDER_REVIEW,
            hard_exclude=True,
            raw_score=None,
        )
        self.v1.status = PolicyLifecycleStatus.PUBLISHED
        self.v1.save()

    def test_evaluator_uses_exact_policy_version(self):
        """Trust evaluator strictly uses the rule configuration from the supplied policy version."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="under_review",
        )

        # Without policy_version (canonical defaults): under_review is PARTIAL 0.30, not hard
        res_default = evaluate_trust(cand)
        self.assertEqual(res_default.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(res_default.raw_score, Decimal("0.30"))
        self.assertFalse(res_default.is_hard)

        # With v1 (custom hard exclusion): under_review is FAIL, is_hard=True
        res_v1 = evaluate_trust(cand, policy_version=self.v1)
        self.assertEqual(res_v1.outcome, SignalOutcome.FAIL)
        self.assertIsNone(res_v1.raw_score)
        self.assertTrue(res_v1.is_hard)
        self.assertFalse(res_v1.is_eligible)
