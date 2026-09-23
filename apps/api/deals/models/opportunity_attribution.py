import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class DealOpportunityRole(models.TextChoices):
    DEMAND_ORIGIN = "DEMAND_ORIGIN", "Demand Origin"
    SUPPLY_ORIGIN = "SUPPLY_ORIGIN", "Supply Origin"


class DealOpportunityAttribution(models.Model):
    """
    DealOpportunityAttribution Entity (Epic 9 Contract §50-§51, T0904).

    Persists explicit source Opportunity provenance for a Deal:
        Deal -> DealOpportunityAttribution(s)

    Critical Invariants:
    - Multi-Opportunity Coexistence: A Deal may originate from both a Demand Opportunity
      (via RFQ conversion) and a Supply Opportunity (via Offer provenance). Both are explicitly
      captured as distinct rows rather than collapsing to a single scalar.
    - Role Choices: Exactly DEMAND_ORIGIN or SUPPLY_ORIGIN (strictly no generic provenance roles).
    - Uniqueness: (deal, opportunity, role) is strictly unique at both DB and application levels.
    - Historical Stability: Editing Opportunity operational metadata (notes, contact attempts, etc.)
      does NOT rewrite or invalidate the Deal's historical attribution.
    - Minimal Identity: Preserves relational linkage for traceability without copying private CRM fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Parent Deal aggregate
    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="opportunity_attributions",
        help_text="Parent Deal aggregate.",
    )

    # Referenced source Opportunity
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="deal_opportunity_attributions",
        help_text="Source Opportunity lead in the trade origin path.",
    )

    # Specific Provenance Role
    role = models.CharField(
        max_length=30,
        choices=DealOpportunityRole.choices,
        help_text="Explicit opportunity provenance role (DEMAND_ORIGIN or SUPPLY_ORIGIN).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Deal Opportunity Attribution"
        verbose_name_plural = "Deal Opportunity Attributions"
        constraints = [
            # 1. Role must be strictly DEMAND_ORIGIN or SUPPLY_ORIGIN
            models.CheckConstraint(
                condition=models.Q(role__in=[c[0] for c in DealOpportunityRole.choices]),
                name="check_valid_deal_opportunity_role",
            ),
            # 2. Strict relational uniqueness on (deal, opportunity, role)
            models.UniqueConstraint(
                fields=["deal", "opportunity", "role"],
                name="unique_deal_opportunity_role",
            ),
        ]
        indexes = [
            models.Index(fields=["deal"], name="idx_deal_opp_deal"),
            models.Index(fields=["opportunity"], name="idx_deal_opp_opp"),
            models.Index(fields=["role"], name="idx_deal_opp_role"),
            models.Index(fields=["-created_at"], name="idx_deal_opp_created_at"),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.role not in DealOpportunityRole.values:
            errors["role"] = f"Invalid opportunity role '{self.role}'. Must be DEMAND_ORIGIN or SUPPLY_ORIGIN."

        # Guard against semantic duplicate in application layer before hitting DB
        if self.deal_id and self.opportunity_id and self.role:
            qs = DealOpportunityAttribution.objects.filter(
                deal_id=self.deal_id,
                opportunity_id=self.opportunity_id,
                role=self.role,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors["__all__"] = (
                    f"A DealOpportunityAttribution already exists for Deal '{self.deal_id}', "
                    f"Opportunity '{self.opportunity_id}', and Role '{self.role}'."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"DealOpportunityAttribution {self.id} for Deal {self.deal_id}: Opp {self.opportunity_id} ({self.role})"
