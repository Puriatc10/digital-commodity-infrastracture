from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from matching.enums import PolicyLifecycleStatus, SignalOutcome


class SpecificationRuleOperator(models.TextChoices):
    EXACT = "EXACT", "Exact"
    MIN_REQUIRED = "MIN_REQUIRED", "Min Required"
    MAX_ALLOWED = "MAX_ALLOWED", "Max Allowed"
    TARGET_WITH_TOLERANCE = "TARGET_WITH_TOLERANCE", "Target With Tolerance"
    IGNORE = "IGNORE", "Ignore"


class SpecificationMatchingRule(models.Model):
    """
    Matching-policy-owned rule specifying how a particular commodity attribute
    semantic identity should be evaluated during matching.

    Lifecycle:
        Draft rules can be edited/deleted.
        Rules under Published or Retired policies are strictly immutable.

    Operators:
        EXACT: Canonical exact comparison.
        MIN_REQUIRED: Candidate numeric value must meet or exceed RFQ requested target.
        MAX_ALLOWED: Candidate numeric value must not exceed RFQ requested limit.
        TARGET_WITH_TOLERANCE: Candidate numeric value must fall within [target - tol, target + tol].
        IGNORE: Attribute produces NOT_APPLICABLE and does not contribute to matching.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy_version = models.ForeignKey(
        "matching.MatchingPolicyVersion",
        on_delete=models.CASCADE,
        related_name="specification_rules",
        help_text="Matching policy version that owns this specification rule.",
    )
    semantic_identity = models.ForeignKey(
        "commodities.CommodityAttributeSemanticIdentity",
        on_delete=models.PROTECT,
        related_name="specification_matching_rules",
        help_text="The semantic identity of the attribute evaluated by this rule.",
    )
    operator = models.CharField(
        max_length=30,
        choices=SpecificationRuleOperator.choices,
        default=SpecificationRuleOperator.EXACT,
        help_text="Operator for comparing RFQ target against candidate actual value.",
    )
    hard_constraint = models.BooleanField(
        default=False,
        help_text="If True, candidate mismatch results in hard failure (candidate ineligible).",
    )
    relative_weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Relative contribution weight within the specification dimension (>= 0).",
    )
    tolerance = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Allowed numeric tolerance for TARGET_WITH_TOLERANCE operator (must be >= 0).",
    )
    missing_data_policy = models.CharField(
        max_length=20,
        choices=SignalOutcome.choices,
        default=SignalOutcome.UNKNOWN,
        help_text="Outcome when candidate lacks evidence for this attribute (default UNKNOWN).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["policy_version", "semantic_identity"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_version", "semantic_identity"],
                name="unique_spec_rule_policy_semantic_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(relative_weight__gte=0),
                name="check_spec_rule_weight_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(operator__in=SpecificationRuleOperator.values),
                name="check_spec_rule_valid_operator",
            ),
            models.CheckConstraint(
                condition=models.Q(missing_data_policy__in=SignalOutcome.values),
                name="check_spec_rule_valid_missing_policy",
            ),
            models.CheckConstraint(
                condition=models.Q(tolerance__isnull=True) | models.Q(tolerance__gte=0),
                name="check_spec_rule_tolerance_nonneg",
            ),
        ]
        indexes = [
            models.Index(
                fields=["policy_version", "semantic_identity"],
                name="idx_spec_rule_pol_sem",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        # 1. Published policy immutability
        if self.policy_version_id:
            pv = getattr(self, "policy_version", None)
            if pv is None:
                from matching.models.policy import MatchingPolicyVersion
                pv = MatchingPolicyVersion.objects.filter(pk=self.policy_version_id).first()
            if pv and pv.status != PolicyLifecycleStatus.DRAFT:
                errors["policy_version"] = "Rules under a published or retired policy version cannot be created or modified."

        if self.pk:
            persisted = SpecificationMatchingRule.objects.select_related("policy_version").filter(pk=self.pk).first()
            if persisted and persisted.policy_version.status != PolicyLifecycleStatus.DRAFT:
                errors["policy_version"] = "Rules under a published or retired policy version are immutable."

        # 2. Operator and tolerance configuration
        if self.operator == SpecificationRuleOperator.TARGET_WITH_TOLERANCE:
            if self.tolerance is None:
                errors["tolerance"] = "Tolerance is required for TARGET_WITH_TOLERANCE operator."
            elif self.tolerance < Decimal("0"):
                errors["tolerance"] = "Tolerance must be non-negative."
        else:
            if self.tolerance is not None:
                errors["tolerance"] = f"Tolerance must be null for operator '{self.operator}'."

        # 3. Relative weight non-negative
        if self.relative_weight is not None and self.relative_weight < Decimal("0"):
            errors["relative_weight"] = "Relative weight must be non-negative."

        # 4. Ignored rule cannot be hard constraint
        if self.operator == SpecificationRuleOperator.IGNORE and self.hard_constraint:
            errors["hard_constraint"] = "An IGNORE rule cannot be configured as a hard constraint."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.policy_version.status != PolicyLifecycleStatus.DRAFT:
            raise ValidationError("Rules under a published or retired policy version cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"Rule({self.policy_version}, {self.semantic_identity.code}, "
            f"{self.operator}, w={self.relative_weight}, hard={self.hard_constraint})"
        )
