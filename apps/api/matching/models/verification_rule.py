from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from matching.enums import PolicyLifecycleStatus
from organizations.verification.models import VerificationStatus


class VerificationMatchingRule(models.Model):
    """
    Matching-policy-owned rule specifying how an organization verification status
    should be evaluated during matching.

    Lifecycle:
        Draft rules can be created, modified, or deleted.
        Rules under Published or Retired policy versions are strictly immutable.

    Invariants:
        - (policy_version, verification_state) is unique.
        - raw_score is a Decimal between 0.0000 and 1.0000 when hard_exclude is False.
        - raw_score must be null when hard_exclude is True (hard exclusion representation).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy_version = models.ForeignKey(
        "matching.MatchingPolicyVersion",
        on_delete=models.CASCADE,
        related_name="verification_rules",
        help_text="Matching policy version that owns this verification rule.",
    )
    verification_state = models.CharField(
        max_length=50,
        choices=VerificationStatus.choices,
        help_text="Organization verification status to evaluate.",
    )
    raw_score = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Normalized score in [0.0000, 1.0000]. Must be null if hard_exclude is True.",
    )
    hard_exclude = models.BooleanField(
        default=False,
        help_text="If True, candidate with this verification status is hard excluded (candidate ineligible).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["policy_version", "verification_state"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_version", "verification_state"],
                name="unique_verification_rule_policy_state",
            ),
            models.CheckConstraint(
                condition=models.Q(verification_state__in=[c[0] for c in VerificationStatus.choices]),
                name="check_valid_verification_rule_state",
            ),
            models.CheckConstraint(
                condition=models.Q(raw_score__isnull=True)
                | (models.Q(raw_score__gte=Decimal("0.0000")) & models.Q(raw_score__lte=Decimal("1.0000"))),
                name="check_verification_rule_score_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["policy_version", "verification_state"],
                name="idx_ver_rule_pol_state",
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
            persisted = VerificationMatchingRule.objects.select_related("policy_version").filter(pk=self.pk).first()
            if persisted and persisted.policy_version.status != PolicyLifecycleStatus.DRAFT:
                errors["policy_version"] = "Rules under a published or retired policy version are immutable."

        # 2. Verification state valid choice
        valid_states = [c[0] for c in VerificationStatus.choices]
        if self.verification_state and self.verification_state not in valid_states:
            errors["verification_state"] = f"Invalid verification state '{self.verification_state}'. Must be one of: {', '.join(valid_states)}."

        # 3. Score and hard_exclude consistency
        if self.hard_exclude:
            if self.raw_score is not None:
                errors["raw_score"] = "raw_score must be null when hard_exclude is True."
        else:
            if self.raw_score is None:
                errors["raw_score"] = "raw_score is required when hard_exclude is False."
            elif self.raw_score < Decimal("0.0000") or self.raw_score > Decimal("1.0000"):
                errors["raw_score"] = "raw_score must be between 0 and 1."

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
            f"VerificationMatchingRule({self.policy_version}, {self.verification_state}, "
            f"score={self.raw_score}, hard={self.hard_exclude})"
        )
