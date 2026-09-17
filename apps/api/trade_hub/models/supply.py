from typing import Any
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SupplyListingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    CLOSED = "closed", "Closed"


class SupplyListingVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    NETWORK = "network", "Network"
    PRIVATE = "private", "Private"


class SupplyListingQuerySet(models.QuerySet):
    def visible_to(self, user: Any, organization: Any = None) -> "SupplyListingQuerySet":
        from trade_hub.services.visibility_service import get_visible_supply_listings

        return get_visible_supply_listings(user, organization=organization, base_queryset=self)


class SupplyListingManager(models.Manager.from_queryset(SupplyListingQuerySet)):
    pass


class SupplyListing(models.Model):
    """
    SupplyListing Aggregate Root.

    Represents a supplier organization's formal commodity supply listing,
    bound to an immutable commodity schema version and validated
    dynamic specifications JSONB.
    """

    objects = SupplyListingManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Supplier / Ownership
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="supply_listings",
        help_text="The supplier organization that owns this supply listing.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_supply_listings",
        help_text="The authenticated user who created this supply listing.",
    )
    created_by_operator = models.BooleanField(
        default=False,
        help_text="True if created by a platform operator on behalf of the supplier organization.",
    )

    # Commodity & Versioned Schema Linkage
    commodity = models.ForeignKey(
        "commodities.CommodityDefinition",
        on_delete=models.PROTECT,
        related_name="supply_listings",
        help_text="Referenced commodity definition.",
    )
    schema_version = models.ForeignKey(
        "commodities.CommoditySchemaVersion",
        on_delete=models.PROTECT,
        related_name="supply_listings",
        help_text="Exact immutable commodity schema version used to validate dynamic specifications.",
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic technical specifications validated against the referenced schema version.",
    )

    # Commercial & Supply Terms
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Supply quantity available (must be positive).",
    )
    unit = models.CharField(
        max_length=20,
        default="MT",
        help_text="Unit of measurement (e.g. MT, Barrels).",
    )
    indicative_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional indicative price per unit.",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        help_text="ISO 4217 3-letter currency code (e.g. USD, EUR).",
    )
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Indicative payment terms (e.g. LC, TT).",
    )
    incoterm = models.CharField(
        max_length=10,
        blank=True,
        help_text="Incoterm code (e.g. FOB, CIF, CFR).",
    )

    # Geography & Availability Window
    origin = models.CharField(
        max_length=255,
        blank=True,
        help_text="Origin location, facility, or port.",
    )
    destination = models.CharField(
        max_length=255,
        blank=True,
        help_text="Allowable destination country or port if restricted.",
    )
    origin_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supply_listings",
        help_text="Structured origin or supply geographic area.",
    )
    availability_window_start = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest availability date.",
    )
    availability_window_end = models.DateField(
        null=True,
        blank=True,
        help_text="Latest availability date.",
    )

    # Quality & Internal Notes
    quality_notes = models.TextField(
        blank=True,
        help_text="Quality, testing, or specification notes.",
    )
    notes = models.TextField(
        blank=True,
        help_text="General internal notes or comments (hidden from external counterparties).",
    )

    # Status & Visibility
    status = models.CharField(
        max_length=30,
        choices=SupplyListingStatus.choices,
        default=SupplyListingStatus.DRAFT,
        help_text="Current lifecycle state of the supply listing.",
    )
    visibility = models.CharField(
        max_length=20,
        choices=SupplyListingVisibility.choices,
        default=SupplyListingVisibility.PUBLIC,
        help_text="Participation visibility tier (public, network, private).",
    )

    # Optimistic Concurrency Foundation
    version = models.IntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    # Lifecycle Timestamps
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the supply listing was activated.",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the supply listing was closed.",
    )
    expired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the supply listing was marked expired.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        if "supplier" in kwargs and "organization" not in kwargs:
            kwargs["organization"] = kwargs.pop("supplier")
        super().__init__(*args, **kwargs)

    @property
    def supplier(self):
        """Alias for the owning supplier organization."""
        return self.organization

    @supplier.setter
    def supplier(self, value):
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

        # Availability window chronological ordering
        if self.availability_window_start and self.availability_window_end:
            if self.availability_window_end < self.availability_window_start:
                errors["availability_window_end"] = (
                    "Availability window end must be on or after availability window start."
                )

        # Numeric field invariants
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.indicative_price is not None and self.indicative_price < 0:
            errors["indicative_price"] = "Indicative price must be non-negative."

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        # Post-activation immutability enforcement
        if self.pk and not self._state.adding:
            persisted = (
                SupplyListing.objects.filter(pk=self.pk)
                .only(
                    "status",
                    "organization_id",
                    "commodity_id",
                    "schema_version_id",
                    "specifications",
                    "quantity",
                    "unit",
                    "indicative_price",
                    "currency",
                    "payment_terms",
                    "incoterm",
                    "origin",
                    "destination",
                    "availability_window_start",
                    "availability_window_end",
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
                    "indicative_price",
                    "currency",
                    "payment_terms",
                    "incoterm",
                    "origin",
                    "destination",
                    "availability_window_start",
                    "availability_window_end",
                    "quality_notes",
                    "created_by_id",
                    "created_by_operator",
                ]
                changed_core_fields = [
                    f for f in core_fields if getattr(self, f) != getattr(persisted, f)
                ]
                if changed_core_fields:
                    if persisted.status != SupplyListingStatus.DRAFT:
                        errors["core_fields"] = (
                            f"Core fields cannot be modified after activation: {', '.join(changed_core_fields)}"
                        )
                    elif self.status == SupplyListingStatus.ACTIVE:
                        errors["core_fields"] = (
                            f"Core fields cannot be modified during activation: {', '.join(changed_core_fields)}"
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
                condition=models.Q(status__in=[c[0] for c in SupplyListingStatus.choices]),
                name="check_valid_supply_listing_status",
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=[c[0] for c in SupplyListingVisibility.choices]),
                name="check_valid_supply_listing_visibility",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="check_positive_supply_listing_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(indicative_price__gte=0) | models.Q(indicative_price__isnull=True),
                name="check_positive_supply_listing_price",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_supply_listing_version",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(availability_window_end__gte=models.F("availability_window_start"))
                    | models.Q(availability_window_start__isnull=True)
                    | models.Q(availability_window_end__isnull=True)
                ),
                name="check_valid_supply_listing_availability_window",
            ),
        ]
        indexes = [
            models.Index(fields=["organization"], name="idx_supply_organization"),
            models.Index(fields=["commodity"], name="idx_supply_commodity"),
            models.Index(fields=["status", "visibility"], name="idx_supply_status_visibility"),
            models.Index(fields=["-created_at"], name="idx_supply_created_at_desc"),
        ]

    @property
    def supply_area(self):
        """Structured geographic area of supply, matching origin_area."""
        return self.origin_area

    def __str__(self):
        commodity_code = getattr(self.commodity, "code", "unknown")
        return f"SupplyListing {self.id} - {commodity_code} ({self.get_status_display()})"
