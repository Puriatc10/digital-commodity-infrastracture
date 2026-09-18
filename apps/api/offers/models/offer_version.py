from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from commodities.services import validate_commodity_payload
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferVersionStatus


class OfferVersion(models.Model):
    """
    Immutable commercial snapshot of an Offer (Epic 8 Contract §9, §10, §13).

    Represents an exact commercial proposal (price, quantity, specs, delivery,
    payment, logistics) at a point in time.
    Lifecycle is strictly DRAFT -> SUBMITTED.
    Once SUBMITTED, all commercial fields and child cost components are immutable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="versions",
        help_text="Parent offer aggregate.",
    )
    version_number = models.PositiveIntegerField(
        help_text="Authoritative server-allocated sequential version number (1, 2, ...).",
    )
    status = models.CharField(
        max_length=20,
        choices=OfferVersionStatus.choices,
        default=OfferVersionStatus.DRAFT,
        help_text="Lifecycle status: DRAFT or SUBMITTED.",
    )

    # Dynamic Commodity Specifications (RFQ Schema Lock)
    schema_version = models.ForeignKey(
        "commodities.CommoditySchemaVersion",
        on_delete=models.PROTECT,
        related_name="offer_versions",
        help_text="Exact schema version bound to the parent RFQ.",
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic specification attributes validated against schema_version.",
    )

    # Commercial Quantities
    offered_quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Proposed quantity (strictly positive; partial or surplus allowed).",
    )
    quantity_unit = models.CharField(
        max_length=20,
        help_text="Unit of measurement (must be compatible with RFQ unit).",
    )

    # Commercial Price & Currency
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Proposed price per unit (strictly positive).",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="ISO 4217 3-letter currency code (exact submitted truth; no FX).",
    )

    # Payment & Commercial Delivery Terms
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Proposed payment terms (e.g. LC at sight, TT 30 days).",
    )
    delivery_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Proposed delivery conditions or freight details.",
    )
    incoterm = models.CharField(
        max_length=10,
        blank=True,
        help_text="Incoterm code (e.g. FOB, CIF, CFR, EXW).",
    )
    delivery_start = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest proposed delivery date.",
    )
    delivery_end = models.DateField(
        null=True,
        blank=True,
        help_text="Latest proposed delivery date.",
    )
    valid_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Proposal validity timestamp (expiry derived, not mutated).",
    )

    # Logistics Cost
    logistics_cost_status = models.CharField(
        max_length=20,
        choices=LogisticsCostStatus.choices,
        default=LogisticsCostStatus.UNKNOWN,
        help_text="Status of logistics cost knowledge.",
    )
    logistics_cost_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Separate logistics cost amount (required if KNOWN_SEPARATE; absent otherwise).",
    )

    notes = models.TextField(
        blank=True,
        help_text="Commercial notes or comments accompanying the version.",
    )

    # Actor Tracking & Timestamps
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_offer_versions",
        help_text="Platform user who created this version draft.",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_offer_versions",
        help_text="Platform user who submitted this version.",
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when version was submitted.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["offer", "version_number"]
        verbose_name = "Offer Version"
        verbose_name_plural = "Offer Versions"
        constraints = [
            # 1. At most one DRAFT per Offer (PostgreSQL conditional unique constraint)
            models.UniqueConstraint(
                fields=["offer"],
                condition=models.Q(status="DRAFT"),
                name="unique_one_draft_per_offer",
            ),
            # 2. Sequential version number uniqueness per Offer
            models.UniqueConstraint(
                fields=["offer", "version_number"],
                name="unique_offer_version_number",
            ),
            # 3. Strictly positive quantity
            models.CheckConstraint(
                condition=models.Q(offered_quantity__gt=0),
                name="check_offer_version_quantity_positive",
            ),
            # 4. Strictly positive unit price
            models.CheckConstraint(
                condition=models.Q(unit_price__gt=0),
                name="check_offer_version_unit_price_positive",
            ),
            # 5. Allowed lifecycle status
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[OfferVersionStatus.DRAFT, OfferVersionStatus.SUBMITTED]
                ),
                name="check_offer_version_valid_status",
            ),
            # 6. Allowed logistics cost status
            models.CheckConstraint(
                condition=models.Q(logistics_cost_status__in=LogisticsCostStatus.values),
                name="check_offer_version_valid_logistics_status",
            ),
            # 7. Logistics cost consistency
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE)
                        & models.Q(logistics_cost_amount__isnull=False)
                        & models.Q(logistics_cost_amount__gte=0)
                    )
                    | (
                        ~models.Q(logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE)
                        & models.Q(logistics_cost_amount__isnull=True)
                    )
                ),
                name="check_offer_version_logistics_cost_consistency",
            ),
            # 8. Delivery window validity: delivery_start <= delivery_end when both set
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_start__isnull=True)
                    | models.Q(delivery_end__isnull=True)
                    | models.Q(delivery_start__lte=models.F("delivery_end"))
                ),
                name="check_offer_version_delivery_window_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["offer", "status"], name="idx_offer_version_status"),
            models.Index(fields=["offer", "version_number"], name="idx_offer_version_num"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.offered_quantity is not None and self.offered_quantity <= Decimal("0"):
            errors["offered_quantity"] = "Offered quantity must be positive."

        if self.unit_price is not None and self.unit_price <= Decimal("0"):
            errors["unit_price"] = "Unit price must be positive."

        if self.delivery_start and self.delivery_end and self.delivery_start > self.delivery_end:
            errors["delivery_end"] = "Delivery start date cannot be after delivery end date."

        if self.logistics_cost_status == LogisticsCostStatus.KNOWN_SEPARATE:
            if self.logistics_cost_amount is None:
                errors["logistics_cost_amount"] = (
                    "logistics_cost_amount is required when logistics_cost_status is KNOWN_SEPARATE."
                )
            elif self.logistics_cost_amount < Decimal("0"):
                errors["logistics_cost_amount"] = "logistics_cost_amount cannot be negative."
        else:
            if self.logistics_cost_amount is not None:
                errors["logistics_cost_amount"] = (
                    f"logistics_cost_amount must be absent when logistics_cost_status is {self.logistics_cost_status}."
                )

        if self.offer_id and self.schema_version_id:
            rfq_schema_id = getattr(self.offer.rfq, "schema_version_id", None)
            if rfq_schema_id and self.schema_version_id != rfq_schema_id:
                errors["schema_version"] = "OfferVersion schema_version must match the RFQ schema_version."

        # Dynamic specifications validation
        if self.schema_version_id:
            try:
                validate_commodity_payload(self.schema_version, self.specifications or {})
            except ValidationError as exc:
                errors["specifications"] = f"Dynamic specifications validation failed: {exc}"

        # Unit compatibility check against RFQ
        if self.offer_id and self.quantity_unit:
            rfq_unit = getattr(self.offer.rfq, "unit", "")
            if rfq_unit and self.quantity_unit.strip().upper() != rfq_unit.strip().upper():
                errors["quantity_unit"] = (
                    f"Offer quantity unit '{self.quantity_unit}' is incompatible with RFQ unit '{rfq_unit}'."
                )

        # Submitted immutability check
        if self.pk and not self._state.adding:
            persisted = OfferVersion.objects.filter(pk=self.pk).first()
            if persisted and persisted.status == OfferVersionStatus.SUBMITTED:
                immutable_fields = [
                    "offer_id",
                    "version_number",
                    "schema_version_id",
                    "specifications",
                    "offered_quantity",
                    "quantity_unit",
                    "unit_price",
                    "currency",
                    "payment_terms",
                    "delivery_terms",
                    "incoterm",
                    "delivery_start",
                    "delivery_end",
                    "valid_until",
                    "logistics_cost_status",
                    "logistics_cost_amount",
                    "notes",
                    "status",
                    "created_by_id",
                    "submitted_by_id",
                    "submitted_at",
                ]
                changed_fields = [
                    f for f in immutable_fields if getattr(self, f) != getattr(persisted, f)
                ]
                if changed_fields:
                    raise ValidationError(
                        f"Submitted OfferVersion is immutable and cannot be modified: {', '.join(changed_fields)}"
                    )

        if self.status == OfferVersionStatus.SUBMITTED:
            if not self.submitted_by_id:
                errors["submitted_by"] = "submitted_by is required when submitting an OfferVersion."
            if not self.submitted_at:
                errors["submitted_at"] = "submitted_at is required when submitting an OfferVersion."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == OfferVersionStatus.SUBMITTED:
            raise ValidationError("Submitted OfferVersion cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"OfferVersion {self.offer_id} V{self.version_number} ({self.status})"


class OfferCostComponent(models.Model):
    """
    Immutable commercial snapshot child representing breakdown costs (Contract §27).

    - Kind: LOGISTICS or OTHER.
    - Amount: Strictly positive Decimal.
    - Currency: Must match parent OfferVersion currency.
    - Parent Immutability: Once parent OfferVersion is SUBMITTED, cost components
      cannot be added, modified, or deleted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.CASCADE,
        related_name="cost_components",
        help_text="Parent OfferVersion commercial snapshot.",
    )
    kind = models.CharField(
        max_length=20,
        choices=CostComponentKind.choices,
        help_text="Cost component kind (LOGISTICS or OTHER).",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Cost amount (strictly positive).",
    )
    currency = models.CharField(
        max_length=3,
        help_text="ISO 4217 3-letter currency code (must equal OfferVersion currency).",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Description or itemization notes for this cost component.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Offer Cost Component"
        verbose_name_plural = "Offer Cost Components"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="check_cost_component_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=CostComponentKind.values),
                name="check_cost_component_valid_kind",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.amount is not None and self.amount <= Decimal("0"):
            errors["amount"] = "Cost component amount must be positive."

        if self.offer_version_id:
            parent_version = self.offer_version
            if parent_version.currency and self.currency != parent_version.currency:
                errors["currency"] = (
                    f"Cost component currency '{self.currency}' must match "
                    f"OfferVersion currency '{parent_version.currency}'."
                )

            # Check if parent is submitted
            if parent_version.status == OfferVersionStatus.SUBMITTED:
                raise ValidationError(
                    "Cannot add or modify cost components on a submitted OfferVersion."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.offer_version.status == OfferVersionStatus.SUBMITTED:
            raise ValidationError("Cannot delete cost components from a submitted OfferVersion.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.kind} ({self.amount} {self.currency}) for {self.offer_version_id}"
