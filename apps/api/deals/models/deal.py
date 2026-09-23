import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Deal(models.Model):
    """
    Deal Aggregate Root (Epic 9 Contract §5, §6, T0901).

    Represents the durable commercial relationship identity materialized from
    a finalized AwardAllocation.

    Critical Invariants:
    - 1 AwardAllocation -> exactly 1 Deal (enforced via OneToOneField & DB unique constraint).
    - Multi-Award creates N distinct Deals; never collapses into a single multi-seller Deal.
    - Exactly One Economic Seller: either seller_organization XOR seller_external_counterparty.
      Both and neither are rejected at PostgreSQL CheckConstraint level.
    - Buyer Organization is strictly derived from the target RFQ owning Organization.
    - All commercial sources (Award, Allocation, RFQ, Offer, OfferVersion, Buyer, Seller)
      are guarded with on_delete=models.PROTECT to ensure historical preservation.
    - Normal product APIs expose no mutation (PATCH/DELETE) on Deals.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Source Award Aggregate
    award = models.ForeignKey(
        "offers.Award",
        on_delete=models.PROTECT,
        related_name="deals",
        help_text="Source Award aggregate.",
    )

    # 1:1 Award Allocation (Contract §5, §8)
    award_allocation = models.OneToOneField(
        "offers.AwardAllocation",
        on_delete=models.PROTECT,
        related_name="deal",
        help_text="Authoritative source AwardAllocation (1 allocation -> exactly 1 Deal).",
    )

    # Source RFQ Demand
    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        related_name="deals",
        help_text="Target RFQ for this commercial deal.",
    )

    # Source Offer & Exact OfferVersion Snapshot
    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="deals",
        help_text="Source Offer negotiation thread.",
    )
    offer_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        related_name="deals",
        help_text="Exact selected OfferVersion commercial snapshot.",
    )

    # Principal Parties (Contract §27, §28, §29)
    buyer_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="buyer_deals",
        help_text="Buyer Organization (authoritatively derived from RFQ.organization).",
    )

    # Economic Seller (mutually exclusive XOR)
    seller_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seller_deals",
        help_text="Internal seller organization (mutually exclusive with seller_external_counterparty).",
    )
    seller_external_counterparty = models.ForeignKey(
        "opportunities.ExternalCounterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deals",
        help_text="Off-platform external counterparty seller (mutually exclusive with seller_organization).",
    )

    # Audit & Materialization Provenance
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_deals",
        help_text="Platform user who authoritatively materialized this deal.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Deal"
        verbose_name_plural = "Deals"
        constraints = [
            # Exactly one economic seller (seller_organization XOR seller_external_counterparty)
            models.CheckConstraint(
                condition=(
                    (models.Q(seller_organization__isnull=False) & models.Q(seller_external_counterparty__isnull=True))
                    | (models.Q(seller_organization__isnull=True) & models.Q(seller_external_counterparty__isnull=False))
                ),
                name="check_deal_seller_exclusive",
            ),
        ]
        indexes = [
            models.Index(fields=["award"], name="idx_deal_award"),
            models.Index(fields=["rfq"], name="idx_deal_rfq"),
            models.Index(fields=["buyer_organization"], name="idx_deal_buyer_org"),
            models.Index(fields=["seller_organization"], name="idx_deal_seller_org"),
            models.Index(fields=["seller_external_counterparty"], name="idx_deal_seller_ext"),
            models.Index(fields=["-created_at"], name="idx_deal_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        # 1. Economic Seller XOR validation
        has_org = self.seller_organization_id is not None
        has_ext = self.seller_external_counterparty_id is not None
        if has_org == has_ext:
            errors["seller"] = "Deal must specify exactly one seller: seller_organization XOR seller_external_counterparty."

        # 2. Source Graph Referential Integrity
        if self.award_allocation_id:
            alloc = self.award_allocation
            if self.award_id and alloc.award_id != self.award_id:
                errors["award_allocation"] = "Referenced AwardAllocation does not belong to referenced Award."
            if self.offer_id and alloc.offer_id != self.offer_id:
                errors["offer"] = "Referenced Offer does not match AwardAllocation.offer."
            if self.offer_version_id and alloc.offer_version_id != self.offer_version_id:
                errors["offer_version"] = "Referenced OfferVersion does not match AwardAllocation.offer_version."

        if self.offer_version_id and self.offer_id:
            if self.offer_version.offer_id != self.offer_id:
                errors["offer_version"] = "Referenced OfferVersion does not belong to referenced Offer."

        if self.offer_id and self.rfq_id:
            if self.offer.rfq_id != self.rfq_id:
                errors["offer"] = "Referenced Offer targets a different RFQ."

        if self.award_id and self.rfq_id:
            if self.award.rfq_id != self.rfq_id:
                errors["award"] = "Referenced Award targets a different RFQ."

        if self.rfq_id and self.buyer_organization_id:
            if self.rfq.organization_id != self.buyer_organization_id:
                errors["buyer_organization"] = "Deal buyer_organization must equal RFQ owning organization."

        # 3. Seller provenance correspondence
        if self.offer_id:
            offer = self.offer
            if offer.offering_organization_id:
                if self.seller_organization_id != offer.offering_organization_id or self.seller_external_counterparty_id is not None:
                    errors["seller_organization"] = "Deal seller must equal Offer offering_organization."
            elif offer.external_counterparty_id:
                if self.seller_external_counterparty_id != offer.external_counterparty_id or self.seller_organization_id is not None:
                    errors["seller_external_counterparty"] = "Deal seller must equal Offer external_counterparty."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    @property
    def is_external(self) -> bool:
        """True if the commercial seller is an off-platform ExternalCounterparty."""
        return self.seller_external_counterparty_id is not None

    @property
    def seller(self):
        """Authoritative economic seller entity (Organization or ExternalCounterparty)."""
        return self.seller_organization or self.seller_external_counterparty

    @property
    def seller_display_name(self) -> str:
        """Human-readable display name of the seller."""
        if self.seller_organization_id:
            return getattr(self.seller_organization, "name", str(self.seller_organization_id))
        if self.seller_external_counterparty_id:
            return getattr(self.seller_external_counterparty, "company_name", str(self.seller_external_counterparty_id))
        return "Unknown"

    def __str__(self) -> str:
        return f"Deal {self.id} (Award {self.award_id}, Allocation {self.award_allocation_id})"
