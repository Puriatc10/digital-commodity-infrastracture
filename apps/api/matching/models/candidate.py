from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from matching.enums import CandidateKind, CandidateLane


class MatchingCandidate(models.Model):
    """
    Immutable candidate record discovered and evaluated for a specific MatchingRun.

    Maintains explicit typed references to exactly one source entity (SupplyListing,
    Qualified Opportunity, Supplier Organization, or Broker Organization).

    Enforces lane/kind/source matrix integrity and prevents duplicate discovery of
    the same source artifact within a run.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        "matching.MatchingRun",
        on_delete=models.CASCADE,
        related_name="candidates",
        help_text="Associated matching execution run.",
    )

    # Classification & Lane
    lane = models.CharField(
        max_length=30,
        choices=CandidateLane.choices,
        help_text="Lane to which this candidate belongs (Direct Supply, Potential Supplier, Broker Path).",
    )
    candidate_kind = models.CharField(
        max_length=30,
        choices=CandidateKind.choices,
        help_text="Candidate evidence type.",
    )

    # Typed Source References (Strictly typed, mutually exclusive: exactly one required)
    supplier_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_matching_candidates",
        help_text="Source Supplier Organization (POTENTIAL_SUPPLIER lane).",
    )
    supply_listing = models.ForeignKey(
        "trade_hub.SupplyListing",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matching_candidates",
        help_text="Source Supply Listing (DIRECT_SUPPLY lane).",
    )
    supply_opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matching_candidates",
        help_text="Source Qualified Supply Opportunity (DIRECT_SUPPLY lane, Operator only).",
    )
    broker_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="broker_matching_candidates",
        help_text="Source Broker Organization (BROKER_PATH lane).",
    )

    # Frozen Analytical Snapshot
    candidate_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Audience-scoped frozen snapshot of candidate evidence data.",
    )

    # Eligibility & Gate Evaluation
    eligible = models.BooleanField(
        default=True,
        help_text="Whether candidate passed all hard eligibility gates.",
    )
    exclusion_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Machine-readable code identifying why candidate was excluded.",
    )

    # Analytical Scores (DecimalField, nullable until final scoring in T0707)
    fit_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Specification / capability fit percentage (0.00 - 100.00).",
    )
    evidence_coverage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Known evidence coverage percentage (0.00 - 100.00).",
    )
    ranking_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Final composite ranking score percentage (0.00 - 100.00).",
    )
    rank = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Rank within the candidate's lane (1-based, rank > 0).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run", "lane", "rank", "-ranking_score"]
        constraints = [
            # 1. Exactly one candidate source FK must be non-null
            models.CheckConstraint(
                condition=(
                    (models.Q(supply_listing__isnull=False) & models.Q(supply_opportunity__isnull=True) & models.Q(supplier_organization__isnull=True) & models.Q(broker_organization__isnull=True))
                    | (models.Q(supply_listing__isnull=True) & models.Q(supply_opportunity__isnull=False) & models.Q(supplier_organization__isnull=True) & models.Q(broker_organization__isnull=True))
                    | (models.Q(supply_listing__isnull=True) & models.Q(supply_opportunity__isnull=True) & models.Q(supplier_organization__isnull=False) & models.Q(broker_organization__isnull=True))
                    | (models.Q(supply_listing__isnull=True) & models.Q(supply_opportunity__isnull=True) & models.Q(supplier_organization__isnull=True) & models.Q(broker_organization__isnull=False))
                ),
                name="check_candidate_source_exactly_one",
            ),
            # 2. Kind and source consistency
            models.CheckConstraint(
                condition=(
                    (models.Q(candidate_kind=CandidateKind.SUPPLY_LISTING) & models.Q(supply_listing__isnull=False))
                    | (models.Q(candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY) & models.Q(supply_opportunity__isnull=False))
                    | (models.Q(candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION) & models.Q(supplier_organization__isnull=False))
                    | (models.Q(candidate_kind=CandidateKind.BROKER_ORGANIZATION) & models.Q(broker_organization__isnull=False))
                ),
                name="check_candidate_kind_source_consistency",
            ),
            # 3. Lane and source consistency
            models.CheckConstraint(
                condition=(
                    (models.Q(lane=CandidateLane.DIRECT_SUPPLY) & (models.Q(supply_listing__isnull=False) | models.Q(supply_opportunity__isnull=False)))
                    | (models.Q(lane=CandidateLane.POTENTIAL_SUPPLIER) & models.Q(supplier_organization__isnull=False))
                    | (models.Q(lane=CandidateLane.BROKER_PATH) & models.Q(broker_organization__isnull=False))
                ),
                name="check_candidate_lane_source_consistency",
            ),
            # 4. Score range constraints
            models.CheckConstraint(
                condition=(
                    (models.Q(fit_score__gte=0) & models.Q(fit_score__lte=100))
                    | models.Q(fit_score__isnull=True)
                ),
                name="check_candidate_fit_score_range",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(evidence_coverage__gte=0) & models.Q(evidence_coverage__lte=100))
                    | models.Q(evidence_coverage__isnull=True)
                ),
                name="check_candidate_evidence_coverage_range",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(ranking_score__gte=0) & models.Q(ranking_score__lte=100))
                    | models.Q(ranking_score__isnull=True)
                ),
                name="check_candidate_ranking_score_range",
            ),
            models.CheckConstraint(
                condition=models.Q(rank__gt=0) | models.Q(rank__isnull=True),
                name="check_candidate_rank_positive",
            ),
            # 5. Conditional uniqueness preventing duplicate source instances within the same run
            models.UniqueConstraint(
                fields=["run", "supply_listing"],
                condition=models.Q(supply_listing__isnull=False),
                name="unique_candidate_run_supply_listing",
            ),
            models.UniqueConstraint(
                fields=["run", "supply_opportunity"],
                condition=models.Q(supply_opportunity__isnull=False),
                name="unique_candidate_run_supply_opportunity",
            ),
            models.UniqueConstraint(
                fields=["run", "supplier_organization"],
                condition=models.Q(supplier_organization__isnull=False),
                name="unique_candidate_run_supplier_organization",
            ),
            models.UniqueConstraint(
                fields=["run", "broker_organization"],
                condition=models.Q(broker_organization__isnull=False),
                name="unique_candidate_run_broker_organization",
            ),
        ]
        indexes = [
            models.Index(fields=["run", "lane"], name="idx_match_cand_run_lane"),
            models.Index(fields=["candidate_kind"], name="idx_match_cand_kind"),
            models.Index(fields=["eligible"], name="idx_match_cand_eligible"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        sources = [
            ("supply_listing", self.supply_listing_id),
            ("supply_opportunity", self.supply_opportunity_id),
            ("supplier_organization", self.supplier_organization_id),
            ("broker_organization", self.broker_organization_id),
        ]
        non_null_sources = [name for name, val in sources if val is not None]

        if len(non_null_sources) == 0:
            errors["source"] = "Exactly one candidate source reference must be specified (found 0)."
        elif len(non_null_sources) > 1:
            errors["source"] = f"Exactly one candidate source reference must be specified (found {len(non_null_sources)}: {', '.join(non_null_sources)})."
        else:
            active_source = non_null_sources[0]
            expected_kind_map = {
                "supply_listing": CandidateKind.SUPPLY_LISTING,
                "supply_opportunity": CandidateKind.SUPPLY_OPPORTUNITY,
                "supplier_organization": CandidateKind.SUPPLIER_ORGANIZATION,
                "broker_organization": CandidateKind.BROKER_ORGANIZATION,
            }
            if self.candidate_kind != expected_kind_map[active_source]:
                errors["candidate_kind"] = (
                    f"Candidate kind '{self.candidate_kind}' is incompatible with source '{active_source}'. "
                    f"Expected '{expected_kind_map[active_source]}'."
                )

            expected_lane_map = {
                "supply_listing": CandidateLane.DIRECT_SUPPLY,
                "supply_opportunity": CandidateLane.DIRECT_SUPPLY,
                "supplier_organization": CandidateLane.POTENTIAL_SUPPLIER,
                "broker_organization": CandidateLane.BROKER_PATH,
            }
            if self.lane != expected_lane_map[active_source]:
                errors["lane"] = (
                    f"Candidate lane '{self.lane}' is incompatible with source '{active_source}'. "
                    f"Expected '{expected_lane_map[active_source]}'."
                )

        if self.fit_score is not None and not (Decimal("0") <= self.fit_score <= Decimal("100")):
            errors["fit_score"] = "Fit score must be between 0 and 100."
        if self.evidence_coverage is not None and not (Decimal("0") <= self.evidence_coverage <= Decimal("100")):
            errors["evidence_coverage"] = "Evidence coverage must be between 0 and 100."
        if self.ranking_score is not None and not (Decimal("0") <= self.ranking_score <= Decimal("100")):
            errors["ranking_score"] = "Ranking score must be between 0 and 100."
        if self.rank is not None and self.rank <= 0:
            errors["rank"] = "Rank must be greater than 0."

        # Historical immutability
        if self.pk and not self._state.adding:
            if MatchingCandidate.objects.filter(pk=self.pk).exists():
                raise ValidationError("MatchingCandidate records are historical analytical records and cannot be modified.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("MatchingCandidate records are historical analytical records and cannot be deleted.")

    def __str__(self):
        return f"Candidate {self.id} ({self.get_candidate_kind_display()}) in Run {self.run_id}"
