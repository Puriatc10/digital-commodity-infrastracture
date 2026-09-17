import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from matching.constants import DEFAULT_ENGINE_VERSION
from matching.enums import MatchingAudience, PolicyLifecycleStatus


class MatchingRun(models.Model):
    """
    Immutable historical audit and execution record for a matching run against an RFQ.

    Stores frozen input/result snapshots, canonical fingerprints, and explicit
    linkages to the exact RFQ version and Published Policy version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Target RFQ Reference (Typed FK, strictly RFQ only)
    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        related_name="matching_runs",
        help_text="Target RFQ procurement demand.",
    )
    rfq_version = models.PositiveIntegerField(
        help_text="Exact RFQ aggregate version at execution time.",
    )

    # Audience Scope
    audience = models.CharField(
        max_length=20,
        choices=MatchingAudience.choices,
        help_text="Target audience scope (BUYER or OPERATOR).",
    )

    # Actor Tracking & Ownership
    requesting_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matching_runs",
        help_text="Buyer organization that requested the run. Null for platform Operator/Admin actors.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requested_matching_runs",
        help_text="Authenticated user who initiated the run.",
    )

    # Policy & Engine Versioning
    policy_version = models.ForeignKey(
        "matching.MatchingPolicyVersion",
        on_delete=models.PROTECT,
        related_name="matching_runs",
        help_text="Published policy version used for candidate evaluation.",
    )
    engine_version = models.CharField(
        max_length=50,
        default=DEFAULT_ENGINE_VERSION,
        help_text="Centralized semantic matching engine contract version.",
    )

    # Snapshots & Deterministic Fingerprints
    target_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Canonical snapshot of RFQ demand at execution time.",
    )
    input_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 fingerprint of the canonical matching inputs.",
    )
    result_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 fingerprint of the canonical matching results.",
    )

    generated_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Timestamp when the matching run was generated.",
    )

    class Meta:
        ordering = ["-generated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rfq_version__gte=1),
                name="check_positive_matching_run_rfq_version",
            ),
            models.CheckConstraint(
                condition=models.Q(audience__in=[c[0] for c in MatchingAudience.choices]),
                name="check_valid_matching_run_audience",
            ),
        ]
        indexes = [
            models.Index(fields=["rfq", "-generated_at"], name="idx_match_run_rfq_gen"),
            models.Index(fields=["audience"], name="idx_match_run_audience"),
            models.Index(fields=["policy_version"], name="idx_match_run_policy_ver"),
            models.Index(fields=["input_fingerprint"], name="idx_match_run_inp_fp"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.rfq_version is not None and self.rfq_version < 1:
            errors["rfq_version"] = "RFQ version must be at least 1."

        if self.audience not in MatchingAudience.values:
            errors["audience"] = f"Audience must be one of: {', '.join(MatchingAudience.values)}."

        # Validate that policy version is published
        if self.policy_version_id:
            policy_version = getattr(self, "policy_version", None)
            if policy_version is None:
                from matching.models.policy import MatchingPolicyVersion
                policy_version = MatchingPolicyVersion.objects.filter(pk=self.policy_version_id).first()
            if policy_version and policy_version.status != PolicyLifecycleStatus.PUBLISHED:
                errors["policy_version"] = "Matching runs can only be executed against a PUBLISHED policy version."

        # Immutability safeguard
        if self.pk and not self._state.adding:
            if MatchingRun.objects.filter(pk=self.pk).exists():
                raise ValidationError("MatchingRun records are historical analytical records and cannot be modified.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("MatchingRun records are historical analytical records and cannot be deleted.")

    @property
    def is_stale(self) -> bool:
        """Return True if the target RFQ version has advanced since this run was generated."""
        if hasattr(self, "rfq") and self.rfq:
            return self.rfq_version != self.rfq.version
        return False

    def __str__(self):
        return f"MatchingRun {self.id} for RFQ {self.rfq_id} v{self.rfq_version} ({self.audience})"
