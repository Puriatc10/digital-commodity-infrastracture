import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import TransportMode


class ExecutionLogistics(models.Model):
    """
    Execution Logistics Operational Tracking Aggregate (Epic 10 Contract §35–§42, T1004).

    Represents actual operational execution facts for an Execution instance.

    Invariants:
    - 1 Execution -> exactly 1 ExecutionLogistics record (OneToOneField & unique DB constraint).
    - Commercial truth separation: DealTermsSnapshot and DealCostSnapshot are NEVER mutated.
      ExecutionLogistics records what actually happened operationally; discrepancies are historically valid.
    - Transport mode is strictly one of TransportMode enum (ROAD, SEA, RAIL, AIR, MULTIMODAL, OTHER);
      never inferred automatically from geography or Incoterm.
    - Structured geography: uses GeographicArea foreign keys alongside operational location descriptions.
      No GPS or telematics.
    - Money: logistics_cost is strictly Decimal (no float). Explicit ISO-4217 currency is mandatory
      when logistics_cost is set. No FX conversion.
    - Time integrity: scheduled_loading_at, actual_loading_at, eta, actual_delivery_at represent
      authoritative operational facts. Obvious impossible chronology (actual_delivery_at < actual_loading_at)
      is strictly rejected.
    - Unknown preservation: missing operational facts remain null/empty without fabricated defaults.
    - Optimistic concurrency: mutations increment version and require expected_version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.OneToOneField(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="logistics",
        help_text="Parent execution instance (1 Execution -> max 1 ExecutionLogistics).",
    )
    carrier_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Carrier name or operational freight operator.",
    )
    transport_mode = models.CharField(
        max_length=20,
        choices=TransportMode.choices,
        blank=True,
        null=True,
        default=None,
        help_text="Canonical transport mode. Must not be inferred automatically.",
    )
    pickup_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Structured pickup geographic area reference.",
    )
    destination_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Structured destination geographic area reference.",
    )
    pickup_location = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Operational pickup facility description or local address.",
    )
    destination_location = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Operational destination facility description or local address.",
    )
    scheduled_loading_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled operational loading timestamp.",
    )
    actual_loading_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Reported actual operational loading timestamp.",
    )
    eta = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Estimated time of arrival (ETA) at destination.",
    )
    actual_delivery_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Reported actual operational delivery timestamp.",
    )
    transport_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Operational transport reference (e.g. B/L, CMR, tracking number).",
    )
    logistics_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual or reported operational logistics cost in Decimal.",
    )
    currency = models.CharField(
        max_length=3,
        blank=True,
        default="",
        help_text="ISO 4217 3-letter currency code for logistics cost.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Execution Logistics"
        verbose_name_plural = "Execution Logistics"
        constraints = [
            models.UniqueConstraint(
                fields=["execution"],
                name="unique_execution_logistics",
            ),
            models.CheckConstraint(
                condition=models.Q(transport_mode__isnull=True)
                | models.Q(transport_mode__in=TransportMode.values),
                name="check_valid_transport_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_logistics_version",
            ),
            models.CheckConstraint(
                condition=models.Q(logistics_cost__isnull=True)
                | models.Q(logistics_cost__gte=0),
                name="check_non_negative_logistics_cost",
            ),
        ]
        indexes = [
            models.Index(fields=["execution", "-created_at"], name="idx_exec_logistics_created"),
        ]

    @property
    def carrier(self) -> str:
        """Roadmap alias for carrier_name."""
        return self.carrier_name

    @carrier.setter
    def carrier(self, value: str) -> None:
        self.carrier_name = value or ""

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        # Immutability of execution reference
        if not self._state.adding:
            orig = ExecutionLogistics.objects.filter(pk=self.pk).first()
            if orig and orig.execution_id != self.execution_id:
                errors["execution"] = "Execution logistics execution reference is immutable."

        # Transport mode validation
        if self.transport_mode and self.transport_mode not in TransportMode.values:
            errors["transport_mode"] = f"Invalid transport mode '{self.transport_mode}'."

        # Money integrity: logistics_cost and currency dependency
        if self.logistics_cost is not None:
            if not isinstance(self.logistics_cost, Decimal):
                try:
                    self.logistics_cost = Decimal(str(self.logistics_cost))
                except Exception:
                    errors["logistics_cost"] = "Logistics cost must be a valid Decimal amount."

            if self.logistics_cost is not None and self.logistics_cost < 0:
                errors["logistics_cost"] = "Logistics cost must be non-negative."

            if not self.currency or len(self.currency.strip()) != 3:
                errors["currency"] = (
                    "Explicit ISO-4217 3-letter currency code is mandatory when logistics cost is specified."
                )
            else:
                self.currency = self.currency.strip().upper()
        else:
            if self.currency:
                self.currency = self.currency.strip().upper()

        # Time integrity: impossible chronology validation
        if self.actual_loading_at and self.actual_delivery_at:
            if self.actual_delivery_at < self.actual_loading_at:
                errors["actual_delivery_at"] = (
                    "Actual delivery timestamp cannot precede actual loading timestamp."
                )

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Logistics for Execution {self.execution_id} (mode={self.transport_mode or 'UNKNOWN'}, v={self.version})"
