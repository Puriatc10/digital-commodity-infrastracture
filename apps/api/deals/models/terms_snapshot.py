from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from offers.enums import CostComponentKind, LogisticsCostStatus


class DealTermsSnapshot(models.Model):
    """
    Immutable commercial terms snapshot of a Deal (Epic 9 Contract §13, §69, T0902).

    Represents the durable accepted commercial truth at Deal creation time:
    - Exact awarded quantity from AwardAllocation.awarded_quantity (never offered_quantity).
    - Unit price, currency, payment terms, delivery terms, and Incoterm from exact selected OfferVersion.
    - Historical CommoditySchemaVersion and deep-copied specifications JSONB.
    - Product cost snapshot computed using strictly Decimal arithmetic.
    - Logistics cost status and separate logistics amount (UNKNOWN preserved as non-numeric uncertainty).
    - Strictly immutable once persisted; normal product APIs expose no mutation or deletion.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 1:1 Deal Aggregate Linkage (Contract §13)
    deal = models.OneToOneField(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="terms_snapshot",
        help_text="Parent Deal aggregate for this terms snapshot.",
    )

    # Commodity & Historical Schema Lock (Contract §23, §71)
    commodity = models.ForeignKey(
        "commodities.CommodityDefinition",
        on_delete=models.PROTECT,
        related_name="deal_terms_snapshots",
        help_text="Referenced commodity definition.",
    )
    schema_version = models.ForeignKey(
        "commodities.CommoditySchemaVersion",
        on_delete=models.PROTECT,
        related_name="deal_terms_snapshots",
        help_text="Exact immutable schema version bound at offer/deal creation time.",
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Canonical deep-copy snapshot of accepted dynamic specifications JSONB.",
    )

    # Commercial Quantities (Contract §15)
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Awarded commercial quantity (strictly positive Decimal from AwardAllocation.awarded_quantity).",
    )
    quantity_unit = models.CharField(
        max_length=20,
        help_text="Commercial unit of measurement from AwardAllocation/OfferVersion.",
    )

    # Commercial Price & Currency (Contract §16, §17, §18)
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Accepted unit price from exact selected OfferVersion.",
    )
    currency = models.CharField(
        max_length=3,
        help_text="ISO 4217 3-letter currency code from exact selected OfferVersion.",
    )
    product_cost_snapshot = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        help_text="Exact Decimal snapshot of unit_price * quantity.",
    )

    # Payment & Commercial Delivery Terms (Contract §21, §22)
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Accepted payment terms from OfferVersion.",
    )
    delivery_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Accepted delivery terms from OfferVersion.",
    )
    incoterm = models.CharField(
        max_length=10,
        blank=True,
        help_text="Accepted Incoterm from OfferVersion.",
    )
    delivery_start = models.DateField(
        null=True,
        blank=True,
        help_text="Accepted earliest delivery date from OfferVersion.",
    )
    delivery_end = models.DateField(
        null=True,
        blank=True,
        help_text="Accepted latest delivery date from OfferVersion.",
    )

    # Origin & Destination Context from RFQ (Contract §22)
    origin = models.CharField(
        max_length=255,
        blank=True,
        help_text="Origin location snapshot if present in RFQ context.",
    )
    destination = models.CharField(
        max_length=255,
        blank=True,
        help_text="Destination location snapshot if present in RFQ context.",
    )
    origin_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Origin geographic area reference if present.",
    )
    destination_area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Destination geographic area reference if present.",
    )

    # Logistics Cost (Contract §19, §20)
    logistics_cost_status = models.CharField(
        max_length=20,
        choices=LogisticsCostStatus.choices,
        default=LogisticsCostStatus.UNKNOWN,
        help_text="Logistics cost knowledge status.",
    )
    logistics_cost_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Separate logistics cost amount if KNOWN_SEPARATE.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Deal Terms Snapshot"
        verbose_name_plural = "Deal Terms Snapshots"
        constraints = [
            # 1. Strictly positive awarded quantity
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="check_deal_terms_quantity_positive",
            ),
            # 2. Strictly positive unit price
            models.CheckConstraint(
                condition=models.Q(unit_price__gt=0),
                name="check_deal_terms_unit_price_positive",
            ),
            # 3. Strictly positive product cost snapshot
            models.CheckConstraint(
                condition=models.Q(product_cost_snapshot__gt=0),
                name="check_deal_terms_product_cost_positive",
            ),
            # 4. Valid logistics cost status
            models.CheckConstraint(
                condition=models.Q(logistics_cost_status__in=LogisticsCostStatus.values),
                name="check_deal_terms_valid_logistics_status",
            ),
            # 5. Logistics cost consistency: KNOWN_SEPARATE requires amount >= 0; others require null
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
                name="check_deal_terms_logistics_cost_consistency",
            ),
            # 6. Delivery window consistency: delivery_start <= delivery_end when both set
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_start__isnull=True)
                    | models.Q(delivery_end__isnull=True)
                    | models.Q(delivery_start__lte=models.F("delivery_end"))
                ),
                name="check_deal_terms_delivery_window_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["deal"], name="idx_deal_terms_deal"),
            models.Index(fields=["commodity"], name="idx_deal_terms_commodity"),
            models.Index(fields=["schema_version"], name="idx_deal_terms_schema"),
            models.Index(fields=["-created_at"], name="idx_deal_terms_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.quantity is not None and self.quantity <= Decimal("0"):
            errors["quantity"] = "Deal terms quantity must be strictly positive."

        if self.unit_price is not None and self.unit_price <= Decimal("0"):
            errors["unit_price"] = "Deal terms unit price must be strictly positive."

        if self.product_cost_snapshot is not None and self.product_cost_snapshot <= Decimal("0"):
            errors["product_cost_snapshot"] = "Product cost snapshot must be strictly positive."

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

        # Immutability enforcement: reject any modification once persisted
        if self.pk and not self._state.adding:
            persisted = DealTermsSnapshot.objects.filter(pk=self.pk).first()
            if persisted:
                raise ValidationError("DealTermsSnapshot is immutable and cannot be updated.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("DealTermsSnapshot is immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"DealTermsSnapshot for Deal {self.deal_id} ({self.quantity} {self.quantity_unit} @ {self.unit_price} {self.currency})"


class DealCostSnapshot(models.Model):
    """
    Immutable commercial child snapshot representing breakdown costs (Contract §19, §70, T0902).

    Deep-copied independently from OfferCostComponent records at materialization time:
    - Never maintains a live foreign key to mutable OfferCostComponent.
    - Kind: LOGISTICS or OTHER.
    - Amount: Strictly positive Decimal.
    - Currency: Matches parent DealTermsSnapshot currency.
    - Strictly immutable once persisted; normal product APIs expose no mutation or deletion.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    deal_terms_snapshot = models.ForeignKey(
        DealTermsSnapshot,
        on_delete=models.PROTECT,
        related_name="cost_snapshots",
        help_text="Parent DealTermsSnapshot.",
    )

    kind = models.CharField(
        max_length=20,
        choices=CostComponentKind.choices,
        help_text="Cost component kind (LOGISTICS or OTHER).",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Cost amount (strictly positive Decimal).",
    )
    currency = models.CharField(
        max_length=3,
        help_text="ISO 4217 3-letter currency code (must match Deal terms currency).",
    )
    description_snapshot = models.CharField(
        max_length=255,
        blank=True,
        help_text="Description or itemization note snapshot.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Deal Cost Snapshot"
        verbose_name_plural = "Deal Cost Snapshots"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="check_deal_cost_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=CostComponentKind.values),
                name="check_deal_cost_valid_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["deal_terms_snapshot"], name="idx_deal_cost_terms"),
            models.Index(fields=["created_at"], name="idx_deal_cost_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.amount is not None and self.amount <= Decimal("0"):
            errors["amount"] = "Cost snapshot amount must be strictly positive."

        if self.kind not in CostComponentKind.values:
            errors["kind"] = f"Invalid cost component kind '{self.kind}'."

        if self.deal_terms_snapshot_id:
            parent_currency = getattr(self.deal_terms_snapshot, "currency", "")
            if parent_currency and self.currency != parent_currency:
                errors["currency"] = (
                    f"Cost snapshot currency '{self.currency}' must match "
                    f"Deal terms currency '{parent_currency}'."
                )

        # Immutability enforcement: reject any modification once persisted
        if self.pk and not self._state.adding:
            persisted = DealCostSnapshot.objects.filter(pk=self.pk).first()
            if persisted:
                raise ValidationError("DealCostSnapshot is immutable and cannot be updated.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("DealCostSnapshot is immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"DealCostSnapshot {self.kind} ({self.amount} {self.currency}) for Terms {self.deal_terms_snapshot_id}"
