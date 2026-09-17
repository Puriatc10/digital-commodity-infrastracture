from typing import Any
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RFQStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    COLLECTING_OFFERS = "collecting_offers", "Collecting Offers"
    NEGOTIATING = "negotiating", "Negotiating"
    AWARDED = "awarded", "Awarded"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class RFQVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    NETWORK = "network", "Network"
    PRIVATE = "private", "Private"


class GeographyConstraintMode(models.TextChoices):
    REQUIRED = "REQUIRED", "Required"
    ALLOWED = "ALLOWED", "Allowed"
    PREFERRED = "PREFERRED", "Preferred"
    EXCLUDED = "EXCLUDED", "Excluded"


class RFQQuerySet(models.QuerySet):
    def visible_to(self, user: Any, organization: Any = None) -> "RFQQuerySet":
        from trade_hub.services.visibility_service import get_visible_rfqs

        return get_visible_rfqs(user, organization=organization, base_queryset=self)


class RFQManager(models.Manager.from_queryset(RFQQuerySet)):
    pass


class RFQ(models.Model):
    """
    RFQ (Request for Quotation) Aggregate Root.

    Represents a buyer organization's formal procurement demand for a specific
    commodity, bound to an immutable commodity schema version and validated
    dynamic specifications JSONB.
    """

    objects = RFQManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Buyer / Ownership
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="rfqs",
        help_text="The buyer organization that owns this RFQ.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_rfqs",
        help_text="The authenticated user who created this RFQ.",
    )
    created_by_operator = models.BooleanField(
        default=False,
        help_text="True if created by a platform operator on behalf of the buyer organization.",
    )

    # Commodity & Versioned Schema Linkage
    commodity = models.ForeignKey(
        "commodities.CommodityDefinition",
        on_delete=models.PROTECT,
        related_name="rfqs",
        help_text="Referenced commodity definition.",
    )
    schema_version = models.ForeignKey(
        "commodities.CommoditySchemaVersion",
        on_delete=models.PROTECT,
        related_name="rfqs",
        help_text="Exact immutable commodity schema version used to validate dynamic specifications.",
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic technical specifications validated against the referenced schema version.",
    )

    # Commercial Terms
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Procurement quantity (must be positive).",
    )
    unit = models.CharField(
        max_length=20,
        default="MT",
        help_text="Unit of measurement (e.g. MT, Barrels).",
    )
    target_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional target price per unit.",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="ISO 4217 3-letter currency code (e.g. USD, EUR).",
    )
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Requested payment terms (e.g. LC, TT).",
    )
    incoterm = models.CharField(
        max_length=10,
        blank=True,
        help_text="Incoterm code (e.g. FOB, CIF, CFR).",
    )

    # Delivery Terms
    origin = models.CharField(
        max_length=255,
        blank=True,
        help_text="Requested origin country or port.",
    )
    destination = models.CharField(
        max_length=255,
        blank=True,
        help_text="Requested destination country or port.",
    )
    origin_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rfqs_as_origin",
        help_text="Structured origin geographic area.",
    )
    destination_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rfqs_as_destination",
        help_text="Structured destination geographic area.",
    )
    delivery_window_start = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest acceptable delivery date.",
    )
    delivery_window_end = models.DateField(
        null=True,
        blank=True,
        help_text="Latest acceptable delivery date.",
    )
    submission_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Offer submission deadline.",
    )

    # Quality & Inspection
    inspection_required = models.BooleanField(
        default=False,
        help_text="Whether third-party quality inspection is required.",
    )
    quality_notes = models.TextField(
        blank=True,
        help_text="Quality, testing, or inspection instructions.",
    )
    notes = models.TextField(
        blank=True,
        help_text="General procurement notes or comments.",
    )

    # Status & Visibility
    status = models.CharField(
        max_length=30,
        choices=RFQStatus.choices,
        default=RFQStatus.DRAFT,
        help_text="Current lifecycle state of the RFQ.",
    )
    visibility = models.CharField(
        max_length=20,
        choices=RFQVisibility.choices,
        default=RFQVisibility.PRIVATE,
        help_text="Participation visibility tier (private, network, public).",
    )

    # Optimistic Concurrency Foundation
    version = models.IntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    # Lifecycle Timestamps & Administrative Metadata
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the RFQ was published.",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the RFQ was closed.",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the RFQ was cancelled.",
    )
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Reason provided when the RFQ was cancelled.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        if "buyer" in kwargs and "organization" not in kwargs:
            kwargs["organization"] = kwargs.pop("buyer")
        super().__init__(*args, **kwargs)

    @property
    def buyer(self):
        """Alias for the owning buyer organization."""
        return self.organization

    @buyer.setter
    def buyer(self, value):
        self.organization = value

    @property
    def source_opportunity_safe(self):
        """Safely returns the originating Opportunity if converted, or None."""
        try:
            return self.source_opportunity
        except Exception:
            return None

    def clean(self):
        super().clean()
        errors = {}

        # Cross-table commodity and schema version integrity
        if self.commodity_id and self.schema_version_id:
            if self.schema_version.commodity_id != self.commodity_id:
                errors["schema_version"] = "Schema version does not belong to the referenced commodity."

        # Delivery window chronological ordering
        if self.delivery_window_start and self.delivery_window_end:
            if self.delivery_window_end < self.delivery_window_start:
                errors["delivery_window_end"] = "Delivery window end must be on or after delivery window start."

        # Numeric field invariants
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.target_price is not None and self.target_price < 0:
            errors["target_price"] = "Target price must be non-negative."

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        # Post-publication immutability enforcement
        if self.pk and not self._state.adding:
            persisted = (
                RFQ.objects.filter(pk=self.pk)
                .only(
                    "status",
                    "organization_id",
                    "commodity_id",
                    "schema_version_id",
                    "specifications",
                    "quantity",
                    "unit",
                    "target_price",
                    "currency",
                    "payment_terms",
                    "incoterm",
                    "origin",
                    "destination",
                    "delivery_window_start",
                    "delivery_window_end",
                    "inspection_required",
                    "quality_notes",
                    "created_by_id",
                    "created_by_operator",
                )
                .first()
            )
            if persisted:
                core_fields = [
                    "organization_id",
                    "commodity_id",
                    "schema_version_id",
                    "specifications",
                    "quantity",
                    "unit",
                    "target_price",
                    "currency",
                    "payment_terms",
                    "incoterm",
                    "origin",
                    "destination",
                    "delivery_window_start",
                    "delivery_window_end",
                    "inspection_required",
                    "quality_notes",
                    "created_by_id",
                    "created_by_operator",
                ]
                changed_core_fields = [
                    f for f in core_fields if getattr(self, f) != getattr(persisted, f)
                ]
                if changed_core_fields:
                    if persisted.status != RFQStatus.DRAFT:
                        errors["core_fields"] = (
                            f"Core fields cannot be modified after publication: {', '.join(changed_core_fields)}"
                        )
                    elif self.status == RFQStatus.PUBLISHED:
                        errors["core_fields"] = (
                            f"Core fields cannot be modified during publication: {', '.join(changed_core_fields)}"
                        )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in RFQStatus.choices]),
                name="check_valid_rfq_status",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=[c[0] for c in RFQVisibility.choices]),
                name="check_valid_rfq_visibility",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="check_positive_rfq_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(target_price__gte=0) | models.Q(target_price__isnull=True),
                name="check_positive_rfq_target_price",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_rfq_version",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_window_end__gte=models.F("delivery_window_start"))
                    | models.Q(delivery_window_start__isnull=True)
                    | models.Q(delivery_window_end__isnull=True)
                ),
                name="check_valid_rfq_delivery_window",
            ),
        ]
        indexes = [
            models.Index(fields=["organization"], name="idx_rfq_organization"),
            models.Index(fields=["commodity"], name="idx_rfq_commodity"),
            models.Index(fields=["status", "visibility"], name="idx_rfq_status_visibility"),
            models.Index(fields=["-created_at"], name="idx_rfq_created_at_desc"),
        ]

    def __str__(self):
        commodity_code = getattr(self.commodity, "code", "unknown")
        return f"RFQ {self.id} - {commodity_code} ({self.get_status_display()})"


class RFQGeographyConstraint(models.Model):
    """
    Structured geographic constraint or preference attached to an RFQ.

    Supports REQUIRED, ALLOWED, PREFERRED, and EXCLUDED modes with multi-area ANY-OF semantics.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.CASCADE,
        related_name="geography_constraints",
        help_text="Target RFQ.",
    )
    mode = models.CharField(
        max_length=20,
        choices=GeographyConstraintMode.choices,
        default=GeographyConstraintMode.REQUIRED,
        help_text="Constraint mode: REQUIRED, ALLOWED, PREFERRED, or EXCLUDED.",
    )
    area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.CASCADE,
        related_name="rfq_constraints",
        help_text="Referenced geographic area.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "mode", "area"],
                name="unique_rfq_geography_constraint",
            )
        ]
        indexes = [
            models.Index(fields=["rfq", "mode"], name="idx_rfq_geo_mode"),
        ]

    def __str__(self):
        return f"RFQ {self.rfq_id} - {self.mode} {self.area_id}"
