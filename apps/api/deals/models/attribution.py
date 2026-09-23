import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class DealAttributionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RESOLVED = "RESOLVED", "Resolved"


class DealAttributionChannel(models.TextChoices):
    PLATFORM_NETWORK = "PLATFORM_NETWORK", "Platform Network"
    DIRECT_SUPPLIER = "DIRECT_SUPPLIER", "Direct Supplier"
    BROKER = "BROKER", "Broker"
    OPPORTUNITY_DESK = "OPPORTUNITY_DESK", "Opportunity Desk"
    BUYER_EXISTING_SUPPLIER = "BUYER_EXISTING_SUPPLIER", "Buyer Existing Supplier"


class DealAttributionResolutionMethod(models.TextChoices):
    AUTOMATIC = "AUTOMATIC", "Automatic"
    MANUAL = "MANUAL", "Manual"


class DealAttribution(models.Model):
    """
    DealAttribution Aggregate (Epic 9 Contract §36-§49, T0903).

    Represents the explainable primary origin classification for a Deal:
        explicit persisted provenance -> deterministic resolver -> RESOLVED / PENDING.

    Critical Invariants:
    - 1 Deal -> exactly 1 DealAttribution (OneToOneField with DB unique constraint).
    - Attribution represents provenance only: NOT party identity, ACL, commission, trust, or analytics.
    - Status is exactly PENDING or RESOLVED.
    - Primary channel is exactly one of the 5 roadmap categories when RESOLVED, and strictly NULL when PENDING.
    - Immutability: Once RESOLVED, primary_channel, resolution metadata, and evidence snapshot cannot be changed.
    - Server derivation: Client cannot forge evidence; server owns resolution audit metadata.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 1:1 Deal Linkage (Contract §38)
    deal = models.OneToOneField(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="attribution",
        help_text="Parent Deal aggregate.",
    )

    # Lifecycle & Primary Channel
    status = models.CharField(
        max_length=20,
        choices=DealAttributionStatus.choices,
        default=DealAttributionStatus.PENDING,
        help_text="Attribution resolution status (PENDING or RESOLVED).",
    )
    primary_channel = models.CharField(
        max_length=40,
        choices=DealAttributionChannel.choices,
        null=True,
        blank=True,
        help_text="Authoritative primary attribution business category (null when PENDING).",
    )

    # Resolution Metadata
    resolution_method = models.CharField(
        max_length=20,
        choices=DealAttributionResolutionMethod.choices,
        null=True,
        blank=True,
        help_text="Method by which attribution was resolved (AUTOMATIC or MANUAL).",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Platform user (Operator/Admin) who authoritatively resolved the attribution.",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative timestamp when attribution was resolved.",
    )
    resolution_reason = models.TextField(
        blank=True,
        default="",
        help_text="Explanation or operational reason for the resolution decision.",
    )

    # Structured, Privacy-Preserving Evidence Snapshot (Contract §49)
    evidence_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Canonical frozen structured evidence dictionary used by the resolver.",
    )

    # Optimistic Concurrency Foundation
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Deal Attribution"
        verbose_name_plural = "Deal Attributions"
        constraints = [
            # 1. PENDING <-> null primary_channel; RESOLVED <-> non-null primary_channel
            models.CheckConstraint(
                condition=(
                    (models.Q(status=DealAttributionStatus.PENDING) & models.Q(primary_channel__isnull=True))
                    | (models.Q(status=DealAttributionStatus.RESOLVED) & models.Q(primary_channel__isnull=False))
                ),
                name="check_deal_attribution_status_channel_consistency",
            ),
            # 2. Valid status
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in DealAttributionStatus.choices]),
                name="check_valid_deal_attribution_status",
            ),
            # 3. Valid primary channel if set
            models.CheckConstraint(
                condition=(
                    models.Q(primary_channel__isnull=True)
                    | models.Q(primary_channel__in=[c[0] for c in DealAttributionChannel.choices])
                ),
                name="check_valid_deal_attribution_primary_channel",
            ),
            # 4. Valid resolution method if set
            models.CheckConstraint(
                condition=(
                    models.Q(resolution_method__isnull=True)
                    | models.Q(resolution_method__in=[c[0] for c in DealAttributionResolutionMethod.choices])
                ),
                name="check_valid_deal_attribution_resolution_method",
            ),
            # 5. Positive version counter
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_deal_attribution_version",
            ),
        ]
        indexes = [
            models.Index(fields=["deal"], name="idx_deal_attr_deal"),
            models.Index(fields=["status"], name="idx_deal_attr_status"),
            models.Index(fields=["primary_channel"], name="idx_deal_attr_channel"),
            models.Index(fields=["-created_at"], name="idx_deal_attr_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        # 1. Version positive check
        if self.version is not None and self.version < 1:
            errors["version"] = "version must be a positive integer."

        # 2. Status & Primary Channel consistency
        if self.status == DealAttributionStatus.PENDING:
            if self.primary_channel is not None:
                errors["primary_channel"] = "primary_channel must be null when status is PENDING."
        elif self.status == DealAttributionStatus.RESOLVED:
            if not self.primary_channel:
                errors["primary_channel"] = "primary_channel is strictly required when status is RESOLVED."
            elif self.primary_channel not in DealAttributionChannel.values:
                errors["primary_channel"] = f"Invalid primary_channel '{self.primary_channel}'."

            if not self.resolution_method:
                errors["resolution_method"] = "resolution_method is required when status is RESOLVED."
            elif self.resolution_method not in DealAttributionResolutionMethod.values:
                errors["resolution_method"] = f"Invalid resolution_method '{self.resolution_method}'."

            if not self.resolved_at:
                errors["resolved_at"] = "resolved_at timestamp is required when status is RESOLVED."

            if self.resolution_method == DealAttributionResolutionMethod.MANUAL:
                if not self.resolved_by_id:
                    errors["resolved_by"] = "resolved_by is strictly required for MANUAL resolution."
                if not self.resolution_reason or not self.resolution_reason.strip():
                    errors["resolution_reason"] = "resolution_reason is strictly required for MANUAL resolution."
        else:
            errors["status"] = f"Invalid status '{self.status}'."

        # 3. Immutability guard for already RESOLVED records
        if not self._state.adding and self.pk:
            orig = (
                DealAttribution.objects.filter(pk=self.pk)
                .values("status", "primary_channel", "resolution_method", "version")
                .first()
            )
            if orig and orig["status"] == DealAttributionStatus.RESOLVED:
                if (
                    self.status != DealAttributionStatus.RESOLVED
                    or self.primary_channel != orig["primary_channel"]
                    or self.resolution_method != orig["resolution_method"]
                ):
                    errors["status"] = "Resolved DealAttribution is immutable and cannot be rewritten or reopened."

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        chan = self.primary_channel or "None"
        return f"DealAttribution {self.id} for Deal {self.deal_id} [{self.status}: {chan}]"
