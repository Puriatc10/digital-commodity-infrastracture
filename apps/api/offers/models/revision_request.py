import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from offers.enums import (
    FORBIDDEN_REVISION_FIELDS,
    OfferVersionStatus,
    RevisionRequestedField,
    RevisionRequestStatus,
)


class RevisionRequest(models.Model):
    """
    Formal procurement negotiation revision request against a submitted OfferVersion (Epic 8 Contract §56).

    A Buyer-side procurement actor or Operator issues a RevisionRequest specifying
    the exact commercial fields requested for revision and an optional human-readable message.
    It targets exactly one submitted OfferVersion (the current commercial base).

    Lifecycle:
        OPEN -> DECLINED (by Offer participant)
        OPEN -> CANCELLED (by Buyer / Operator)
        OPEN -> RESOLVED (by revised OfferVersion in T0811)

    Invariants:
    - Exactly one OPEN request per Offer at any point in time (enforced by DB conditional unique constraint).
    - Base OfferVersion must belong to the Offer and be in SUBMITTED status.
    - Base OfferVersion is commercially immutable and never mutated by revision requests.
    - Terminal states (DECLINED, CANCELLED, RESOLVED) cannot be mutated or reopened.
    - requested_fields is a canonical list of valid field identifiers without duplicates or forbidden server fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="revision_requests",
        help_text="Parent offer aggregate.",
    )
    base_offer_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        related_name="base_revision_requests",
        help_text="Target submitted OfferVersion being revised.",
    )
    requested_fields = models.JSONField(
        default=list,
        help_text="Canonical list of field names requested for revision.",
    )
    message = models.TextField(
        blank=True,
        default="",
        help_text="Human-entered revision explanation or instruction.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_revisions",
        help_text="Platform user who initiated the revision request.",
    )
    requested_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when revision request was created.",
    )
    status = models.CharField(
        max_length=20,
        choices=RevisionRequestStatus.choices,
        default=RevisionRequestStatus.OPEN,
        help_text="Revision request lifecycle status: OPEN, RESOLVED, DECLINED, CANCELLED.",
    )
    resolved_by_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolving_revision_requests",
        help_text="Revised OfferVersion that resolves this request (T0811).",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when request was resolved, declined, or cancelled.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "Revision Request"
        verbose_name_plural = "Revision Requests"
        constraints = [
            # 1. At most one OPEN revision request per Offer (Epic 8 Contract §59)
            models.UniqueConstraint(
                fields=["offer"],
                condition=models.Q(status=RevisionRequestStatus.OPEN),
                name="unique_open_revision_request_per_offer",
            ),
            # 2. Valid status check
            models.CheckConstraint(
                condition=models.Q(status__in=RevisionRequestStatus.values),
                name="check_revision_request_valid_status",
            ),
            # 3. Resolution consistency: resolved_by_version present iff status == RESOLVED
            models.CheckConstraint(
                condition=(
                    (models.Q(status=RevisionRequestStatus.RESOLVED) & models.Q(resolved_by_version__isnull=False))
                    | (~models.Q(status=RevisionRequestStatus.RESOLVED) & models.Q(resolved_by_version__isnull=True))
                ),
                name="check_revision_request_resolution_consistency",
            ),
        ]
        indexes = [
            models.Index(fields=["offer", "status"], name="idx_rev_req_offer_status"),
            models.Index(fields=["base_offer_version"], name="idx_rev_req_base_ver"),
            models.Index(fields=["-requested_at"], name="idx_rev_req_requested_at"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        # 1. Base OfferVersion validation
        if self.offer_id and self.base_offer_version_id:
            if self.base_offer_version.offer_id != self.offer_id:
                errors["base_offer_version"] = "base_offer_version must belong to this offer."
            if self.base_offer_version.status != OfferVersionStatus.SUBMITTED:
                errors["base_offer_version"] = "base_offer_version must be in SUBMITTED status."

        # 2. Canonical requested_fields validation
        if not isinstance(self.requested_fields, list):
            errors["requested_fields"] = "requested_fields must be a list of field names."
        elif not self.requested_fields:
            errors["requested_fields"] = "At least one field must be requested for revision."
        else:
            allowed_fields = set(RevisionRequestedField.values)
            seen = set()
            for f in self.requested_fields:
                if not isinstance(f, str):
                    errors["requested_fields"] = f"Invalid field '{f}'; field names must be strings."
                    break
                clean_f = f.strip()
                if clean_f in seen:
                    errors["requested_fields"] = f"Duplicate field '{clean_f}' in requested_fields."
                    break
                seen.add(clean_f)
                if clean_f in FORBIDDEN_REVISION_FIELDS:
                    errors["requested_fields"] = f"Field '{clean_f}' is forbidden and cannot be requested for revision."
                    break
                if clean_f not in allowed_fields:
                    errors["requested_fields"] = (
                        f"Field '{clean_f}' is not a valid revisable field. "
                        f"Allowed fields: {', '.join(sorted(allowed_fields))}."
                    )
                    break

        # 3. Status transition & terminal immutability validation
        if self.pk and not self._state.adding:
            persisted = RevisionRequest.objects.filter(pk=self.pk).first()
            if persisted:
                terminal_statuses = {
                    RevisionRequestStatus.RESOLVED,
                    RevisionRequestStatus.DECLINED,
                    RevisionRequestStatus.CANCELLED,
                }
                if persisted.status in terminal_statuses:
                    if self.status != persisted.status:
                        raise ValidationError(
                            f"RevisionRequest is in terminal status '{persisted.status}' and cannot be modified or reopened."
                        )
                    # Once terminal, commercial metadata is completely immutable
                    immutable_attrs = [
                        "offer_id",
                        "base_offer_version_id",
                        "requested_fields",
                        "message",
                        "requested_by_id",
                        "requested_at",
                        "resolved_by_version_id",
                        "resolved_at",
                    ]
                    for attr in immutable_attrs:
                        if getattr(self, attr) != getattr(persisted, attr):
                            raise ValidationError(
                                f"Field '{attr}' cannot be changed on a terminal RevisionRequest."
                            )
                else:
                    # Current status is OPEN: cannot modify core request definition
                    immutable_attrs = [
                        "offer_id",
                        "base_offer_version_id",
                        "requested_fields",
                        "message",
                        "requested_by_id",
                        "requested_at",
                    ]
                    for attr in immutable_attrs:
                        if getattr(self, attr) != getattr(persisted, attr):
                            raise ValidationError(
                                f"Field '{attr}' cannot be modified once RevisionRequest is created."
                            )

        # 4. In T0810, transition to RESOLVED is guarded
        if self.status == RevisionRequestStatus.RESOLVED and not self.resolved_by_version_id:
            errors["resolved_by_version"] = "resolved_by_version is required when status is RESOLVED."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("RevisionRequest records are immutable historical audit records and cannot be deleted.")

    def __str__(self):
        return f"RevisionRequest {self.id} for Offer {self.offer_id} ({self.status})"
