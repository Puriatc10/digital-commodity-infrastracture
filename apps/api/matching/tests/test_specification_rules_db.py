from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityAttributeSemanticIdentity,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from matching.enums import PolicyLifecycleStatus, SignalOutcome
from matching.models import (
    MatchingPolicy,
    MatchingPolicyVersion,
    SpecificationMatchingRule,
    SpecificationRuleOperator,
)


class SpecificationMatchingRuleModelTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_spec_test",
            name_fa="قیر آزمایشی قوانین",
            name_en="Test Bitumen Spec",
        )
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
        )
        self.attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_version,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.ENUM,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={"options": [{"value": "60/70"}]},
        )
        self.semantic_identity = self.attr.semantic_identity

        self.policy = MatchingPolicy.objects.create(
            name="Test Policy",
            description="Policy for testing specification rules",
        )
        self.policy_version = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
        )

    def test_create_valid_specification_rule(self):
        """Create a valid specification matching rule on a draft policy version."""
        rule = SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=True,
            relative_weight=Decimal("2.5000"),
            missing_data_policy=SignalOutcome.UNKNOWN,
        )
        self.assertEqual(rule.operator, SpecificationRuleOperator.EXACT)
        self.assertTrue(rule.hard_constraint)
        self.assertEqual(rule.relative_weight, Decimal("2.5000"))

    def test_uniqueness_policy_version_and_semantic_identity(self):
        """Cannot create duplicate rules for the same semantic identity on the same policy version."""
        SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SpecificationMatchingRule.objects.create(
                    policy_version=self.policy_version,
                    semantic_identity=self.semantic_identity,
                    operator=SpecificationRuleOperator.MIN_REQUIRED,
                )

    def test_target_with_tolerance_requires_tolerance(self):
        """TARGET_WITH_TOLERANCE requires a non-negative tolerance."""
        # None tolerance -> ValidationError
        with self.assertRaises(ValidationError):
            rule = SpecificationMatchingRule(
                policy_version=self.policy_version,
                semantic_identity=self.semantic_identity,
                operator=SpecificationRuleOperator.TARGET_WITH_TOLERANCE,
                tolerance=None,
            )
            rule.full_clean()

        # Negative tolerance -> ValidationError
        with self.assertRaises(ValidationError):
            rule = SpecificationMatchingRule(
                policy_version=self.policy_version,
                semantic_identity=self.semantic_identity,
                operator=SpecificationRuleOperator.TARGET_WITH_TOLERANCE,
                tolerance=Decimal("-0.5000"),
            )
            rule.full_clean()

        # Valid non-negative tolerance -> succeeds
        rule = SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.semantic_identity,
            operator=SpecificationRuleOperator.TARGET_WITH_TOLERANCE,
            tolerance=Decimal("5.0000"),
        )
        self.assertEqual(rule.tolerance, Decimal("5.0000"))

    def test_non_tolerance_operators_forbid_tolerance(self):
        """Operators other than TARGET_WITH_TOLERANCE forbid tolerance."""
        for op in [
            SpecificationRuleOperator.EXACT,
            SpecificationRuleOperator.MIN_REQUIRED,
            SpecificationRuleOperator.MAX_ALLOWED,
            SpecificationRuleOperator.IGNORE,
        ]:
            with self.assertRaises(ValidationError):
                rule = SpecificationMatchingRule(
                    policy_version=self.policy_version,
                    semantic_identity=self.semantic_identity,
                    operator=op,
                    tolerance=Decimal("2.0000"),
                )
                rule.full_clean()

    def test_ignore_operator_cannot_be_hard_constraint(self):
        """IGNORE operator cannot be configured as a hard constraint."""
        with self.assertRaises(ValidationError):
            rule = SpecificationMatchingRule(
                policy_version=self.policy_version,
                semantic_identity=self.semantic_identity,
                operator=SpecificationRuleOperator.IGNORE,
                hard_constraint=True,
            )
            rule.full_clean()

    def test_relative_weight_cannot_be_negative(self):
        """Relative weight cannot be negative."""
        with self.assertRaises(ValidationError):
            rule = SpecificationMatchingRule(
                policy_version=self.policy_version,
                semantic_identity=self.semantic_identity,
                operator=SpecificationRuleOperator.EXACT,
                relative_weight=Decimal("-1.0000"),
            )
            rule.full_clean()

    def test_published_policy_version_rules_immutable(self):
        """Rules cannot be created, modified, or deleted on published or retired policy versions."""
        rule = SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
        )

        # Publish the policy version
        self.policy_version.status = PolicyLifecycleStatus.PUBLISHED
        self.policy_version.save(update_fields=["status"])

        # 1. Cannot update rule
        rule.operator = SpecificationRuleOperator.MIN_REQUIRED
        with self.assertRaises(ValidationError):
            rule.save()

        # 2. Cannot delete rule
        with self.assertRaises(ValidationError):
            rule.delete()

        # 3. Cannot create new rule
        other_sem = CommodityAttributeSemanticIdentity.objects.create(
            commodity=self.commodity,
            code="other_sem_id",
        )
        with self.assertRaises(ValidationError):
            SpecificationMatchingRule.objects.create(
                policy_version=self.policy_version,
                semantic_identity=other_sem,
                operator=SpecificationRuleOperator.EXACT,
            )

    def test_semantic_identity_protected_from_deletion_when_referenced_by_rule(self):
        """Deleting a semantic identity referenced by a matching rule raises ProtectedError."""
        SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
        )
        with self.assertRaises(ProtectedError):
            self.semantic_identity.delete()

