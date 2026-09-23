import uuid

from django.core.exceptions import ValidationError
from django.db import models


class PartyRole(models.TextChoices):
    """Principal commercial party role in a Deal (Contract §27, §30)."""

    BUYER = "BUYER", "Buyer"
    SELLER = "SELLER", "Seller"


class PartyType(models.TextChoices):
    """Backing entity type for a Deal party snapshot (Contract §30)."""

    ORGANIZATION = "ORGANIZATION", "Organization"
    EXTERNAL_COUNTERPARTY = "EXTERNAL_COUNTERPARTY", "External Counterparty"


class DealPartySnapshot(models.Model):
    """
    Immutable snapshot of a principal commercial party on a Deal (Contract §27-§32, T0902).

    Represents the durable commercial identity of the Buyer and Seller at Deal creation:
    - Exactly one BUYER and one SELLER per Deal (enforced via DB uniqueness constraint).
    - Backing reference XOR enforced at DB check constraint level:
        * ORGANIZATION: organization != null AND external_counterparty == null
        * EXTERNAL_COUNTERPARTY: organization == null AND external_counterparty != null
    - Minimal commercial identity only (name, country, registration_identifier).
      Never stores phone, email, credentials, capabilities, private notes, or verification files.
    - Strictly immutable once persisted; normal product APIs expose no mutation or deletion.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="party_snapshots",
        help_text="Parent Deal aggregate.",
    )

    role = models.CharField(
        max_length=20,
        choices=PartyRole.choices,
        help_text="Commercial principal role (BUYER or SELLER).",
    )
    party_type = models.CharField(
        max_length=30,
        choices=PartyType.choices,
        help_text="Backing entity type (ORGANIZATION or EXTERNAL_COUNTERPARTY).",
    )

    # Backing source references (mutually exclusive XOR based on party_type)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deal_party_snapshots",
        help_text="Backing platform Organization (required when party_type=ORGANIZATION).",
    )
    external_counterparty = models.ForeignKey(
        "opportunities.ExternalCounterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deal_party_snapshots",
        help_text="Backing off-platform ExternalCounterparty (required when party_type=EXTERNAL_COUNTERPARTY).",
    )

    # Minimal legal / commercial identity snapshot (Contract §31)
    name_snapshot = models.CharField(
        max_length=255,
        help_text="Commercial or legal entity name snapshot.",
    )
    country_snapshot = models.CharField(
        max_length=255,
        blank=True,
        help_text="Country or jurisdiction snapshot.",
    )
    registration_identifier_snapshot = models.CharField(
        max_length=255,
        blank=True,
        help_text="Business registration identifier snapshot.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["role"]
        verbose_name = "Deal Party Snapshot"
        verbose_name_plural = "Deal Party Snapshots"
        constraints = [
            # Exactly one BUYER and one SELLER per Deal
            models.UniqueConstraint(
                fields=["deal", "role"],
                name="unique_deal_party_role",
            ),
            # Valid party role
            models.CheckConstraint(
                condition=models.Q(role__in=PartyRole.values),
                name="check_deal_party_role_valid",
            ),
            # Valid party type
            models.CheckConstraint(
                condition=models.Q(party_type__in=PartyType.values),
                name="check_deal_party_type_valid",
            ),
            # Backing entity XOR: ORGANIZATION vs EXTERNAL_COUNTERPARTY
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(party_type=PartyType.ORGANIZATION)
                        & models.Q(organization__isnull=False)
                        & models.Q(external_counterparty__isnull=True)
                    )
                    | (
                        models.Q(party_type=PartyType.EXTERNAL_COUNTERPARTY)
                        & models.Q(organization__isnull=True)
                        & models.Q(external_counterparty__isnull=False)
                    )
                ),
                name="check_deal_party_backing_exclusive",
            ),
        ]
        indexes = [
            models.Index(fields=["deal", "role"], name="idx_deal_party_role"),
            models.Index(fields=["organization"], name="idx_deal_party_org"),
            models.Index(fields=["external_counterparty"], name="idx_deal_party_ext"),
            models.Index(fields=["created_at"], name="idx_deal_party_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.role not in PartyRole.values:
            errors["role"] = f"Invalid party role '{self.role}'. Must be BUYER or SELLER."

        if self.party_type not in PartyType.values:
            errors["party_type"] = f"Invalid party type '{self.party_type}'."

        if self.party_type == PartyType.ORGANIZATION:
            if not self.organization_id or self.external_counterparty_id is not None:
                errors["organization"] = (
                    "Organization party snapshot must specify organization and not external_counterparty."
                )
        elif self.party_type == PartyType.EXTERNAL_COUNTERPARTY:
            if not self.external_counterparty_id or self.organization_id is not None:
                errors["external_counterparty"] = (
                    "External counterparty party snapshot must specify external_counterparty and not organization."
                )

        if not self.name_snapshot or not self.name_snapshot.strip():
            errors["name_snapshot"] = "name_snapshot cannot be empty."

        # Immutability enforcement: reject any modification once persisted
        if self.pk and not self._state.adding:
            persisted = DealPartySnapshot.objects.filter(pk=self.pk).first()
            if persisted:
                raise ValidationError("DealPartySnapshot is immutable and cannot be updated.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("DealPartySnapshot is immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"DealPartySnapshot {self.role} for Deal {self.deal_id}: {self.name_snapshot} ({self.party_type})"
