from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from offers.enums import AwardStatus


class Award(models.Model):
    """
    Authoritative Award aggregate root for an RFQ (Contract §63, T0813).

    Represents the formal procurement award decision made by a human buyer or
    authorized operator.
    Guarantees exactly one Award aggregate per RFQ via database unique constraint.

    Lifecycle:
        DRAFT -> FINALIZED

    Once FINALIZED, the award and all its allocations are strictly immutable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # One Award per RFQ aggregate root
    rfq = models.OneToOneField(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        related_name="award",
        help_text="Target RFQ for this procurement award aggregate.",
    )

    status = models.CharField(
        max_length=20,
        choices=AwardStatus.choices,
        default=AwardStatus.DRAFT,
        help_text="Lifecycle status of the award (DRAFT or FINALIZED).",
    )

    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    # Creator Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_awards",
        help_text="Platform user who created the draft award.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Finalization Audit
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finalized_awards",
        help_text="Platform user who authoritatively finalized the award.",
    )
    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when the award was finalized.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in AwardStatus.choices]),
                name="check_valid_award_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_award_version",
            ),
        ]
        indexes = [
            models.Index(fields=["rfq", "status"], name="idx_award_rfq_status"),
        ]

    def __str__(self) -> str:
        return f"Award {self.id} for RFQ {self.rfq_id} ({self.status})"

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        if self.status == AwardStatus.FINALIZED:
            if not self.finalized_by_id:
                errors["finalized_by"] = "finalized_by is strictly required when status is FINALIZED."
            if not self.finalized_at:
                errors["finalized_at"] = "finalized_at timestamp is strictly required when status is FINALIZED."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)


class AwardAllocation(models.Model):
    """
    Individual commercial allocation row within an Award (Contract §64, T0813).

    Binds an awarded quantity to an EXACT submitted OfferVersion commercial snapshot.
    DB unique constraint on (award, offer_version) prevents duplicate allocations
    for the exact same commercial snapshot.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    award = models.ForeignKey(
        "offers.Award",
        on_delete=models.CASCADE,
        related_name="allocations",
        help_text="Parent award aggregate.",
    )

    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="award_allocations",
        help_text="Parent offer thread.",
    )

    offer_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        related_name="award_allocations",
        help_text="Exact selected OfferVersion commercial snapshot.",
    )

    awarded_quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Awarded commercial quantity (strictly positive Decimal).",
    )

    quantity_unit = models.CharField(
        max_length=20,
        help_text="Commercial unit of measurement (must match RFQ and OfferVersion).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["award", "offer_version"],
                name="unique_award_offer_version",
            ),
            models.CheckConstraint(
                condition=models.Q(awarded_quantity__gt=0),
                name="check_positive_awarded_quantity",
            ),
        ]
        indexes = [
            models.Index(fields=["award", "offer"], name="idx_alloc_award_offer"),
        ]

    def __str__(self) -> str:
        return (
            f"Allocation {self.id}: {self.awarded_quantity} {self.quantity_unit} "
            f"to Offer {self.offer_id} V{getattr(self.offer_version, 'version_number', '?')}"
        )

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.awarded_quantity is not None and self.awarded_quantity <= Decimal("0"):
            errors["awarded_quantity"] = "Awarded quantity must be strictly greater than zero."

        # Referential integrity checks
        if self.offer_version_id and self.offer_id:
            if self.offer_version.offer_id != self.offer_id:
                errors["offer_version"] = "Selected OfferVersion does not belong to the referenced Offer."

        if self.offer_id and self.award_id:
            if self.offer.rfq_id != self.award.rfq_id:
                errors["offer"] = "Referenced Offer does not target the same RFQ as the Award."

        if self.offer_version_id:
            if self.quantity_unit and self.offer_version.quantity_unit != self.quantity_unit:
                errors["quantity_unit"] = (
                    f"Quantity unit '{self.quantity_unit}' does not match "
                    f"OfferVersion unit '{self.offer_version.quantity_unit}'."
                )
            if self.awarded_quantity is not None:
                if self.awarded_quantity > self.offer_version.offered_quantity:
                    errors["awarded_quantity"] = (
                        f"Awarded quantity ({self.awarded_quantity}) cannot exceed "
                        f"offered quantity ({self.offer_version.offered_quantity})."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)
