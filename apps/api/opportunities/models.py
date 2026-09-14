import uuid

from django.conf import settings
from django.db import models


class ExternalCounterparty(models.Model):
    """
    Represents an off-platform real-world commercial counterparty recorded by an Operator.

    Critical Invariant:
        ExternalCounterparty != User
        ExternalCounterparty != Organization

    This entity does NOT create or require a platform User, Organization,
    OrganizationMembership, or OrganizationCapability row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core commercial & contact fields (Product Specification §21)
    company_name = models.CharField(
        max_length=255,
        help_text="Display or legal entity name of the external counterparty.",
    )
    contact_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the individual representative or contact person.",
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone number for operational contact.",
    )
    email = models.EmailField(
        max_length=254,
        blank=True,
        help_text="Email address for operational contact.",
    )
    geography = models.CharField(
        max_length=255,
        blank=True,
        help_text="Country, port, or regional jurisdiction.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Free-form operational notes by the Operator.",
    )

    # Internal actor tracking (nullable: can exist without platform user)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_external_counterparties",
        help_text="Operator who recorded this external counterparty (null if unassigned/system).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "External Counterparty"
        verbose_name_plural = "External Counterparties"
        indexes = [
            models.Index(fields=["company_name"], name="idx_ext_cp_company_name"),
            models.Index(fields=["-created_at"], name="idx_ext_cp_created_at_desc"),
        ]

    def __str__(self):
        if self.contact_name:
            return f"{self.company_name} ({self.contact_name})"
        return self.company_name


class OpportunityDirection(models.TextChoices):
    SUPPLY = "Supply", "Supply"
    DEMAND = "Demand", "Demand"


class OpportunityStatus(models.TextChoices):
    CAPTURED = "Captured", "Captured"


class Opportunity(models.Model):
    """
    Foundational Opportunity aggregate for Market Discovery / Opportunity Desk.

    Represents a trade lead with a concrete trade direction (Supply or Demand)
    and a mutually exclusive counterparty (internal Organization or off-platform
    ExternalCounterparty).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Direction (Spec §17: Supply or Demand)
    direction = models.CharField(
        max_length=10,
        choices=OpportunityDirection.choices,
        help_text="Trade direction: Supply or Demand.",
    )

    # Counterparty Relationship (mutually exclusive: exactly one required)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Internal registered platform organization (mutually exclusive with external_counterparty).",
    )
    external_counterparty = models.ForeignKey(
        ExternalCounterparty,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Off-platform external counterparty (mutually exclusive with organization).",
    )

    # Commodity (generic reference, no commodity-specific branches)
    commodity = models.ForeignKey(
        "commodities.CommodityDefinition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Referenced commodity definition.",
    )

    # Commercial & Quantity Terms
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Lead quantity (must be positive if specified).",
    )
    unit = models.CharField(
        max_length=20,
        default="MT",
        blank=True,
        help_text="Unit of measurement.",
    )
    indicative_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Indicative or target unit price.",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        blank=True,
        help_text="ISO 4217 currency code.",
    )

    # Delivery & Geography
    delivery_window_start = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest expected delivery date.",
    )
    delivery_window_end = models.DateField(
        null=True,
        blank=True,
        help_text="Latest expected delivery date.",
    )
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Indicative payment terms.",
    )
    geography = models.CharField(
        max_length=255,
        blank=True,
        help_text="Origin/destination region, country, or port.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal operational notes.",
    )

    # Foundational Lifecycle State (T0603 owns transitions; default Captured)
    status = models.CharField(
        max_length=30,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.CAPTURED,
        help_text="Foundational lifecycle state.",
    )

    # Internal Actor Tracking & Timestamps
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_opportunities",
        help_text="Operator who recorded this opportunity.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Opportunity"
        verbose_name_plural = "Opportunities"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(direction__in=["Supply", "Demand"]),
                name="check_valid_opportunity_direction",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(organization__isnull=False) & models.Q(external_counterparty__isnull=True))
                    | (models.Q(organization__isnull=True) & models.Q(external_counterparty__isnull=False))
                ),
                name="check_opportunity_counterparty_exclusive",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) | models.Q(quantity__isnull=True),
                name="check_positive_opportunity_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(indicative_price__gte=0) | models.Q(indicative_price__isnull=True),
                name="check_non_negative_opportunity_indicative_price",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[OpportunityStatus.CAPTURED]),
                name="check_valid_opportunity_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_window_end__gte=models.F("delivery_window_start"))
                    | models.Q(delivery_window_start__isnull=True)
                    | models.Q(delivery_window_end__isnull=True)
                ),
                name="check_valid_opportunity_delivery_window",
            ),
        ]
        indexes = [
            models.Index(fields=["direction"], name="idx_opp_direction"),
            models.Index(fields=["status"], name="idx_opp_status"),
            models.Index(fields=["organization"], name="idx_opp_organization"),
            models.Index(fields=["external_counterparty"], name="idx_opp_ext_counterparty"),
            models.Index(fields=["commodity"], name="idx_opp_commodity"),
            models.Index(fields=["-created_at"], name="idx_opp_created_at_desc"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.direction not in [OpportunityDirection.SUPPLY, OpportunityDirection.DEMAND]:
            errors["direction"] = "Direction must be either 'Supply' or 'Demand'."

        if self.organization_id and self.external_counterparty_id:
            errors["counterparty"] = "Opportunity cannot reference both an internal Organization and an ExternalCounterparty."
        elif not self.organization_id and not self.external_counterparty_id:
            errors["counterparty"] = "Opportunity must reference either an internal Organization or an ExternalCounterparty."

        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.indicative_price is not None and self.indicative_price < 0:
            errors["indicative_price"] = "Indicative price must be non-negative."

        if self.delivery_window_start and self.delivery_window_end:
            if self.delivery_window_end < self.delivery_window_start:
                errors["delivery_window_end"] = "Delivery window end must be on or after delivery window start."

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        counterparty = self.organization.name if self.organization else str(self.external_counterparty)
        return f"Opportunity {self.id} [{self.direction}] - {counterparty}"
