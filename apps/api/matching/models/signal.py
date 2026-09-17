from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from matching.enums import SignalDimension, SignalOutcome


class MatchingSignal(models.Model):
    """
    Structured analytical evidence for a specific candidate evaluation dimension.

    Captures machine-readable codes, normalized scores, weights, structured expected/actual
    values, and optional semantic identity snapshots for dynamic specifications.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        "matching.MatchingCandidate",
        on_delete=models.CASCADE,
        related_name="signals",
        help_text="Candidate evaluated by this signal.",
    )

    # Classification
    dimension = models.CharField(
        max_length=50,
        choices=SignalDimension.choices,
        help_text="Evaluation dimension (Specification, Quantity, Availability, Geography, Trust, History).",
    )
    code = models.CharField(
        max_length=100,
        help_text="Machine-readable rule or attribute code (e.g. 'spec.penetration_grade', 'availability').",
    )
    outcome = models.CharField(
        max_length=20,
        choices=SignalOutcome.choices,
        help_text="Structured outcome: PASS, PARTIAL, FAIL, UNKNOWN, NOT_APPLICABLE.",
    )
    is_hard = models.BooleanField(
        default=False,
        help_text="Whether this signal evaluated a hard eligibility gate.",
    )

    # Numeric Evaluation (DecimalField)
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Dimension or rule weight (>= 0).",
    )
    raw_score = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Normalized score in [0.0000, 1.0000] for known evaluation. Null for UNKNOWN/NOT_APPLICABLE.",
    )
    contribution = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Weighted contribution towards candidate score (>= 0).",
    )

    # Structured Comparison Values (JSONB)
    expected_value = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Constrained structured JSONB representing target demand expectation.",
    )
    actual_value = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Constrained structured JSONB representing candidate actual supply evidence.",
    )

    # Machine-readable Reason & Semantic Identity Snapshot
    reason_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Machine-readable outcome explanation code (never localized text).",
    )
    semantic_identity = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Optional stable UUID or fingerprint snapshot of commodity attribute semantic identity.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["candidate", "dimension", "code"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(raw_score__gte=0) & models.Q(raw_score__lte=1))
                    | models.Q(raw_score__isnull=True)
                ),
                name="check_signal_raw_score_range",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0) | models.Q(weight__isnull=True),
                name="check_signal_weight_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(contribution__gte=0) | models.Q(contribution__isnull=True),
                name="check_signal_contribution_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(outcome__in=[c[0] for c in SignalOutcome.choices]),
                name="check_valid_signal_outcome",
            ),
            models.CheckConstraint(
                condition=models.Q(dimension__in=[c[0] for c in SignalDimension.choices]),
                name="check_valid_signal_dimension",
            ),
        ]
        indexes = [
            models.Index(fields=["candidate", "dimension"], name="idx_match_sig_cand_dim"),
            models.Index(fields=["outcome"], name="idx_match_sig_outcome"),
            models.Index(fields=["code"], name="idx_match_sig_code"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.outcome not in SignalOutcome.values:
            errors["outcome"] = f"Outcome must be one of: {', '.join(SignalOutcome.values)}."

        if self.dimension not in SignalDimension.values:
            errors["dimension"] = f"Dimension must be one of: {', '.join(SignalDimension.values)}."

        if self.raw_score is not None and not (Decimal("0") <= self.raw_score <= Decimal("1")):
            errors["raw_score"] = "Raw score must be between 0.0000 and 1.0000."

        if self.weight is not None and self.weight < Decimal("0"):
            errors["weight"] = "Weight must be non-negative."

        if self.contribution is not None and self.contribution < Decimal("0"):
            errors["contribution"] = "Contribution must be non-negative."

        # Historical immutability
        if self.pk and not self._state.adding:
            if MatchingSignal.objects.filter(pk=self.pk).exists():
                raise ValidationError("MatchingSignal records are historical analytical records and cannot be modified.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("MatchingSignal records are historical analytical records and cannot be deleted.")

    def __str__(self):
        return f"Signal {self.dimension}.{self.code} -> {self.outcome} (Candidate {self.candidate_id})"
