from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from offers.enums import (
    DecisionDimension,
    DecisionProfileLifecycleStatus,
    DecisionSignalStatus,
    OfferVersionStatus,
)


class DecisionProfile(models.Model):
    """
    DecisionProfile Aggregate Root (Contract §39, T0808).

    Identifies a named procurement decision policy configuration whose
    parameters and dimension weights are versioned through immutable
    DecisionProfileVersion instances.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=100,
        unique=True,
        help_text="Canonical unique code identifying this profile (e.g. 'default-procurement-decision').",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable decision profile name.",
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of decision policy objectives and scope.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"], name="idx_dec_profile_code"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class DecisionProfileVersion(models.Model):
    """
    Immutable versioned snapshot of procurement decision weights, minimum coverage, and rules.

    Lifecycle:
        DRAFT -> PUBLISHED -> RETIRED

    Invariants:
        - version > 0
        - (profile, version) is unique
        - minimum_coverage is Decimal in [0.00, 100.00]
        - Published versions and their dimension weights are strictly immutable
        - Published version can transition only to Retired
        - Retired versions cannot change status
        - Published or Retired versions cannot be deleted
        - Decision runs can only execute against Published profile versions
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        DecisionProfile,
        on_delete=models.PROTECT,
        related_name="versions",
        help_text="Owning decision profile.",
    )
    version = models.PositiveIntegerField(
        help_text="Monotonically increasing version number (must be > 0).",
    )
    status = models.CharField(
        max_length=20,
        choices=DecisionProfileLifecycleStatus.choices,
        default=DecisionProfileLifecycleStatus.DRAFT,
        help_text="Current lifecycle state of this profile version.",
    )
    minimum_coverage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("70.00"),
        help_text="Minimum required evidence coverage percentage [0.00, 100.00] (Contract §50).",
    )
    description = models.TextField(
        blank=True,
        help_text="Release notes or rationale for this policy version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["profile", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "version"],
                name="unique_dec_profile_version",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="check_pos_dec_profile_ver",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in DecisionProfileLifecycleStatus.choices]),
                name="check_valid_dec_profile_status",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_coverage__gte=0, minimum_coverage__lte=100),
                name="check_valid_dec_min_coverage",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "version"], name="idx_dec_prof_ver"),
            models.Index(fields=["status"], name="idx_dec_prof_status"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.version is not None and self.version <= 0:
            errors["version"] = "Profile version must be greater than 0."

        if self.minimum_coverage is not None:
            if self.minimum_coverage < Decimal("0") or self.minimum_coverage > Decimal("100"):
                errors["minimum_coverage"] = "Minimum coverage must be between 0 and 100."

        if self._state.adding and self.status == DecisionProfileLifecycleStatus.RETIRED:
            errors["status"] = "New profile versions cannot start retired."

        if self.pk and not self._state.adding:
            persisted = DecisionProfileVersion.objects.filter(pk=self.pk).first()
            if persisted:
                # Core identity immutability
                if self.profile_id != persisted.profile_id:
                    errors["profile"] = "Profile reference cannot be modified."
                if self.version != persisted.version:
                    errors["version"] = "Profile version number cannot be modified."

                # Status transitions and configuration immutability
                if persisted.status == DecisionProfileLifecycleStatus.DRAFT:
                    if self.status == DecisionProfileLifecycleStatus.RETIRED:
                        errors["status"] = "Draft profile versions must be published before retirement."
                elif persisted.status == DecisionProfileLifecycleStatus.PUBLISHED:
                    if self.status == DecisionProfileLifecycleStatus.DRAFT:
                        errors["status"] = "Cannot revert a published profile version to draft."
                    if self.minimum_coverage != persisted.minimum_coverage:
                        errors["minimum_coverage"] = "Minimum coverage of a published profile version is immutable."
                elif persisted.status == DecisionProfileLifecycleStatus.RETIRED:
                    if self.status != DecisionProfileLifecycleStatus.RETIRED:
                        errors["status"] = "Retired profile versions cannot change status."
                    if self.minimum_coverage != persisted.minimum_coverage:
                        errors["minimum_coverage"] = "Minimum coverage of a retired profile version is immutable."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in [DecisionProfileLifecycleStatus.PUBLISHED, DecisionProfileLifecycleStatus.RETIRED]:
            raise ValidationError("Published or retired profile versions cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.profile.code} v{self.version} ({self.get_status_display()})"


class DecisionDimensionWeight(models.Model):
    """
    Relational dimension weight configuring a DecisionProfileVersion (T0808).

    Invariants:
        - Exactly one weight per dimension per profile version.
        - Weight is a Decimal in [0.00, 100.00].
        - Weights belonging to a Published or Retired profile version are immutable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile_version = models.ForeignKey(
        DecisionProfileVersion,
        on_delete=models.CASCADE,
        related_name="dimension_weights",
        help_text="Owning profile version.",
    )
    dimension = models.CharField(
        max_length=30,
        choices=DecisionDimension.choices,
        help_text="Procurement evaluation dimension.",
    )
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Configured dimension weight percentage [0.00, 100.00].",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["profile_version", "dimension"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile_version", "dimension"],
                name="unique_dec_pv_dim",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0, weight__lte=100),
                name="check_valid_dec_dim_weight",
            ),
            models.CheckConstraint(
                condition=models.Q(dimension__in=[c[0] for c in DecisionDimension.choices]),
                name="check_valid_dec_dim_choice",
            ),
        ]
        indexes = [
            models.Index(fields=["profile_version", "dimension"], name="idx_dec_pv_dim"),
        ]

    def clean(self):
        super().clean()
        if self.weight is not None:
            if self.weight < Decimal("0") or self.weight > Decimal("100"):
                raise ValidationError({"weight": "Dimension weight must be between 0 and 100."})

        # Check immutability if parent profile version is published or retired
        pv = getattr(self, "profile_version", None)
        if not pv and self.profile_version_id:
            pv = DecisionProfileVersion.objects.filter(pk=self.profile_version_id).first()

        if pv and pv.status in [
            DecisionProfileLifecycleStatus.PUBLISHED,
            DecisionProfileLifecycleStatus.RETIRED,
        ]:
            if self._state.adding:
                raise ValidationError("Cannot add dimension weights to a published or retired profile version.")
            persisted = DecisionDimensionWeight.objects.filter(pk=self.pk).first()
            if persisted and (self.weight != persisted.weight or self.dimension != persisted.dimension):
                raise ValidationError("Dimension weights of a published or retired profile version are immutable.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pv = getattr(self, "profile_version", None)
        if not pv and self.profile_version_id:
            pv = DecisionProfileVersion.objects.filter(pk=self.profile_version_id).first()
        if pv and pv.status in [
            DecisionProfileLifecycleStatus.PUBLISHED,
            DecisionProfileLifecycleStatus.RETIRED,
        ]:
            raise ValidationError("Dimension weights of a published or retired profile version cannot be deleted.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.profile_version} - {self.dimension}: {self.weight}%"


class DecisionRun(models.Model):
    """
    Immutable analysis execution record for procurement decision support (Contract §52, T0808).

    Stores frozen input fingerprints, RFQ demand snapshot, and explicit linkage to the
    exact Published DecisionProfileVersion and RFQ.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        related_name="decision_runs",
        help_text="Target RFQ procurement demand.",
    )
    decision_profile_version = models.ForeignKey(
        DecisionProfileVersion,
        on_delete=models.PROTECT,
        related_name="decision_runs",
        help_text="Published decision profile version used for evaluation.",
    )
    engine_version = models.CharField(
        max_length=50,
        default="decision-engine-v1",
        help_text="Centralized semantic decision engine contract version.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_decision_runs",
        help_text="Authenticated Buyer or Operator actor who initiated the decision run.",
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        db_index=True,
        help_text="Timestamp when the decision run was initiated.",
    )
    input_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 fingerprint of the canonical decision inputs.",
    )
    result_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 fingerprint of the decision results (reserved for T0809).",
    )
    target_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Canonical frozen snapshot of RFQ procurement demand at run creation.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rfq", "-created_at"], name="idx_dec_run_rfq_created"),
            models.Index(fields=["input_fingerprint"], name="idx_dec_run_input_fp"),
        ]

    def clean(self):
        super().clean()
        if self.pk and not self._state.adding:
            persisted = DecisionRun.objects.filter(pk=self.pk).first()
            if persisted:
                if self.rfq_id != persisted.rfq_id:
                    raise ValidationError("DecisionRun target RFQ cannot be modified.")
                if self.decision_profile_version_id != persisted.decision_profile_version_id:
                    raise ValidationError("DecisionRun profile version reference cannot be modified.")
                if self.engine_version != persisted.engine_version:
                    raise ValidationError("DecisionRun engine_version cannot be modified.")
                if self.input_fingerprint != persisted.input_fingerprint:
                    raise ValidationError("DecisionRun input_fingerprint cannot be modified.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Decision runs are immutable audit records and cannot be deleted.")

    def __str__(self):
        return f"DecisionRun {self.id} on RFQ {self.rfq_id} ({self.engine_version})"


class DecisionCandidate(models.Model):
    """
    Immutable candidate record evaluated within a DecisionRun (Contract §53, T0808).

    Binds the DecisionRun to an exact commercial OfferVersion snapshot.
    Evaluation scores, coverage, and rank are nullable prior to T0809 evaluation.
    award_eligible defaults to None (null-safe unevaluated representation).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    decision_run = models.ForeignKey(
        DecisionRun,
        on_delete=models.CASCADE,
        related_name="candidates",
        help_text="Associated decision run execution.",
    )
    offer = models.ForeignKey(
        "offers.Offer",
        on_delete=models.PROTECT,
        related_name="decision_candidates",
        help_text="Parent offer negotiation thread.",
    )
    offer_version = models.ForeignKey(
        "offers.OfferVersion",
        on_delete=models.PROTECT,
        related_name="decision_candidates",
        help_text="Exact immutable commercial snapshot evaluated.",
    )

    # Analytical Scores (DecimalField, nullable until final scoring in T0809)
    decision_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Weighted decision score percentage [0.00, 100.00] (Contract §47).",
    )
    evidence_coverage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Evidence coverage percentage [0.00, 100.00] (Contract §48).",
    )
    effective_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Effective decision score percentage [0.00, 100.00] (Contract §49).",
    )
    award_eligible = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Award eligibility gate outcome. None indicates unevaluated prior to T0809 hard conditions.",
    )
    rank = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Deterministic rank position (positive integer >= 1) among evaluated candidates.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["decision_run", "rank", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["decision_run", "offer_version"],
                name="unique_dec_run_off_ver",
            ),
            models.CheckConstraint(
                condition=models.Q(rank__isnull=True) | models.Q(rank__gte=1),
                name="check_pos_dec_cand_rank",
            ),
            models.CheckConstraint(
                condition=models.Q(decision_score__isnull=True)
                | models.Q(decision_score__gte=0, decision_score__lte=100),
                name="check_dec_cand_score_range",
            ),
            models.CheckConstraint(
                condition=models.Q(evidence_coverage__isnull=True)
                | models.Q(evidence_coverage__gte=0, evidence_coverage__lte=100),
                name="check_dec_cand_cov_range",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_score__isnull=True)
                | models.Q(effective_score__gte=0, effective_score__lte=100),
                name="check_dec_cand_eff_range",
            ),
        ]
        indexes = [
            models.Index(fields=["decision_run", "offer"], name="idx_dec_cand_run_offer"),
            models.Index(fields=["decision_run", "rank"], name="idx_dec_cand_run_rank"),
        ]

    def clean(self):
        super().clean()
        # Cross-entity integrity checks
        if self.offer_id and self.decision_run_id:
            # Candidate Offer must belong to the same RFQ as DecisionRun
            run_rfq_id = getattr(self.decision_run, "rfq_id", None)
            offer_rfq_id = getattr(self.offer, "rfq_id", None)
            if run_rfq_id and offer_rfq_id and run_rfq_id != offer_rfq_id:
                raise ValidationError("Candidate Offer must belong to the same RFQ as DecisionRun.")

        if self.offer_version_id and self.offer_id:
            # Candidate OfferVersion must belong to candidate Offer
            ver_offer_id = getattr(self.offer_version, "offer_id", None)
            if ver_offer_id and ver_offer_id != self.offer_id:
                raise ValidationError("Candidate OfferVersion must belong to candidate Offer.")

            # Candidate OfferVersion must be in SUBMITTED status
            ver_status = getattr(self.offer_version, "status", None)
            if ver_status and ver_status != OfferVersionStatus.SUBMITTED:
                raise ValidationError("Only SUBMITTED OfferVersion can be a decision candidate.")

        if self.rank is not None and self.rank < 1:
            raise ValidationError({"rank": "Rank must be a positive integer (>= 1)."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Candidate {self.offer_id} in Run {self.decision_run_id}"


class DecisionSignal(models.Model):
    """
    Structured analytical evidence evaluated for a DecisionCandidate (Contract §40, §54, T0808).

    Stores machine-readable codes, normalized scores, weights, structured expected/actual
    values, and privacy-sanitized snapshot data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        DecisionCandidate,
        on_delete=models.CASCADE,
        related_name="signals",
        help_text="Candidate evaluated by this signal.",
    )
    dimension = models.CharField(
        max_length=30,
        choices=DecisionDimension.choices,
        help_text="Evaluation dimension (COST, QUALITY, DELIVERY, PAYMENT, TRUST, COMPLETENESS).",
    )
    code = models.CharField(
        max_length=100,
        help_text="Machine-readable rule or signal code (e.g. 'cost.landed_unit_cost').",
    )
    status = models.CharField(
        max_length=20,
        choices=DecisionSignalStatus.choices,
        help_text="Structured outcome: PASS, PARTIAL, FAIL, UNKNOWN, NOT_APPLICABLE.",
    )
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Dimension or signal weight percentage (>= 0).",
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
    expected_value = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Structured JSONB representing target RFQ expectation.",
    )
    actual_value = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="Structured JSONB representing candidate actual commercial proposal.",
    )
    reason_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Machine-readable reason code (never localized text).",
    )
    snapshot_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sanitized decision-relevant facts. Strictly excludes private CRM/contact data.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["candidate", "dimension", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in DecisionSignalStatus.choices]),
                name="check_valid_dec_sig_status",
            ),
            models.CheckConstraint(
                condition=models.Q(dimension__in=[c[0] for c in DecisionDimension.choices]),
                name="check_valid_dec_sig_dim",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__isnull=True) | models.Q(weight__gte=0),
                name="check_dec_sig_weight_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(raw_score__isnull=True)
                | models.Q(raw_score__gte=0, raw_score__lte=1),
                name="check_dec_sig_raw_score_range",
            ),
            models.CheckConstraint(
                condition=models.Q(contribution__isnull=True) | models.Q(contribution__gte=0),
                name="check_dec_sig_contrib_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["candidate", "dimension", "code"], name="idx_dec_sig_cand_dim_code"),
        ]

    def clean(self):
        super().clean()
        # Privacy guard: snapshot_data must not contain private CRM or contact fields
        forbidden_keys = {
            "phone",
            "email",
            "contact_attempts",
            "operator_notes",
            "notes",
            "private_opportunity_data",
            "source_opportunity",
        }
        if isinstance(self.snapshot_data, dict):
            found_forbidden = [k for k in self.snapshot_data.keys() if k.lower() in forbidden_keys]
            if found_forbidden:
                raise ValidationError(
                    f"Private CRM/contact fields {found_forbidden} are strictly forbidden in DecisionSignal snapshot_data."
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Signal {self.dimension}.{self.code} = {self.status} (Candidate {self.candidate_id})"
