import uuid

from django.core.exceptions import ValidationError
from django.db import models

from matching.enums import PolicyLifecycleStatus


class MatchingPolicy(models.Model):
    """
    MatchingPolicy Aggregate Root.

    Identifies a named matching policy configuration, whose rules and parameters
    are versioned through immutable MatchingPolicyVersion instances.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=100,
        unique=True,
        help_text="Canonical unique code identifying this policy (e.g. 'default-commodity-matching').",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable policy name.",
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the matching policy objectives and scope.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"], name="idx_matching_policy_code"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class MatchingPolicyVersion(models.Model):
    """
    Immutable versioned snapshot of matching policy parameters, weights, and rules.

    Lifecycle:
        DRAFT -> PUBLISHED -> RETIRED

    Invariants:
        - version > 0
        - (policy, version) is unique
        - Published configuration cannot be modified
        - Published policy can transition to Retired
        - Matching runs can only be executed against Published policy versions
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        MatchingPolicy,
        on_delete=models.PROTECT,
        related_name="versions",
        help_text="Owning matching policy.",
    )
    version = models.PositiveIntegerField(
        help_text="Monotonically increasing version number (must be > 0).",
    )
    status = models.CharField(
        max_length=20,
        choices=PolicyLifecycleStatus.choices,
        default=PolicyLifecycleStatus.DRAFT,
        help_text="Current lifecycle state of this policy version.",
    )
    description = models.TextField(
        blank=True,
        help_text="Release notes or rationale for this policy version.",
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        help_text="Deterministic configuration snapshot of weights, thresholds, and rule parameters.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["policy", "-version"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="check_positive_policy_version",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in PolicyLifecycleStatus.choices]),
                name="check_valid_policy_version_status",
            ),
            models.UniqueConstraint(
                fields=["policy", "version"],
                name="unique_policy_version",
            ),
        ]
        indexes = [
            models.Index(fields=["policy", "version"], name="idx_match_pol_ver"),
            models.Index(fields=["status"], name="idx_match_pol_status"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.version is not None and self.version <= 0:
            errors["version"] = "Policy version must be greater than 0."

        if self._state.adding and self.status == PolicyLifecycleStatus.RETIRED:
            errors["status"] = "New policy versions cannot start retired."

        if self.pk and not self._state.adding:
            persisted = MatchingPolicyVersion.objects.filter(pk=self.pk).first()
            if persisted:
                # Core identity immutability
                if self.policy_id != persisted.policy_id:
                    errors["policy"] = "Policy reference cannot be modified."
                if self.version != persisted.version:
                    errors["version"] = "Policy version number cannot be modified."

                # Status transitions and configuration immutability
                if persisted.status == PolicyLifecycleStatus.DRAFT:
                    if self.status == PolicyLifecycleStatus.RETIRED:
                        errors["status"] = "Draft policy versions must be published before retirement."
                elif persisted.status == PolicyLifecycleStatus.PUBLISHED:
                    if self.status == PolicyLifecycleStatus.DRAFT:
                        errors["status"] = "Cannot revert a published policy version to draft."
                    # Configuration cannot be edited after publication
                    if self.configuration != persisted.configuration:
                        errors["configuration"] = "Configuration of a published policy version is immutable."
                elif persisted.status == PolicyLifecycleStatus.RETIRED:
                    if self.status != PolicyLifecycleStatus.RETIRED:
                        errors["status"] = "Retired policy versions cannot change status."
                    if self.configuration != persisted.configuration:
                        errors["configuration"] = "Configuration of a retired policy version is immutable."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in [PolicyLifecycleStatus.PUBLISHED, PolicyLifecycleStatus.RETIRED]:
            raise ValidationError("Published or retired policy versions cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.policy.code} v{self.version} ({self.get_status_display()})"
