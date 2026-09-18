import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from offers.enums import OfferorRole


class Offer(models.Model):
    """
    Offer Aggregate Root (Spec P1-P4, Epic 8 Contract §6).

    Represents the stable negotiation identity against an RFQ for a given
    economic party and offeror role. Commercial proposals and terms are
    strictly decoupled into immutable OfferVersion records (Epic 8 T0802).

    Critical Invariants:
    - Target: Always targets exactly one RFQ.
    - Exactly One Economic Party: Either offering_organization XOR external_counterparty.
      Both and neither are rejected at PostgreSQL CheckConstraint level.
    - Offeror Role: Exactly SUPPLIER or BROKER (no TRADER).
    - Uniqueness: (rfq, offering_organization, offeror_role) and
      (rfq, external_counterparty, offeror_role) are unique via conditional DB constraints.
    - Historical Safety: Deletions are guarded with models.PROTECT on all FKs.
    - Optimistic Concurrency: aggregate_version initialized to 1 following platform convention.
    - Creator Authenticity: created_by is derived from the server-authenticated actor.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # RFQ Target (Epic 8 Contract §6, P1)
    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        related_name="offers",
        help_text="Target RFQ for this offer thread.",
    )

    # Commercial Role (SUPPLIER or BROKER)
    offeror_role = models.CharField(
        max_length=20,
        choices=OfferorRole.choices,
        help_text="Role assumed by the offeror (SUPPLIER or BROKER).",
    )

    # Economic Party (mutually exclusive: exactly one required)
    offering_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="offers",
        help_text="Internal platform organization making the offer (mutually exclusive with external_counterparty).",
    )
    external_counterparty = models.ForeignKey(
        "opportunities.ExternalCounterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="offers",
        help_text="Off-platform external counterparty for operator-entered offers (mutually exclusive with offering_organization).",
    )

    # Provenance Context (Contract §20)
    source_opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="offers",
        help_text="Originating lead/opportunity provenance context.",
    )

    # Current Submitted Version Snapshot (Epic 8 Contract §6, §35)
    current_submitted_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Currently active submitted OfferVersion commercial snapshot.",
    )

    # Optimistic Concurrency Foundation (Contract §6, §76)
    aggregate_version = models.IntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    # Internal Actor Tracking & Audit Timestamps
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_offers",
        help_text="Platform user who recorded or entered the offer.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Offer"
        verbose_name_plural = "Offers"
        constraints = [
            # 1. Exactly one economic party (offering_organization XOR external_counterparty)
            models.CheckConstraint(
                condition=(
                    (models.Q(offering_organization__isnull=False) & models.Q(external_counterparty__isnull=True))
                    | (models.Q(offering_organization__isnull=True) & models.Q(external_counterparty__isnull=False))
                ),
                name="check_offer_economic_party_exclusive",
            ),
            # 2. Offeror role must be strictly SUPPLIER or BROKER
            models.CheckConstraint(
                condition=models.Q(offeror_role__in=[OfferorRole.SUPPLIER, OfferorRole.BROKER]),
                name="check_offer_valid_offeror_role",
            ),
            # 3. Conditional uniqueness for internal organization offer threads
            models.UniqueConstraint(
                fields=["rfq", "offering_organization", "offeror_role"],
                condition=models.Q(offering_organization__isnull=False),
                name="unique_offer_rfq_organization_role",
            ),
            # 4. Conditional uniqueness for external counterparty offer threads
            models.UniqueConstraint(
                fields=["rfq", "external_counterparty", "offeror_role"],
                condition=models.Q(external_counterparty__isnull=False),
                name="unique_offer_rfq_external_counterparty_role",
            ),
        ]
        indexes = [
            models.Index(fields=["rfq", "-created_at"], name="idx_offer_rfq_created_at"),
            models.Index(fields=["offering_organization"], name="idx_offer_offering_org"),
            models.Index(fields=["external_counterparty"], name="idx_offer_ext_counterparty"),
            models.Index(fields=["source_opportunity"], name="idx_offer_source_opp"),
        ]

    def clean(self):
        super().clean()
        has_org = self.offering_organization_id is not None
        has_ext = self.external_counterparty_id is not None
        if has_org == has_ext:
            raise ValidationError(
                "Offer must specify exactly one economic party: offering_organization XOR external_counterparty."
            )
        if self.offeror_role not in [OfferorRole.SUPPLIER, OfferorRole.BROKER]:
            raise ValidationError(
                f"Invalid offeror role '{self.offeror_role}'. Must be SUPPLIER or BROKER."
            )
        if self.current_submitted_version_id is not None:
            from offers.enums import OfferVersionStatus

            current_v = self.current_submitted_version
            if current_v:
                if current_v.offer_id != self.id:
                    raise ValidationError(
                        "current_submitted_version must belong to this offer."
                    )
                if current_v.status != OfferVersionStatus.SUBMITTED:
                    raise ValidationError(
                        "current_submitted_version must be in SUBMITTED status."
                    )

    def save(self, *args, **kwargs):
        if self.current_submitted_version_id is not None:
            from offers.enums import OfferVersionStatus

            current_v = self.current_submitted_version
            if current_v:
                if current_v.offer_id != self.id:
                    raise ValidationError(
                        "current_submitted_version must belong to this offer."
                    )
                if current_v.status != OfferVersionStatus.SUBMITTED:
                    raise ValidationError(
                        "current_submitted_version must be in SUBMITTED status."
                    )
        super().save(*args, **kwargs)

    @property
    def version(self) -> int:
        """Alias for aggregate_version adhering to repository optimistic concurrency convention."""
        return self.aggregate_version

    @property
    def is_external(self) -> bool:
        """True if this offer represents an off-platform external counterparty."""
        return self.external_counterparty_id is not None

    @property
    def economic_party(self):
        """Returns the owning economic entity (Organization or ExternalCounterparty)."""
        return self.offering_organization or self.external_counterparty

    def __str__(self):
        party_name = (
            self.offering_organization.name
            if self.offering_organization_id
            else (
                self.external_counterparty.company_name
                if self.external_counterparty_id
                else "Unknown"
            )
        )
        return f"Offer {self.id} for RFQ {self.rfq_id} ({party_name} as {self.offeror_role})"
