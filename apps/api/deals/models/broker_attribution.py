import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class DealBrokerRole(models.TextChoices):
    SUPPLY_ORIGINATOR = "SUPPLY_ORIGINATOR", "Supply Originator"
    DEMAND_ORIGINATOR = "DEMAND_ORIGINATOR", "Demand Originator"


class DealBrokerAttribution(models.Model):
    """
    DealBrokerAttribution Entity (Epic 9 Contract §52-§59, T0904).

    Persists explicit Broker provenance for a Deal:
        Deal -> DealBrokerAttribution(s)

    Critical Invariants:
    - Provenance Only: Broker attribution is provenance, NOT Deal party identity, ACL,
      commission, referral fee, trust score, or economics.
    - Role Choices: Exactly SUPPLY_ORIGINATOR or DEMAND_ORIGINATOR (strictly no generic Broker role).
    - Multiple Brokers: A Deal may have multiple Broker rows when supported by explicit source evidence
      (e.g. Broker A as Demand Originator, Broker B as Supply Originator, or same Broker in both roles).
    - Deduplication: Semantic uniqueness on (deal, broker_organization, role, related_opportunity).
      Uses PostgreSQL `nulls_distinct=False` so duplicate rows with NULL related_opportunity are strictly rejected.
    - No Capability Inference: Must NOT be created merely because an organization possesses Broker capability;
      strictly requires explicit persisted source provenance.
    - Historical Stability: Removing an organization's Broker capability or updating Opportunity metadata
      does NOT mutate or delete historical DealBrokerAttribution records.
    - No Access: Attributed Brokers that are not the Deal Seller have zero read/write access to the Deal.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Parent Deal aggregate
    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="broker_attributions",
        help_text="Parent Deal aggregate.",
    )

    # Attributed Broker Organization
    broker_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="deal_broker_attributions",
        help_text="Attributed Broker organization.",
    )

    # Specific Provenance Role
    role = models.CharField(
        max_length=30,
        choices=DealBrokerRole.choices,
        help_text="Explicit broker originator role (SUPPLY_ORIGINATOR or DEMAND_ORIGINATOR).",
    )

    # Optional Related Opportunity Provenance Link
    related_opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deal_broker_attributions",
        help_text="Related source Opportunity if present in the provenance path.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Deal Broker Attribution"
        verbose_name_plural = "Deal Broker Attributions"
        constraints = [
            # 1. Role must be strictly SUPPLY_ORIGINATOR or DEMAND_ORIGINATOR
            models.CheckConstraint(
                condition=models.Q(role__in=[c[0] for c in DealBrokerRole.choices]),
                name="check_valid_deal_broker_role",
            ),
            # 2. Strict semantic uniqueness on (deal, broker_organization, role, related_opportunity)
            # nulls_distinct=False ensures NULL related_opportunity tuples compare equal in PostgreSQL 15+
            models.UniqueConstraint(
                fields=["deal", "broker_organization", "role", "related_opportunity"],
                nulls_distinct=False,
                name="unique_deal_broker_role_opportunity",
            ),
        ]
        indexes = [
            models.Index(fields=["deal"], name="idx_deal_brk_deal"),
            models.Index(fields=["broker_organization"], name="idx_deal_brk_org"),
            models.Index(fields=["role"], name="idx_deal_brk_role"),
            models.Index(fields=["related_opportunity"], name="idx_deal_brk_opp"),
            models.Index(fields=["-created_at"], name="idx_deal_brk_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.role not in DealBrokerRole.values:
            errors["role"] = f"Invalid broker role '{self.role}'. Must be SUPPLY_ORIGINATOR or DEMAND_ORIGINATOR."

        # Guard against semantic duplicate in application layer before hitting DB
        if self.deal_id and self.broker_organization_id and self.role:
            qs = DealBrokerAttribution.objects.filter(
                deal_id=self.deal_id,
                broker_organization_id=self.broker_organization_id,
                role=self.role,
                related_opportunity_id=self.related_opportunity_id,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["__all__"] = (
                    f"A DealBrokerAttribution already exists for Deal '{self.deal_id}', "
                    f"Broker '{self.broker_organization_id}', Role '{self.role}', "
                    f"and Related Opportunity '{self.related_opportunity_id}'."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        opp_str = f" [Opp: {self.related_opportunity_id}]" if self.related_opportunity_id else ""
        return f"DealBrokerAttribution {self.id} for Deal {self.deal_id}: {self.broker_organization_id} ({self.role}){opp_str}"
