from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Optional, Sequence
import uuid

from django.utils import timezone

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import DecisionDimensionWeight, OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult


@dataclass(frozen=True)
class EvaluatedCandidateScores:
    """
    Persistable score outcomes for one candidate OfferVersion (Contract §47-§50, T0809).
    """

    decision_score: Optional[Decimal]
    evidence_coverage: Decimal
    effective_score: Decimal
    applicable_weight: Decimal
    known_weight: Decimal
    weighted_score_sum: Decimal


def aggregate_candidate_scores(
    signals_by_dimension: Mapping[str, SignalEvaluationResult],
    dimension_weights: Sequence[DecisionDimensionWeight],
) -> tuple[EvaluatedCandidateScores, dict[str, Decimal]]:
    """
    Centralized Decimal score aggregator (Contract §47-§49, T0809).

    Formulas:
        A = total applicable weights (excluding NOT_APPLICABLE)
        K = total known weights (excluding UNKNOWN and NOT_APPLICABLE)
        C = sum(weight * raw_score) for known signals

    Then:
        - If K == 0:
            DecisionScore = None
            EvidenceCoverage = 0.00
            EffectiveScore = 0.00
        - Else:
            DecisionScore = (C / K) * 100
            EvidenceCoverage = (K / A) * 100
            EffectiveScore = DecisionScore * EvidenceCoverage / 100

    Invariants:
        - Pure Decimal calculations end-to-end; zero binary float conversions.
        - Single centralized rounding policy: ROUND_HALF_UP with 2 decimal places.
        - Returns per-dimension contribution Decimal values.
    """
    # Build fast lookup for weights
    weight_map: dict[str, Decimal] = {
        dw.dimension: Decimal(str(dw.weight)) for dw in dimension_weights
    }

    a_sum = Decimal("0.00")
    k_sum = Decimal("0.00")
    c_sum = Decimal("0.0000")
    contributions: dict[str, Decimal] = {}

    for dim in DecisionDimension.values:
        weight = weight_map.get(dim, Decimal("0.00"))
        signal = signals_by_dimension.get(dim)

        if not signal or signal.status == DecisionSignalStatus.NOT_APPLICABLE:
            # Genuinely not applicable: excludes weight from both A and K
            continue

        # Signal is applicable
        a_sum += weight

        if signal.status == DecisionSignalStatus.UNKNOWN:
            # Applicable, but evidence is missing: included in A, excluded from K
            continue

        # Known evaluation: PASS, PARTIAL, or FAIL
        k_sum += weight
        raw_score = signal.raw_score if signal.raw_score is not None else Decimal("0.0000")
        weighted_val = weight * raw_score
        c_sum += weighted_val

        contrib = (weighted_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        contributions[dim] = contrib

    # Zero-known Guard
    if k_sum == Decimal("0.00"):
        scores = EvaluatedCandidateScores(
            decision_score=None,
            evidence_coverage=Decimal("0.00"),
            effective_score=Decimal("0.00"),
            applicable_weight=a_sum.quantize(Decimal("0.01")),
            known_weight=Decimal("0.00"),
            weighted_score_sum=Decimal("0.00"),
        )
        return scores, contributions

    decision_score = (c_sum / k_sum * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    evidence_coverage = (
        (k_sum / a_sum * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if a_sum > Decimal("0")
        else Decimal("0.00")
    )
    effective_score = (decision_score * evidence_coverage / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    scores = EvaluatedCandidateScores(
        decision_score=decision_score,
        evidence_coverage=evidence_coverage,
        effective_score=effective_score,
        applicable_weight=a_sum.quantize(Decimal("0.01")),
        known_weight=k_sum.quantize(Decimal("0.01")),
        weighted_score_sum=c_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )
    return scores, contributions


def evaluate_award_eligibility(
    candidate_version: OfferVersion,
    signals_by_dimension: Mapping[str, SignalEvaluationResult],
    *,
    reference_time: Optional[timezone.datetime] = None,
) -> tuple[bool, list[str]]:
    """
    Centralized award eligibility gate evaluation (Contract §67, T0809).

    Rejection conditions:
    - Hard quality failure (Quality signal is_hard_failure or status==FAIL)
    - Suspended organization (Trust signal is_hard_failure or status==FAIL with SUSPENDED)
    - Expired OfferVersion (valid_until in the past)
    - Invalid external provenance (external offer missing counterparty)
    - Structural commercial ineligibility (non-positive quantity or unit price)
    """
    now = reference_time or timezone.now()
    reasons: list[str] = []
    offer = candidate_version.offer

    # 1. Hard Quality Failure
    quality_sig = signals_by_dimension.get(DecisionDimension.QUALITY)
    if quality_sig and (quality_sig.is_hard_failure or quality_sig.status == DecisionSignalStatus.FAIL):
        reasons.append("HARD_QUALITY_FAILURE")

    # 2. Suspended Organization
    trust_sig = signals_by_dimension.get(DecisionDimension.TRUST)
    if trust_sig and (trust_sig.is_hard_failure or trust_sig.reason_code == "SUSPENDED_ORGANIZATION"):
        reasons.append("SUSPENDED_ORGANIZATION")

    # 3. Expired OfferVersion
    if candidate_version.valid_until and candidate_version.valid_until < now:
        reasons.append("OFFER_EXPIRED")

    # 4. Invalid External Provenance
    if offer.offeror_role == "SUPPLIER" and not offer.offering_organization_id and not offer.external_counterparty_id:
        reasons.append("INVALID_EXTERNAL_PROVENANCE")

    # 5. Structural Quantity / Price Invariants
    if candidate_version.offered_quantity is None or candidate_version.offered_quantity <= Decimal("0"):
        reasons.append("NON_POSITIVE_QUANTITY")
    if candidate_version.unit_price is None or candidate_version.unit_price <= Decimal("0"):
        reasons.append("NON_POSITIVE_UNIT_PRICE")

    is_eligible = len(reasons) == 0
    return is_eligible, reasons


@dataclass
class CandidateRankingItem:
    offer_id: uuid.UUID
    offer_version_id: uuid.UUID
    effective_score: Optional[Decimal]
    evidence_coverage: Optional[Decimal]
    decision_score: Optional[Decimal]
    award_eligible: bool
    rank: Optional[int] = None
    is_recommended: bool = False


def rank_and_recommend_candidates(
    candidates: list[CandidateRankingItem],
    minimum_coverage: Decimal,
) -> list[CandidateRankingItem]:
    """
    Deterministic multi-key candidate ranking and human-controlled recommendation selection (Contract §50, §55, T0809).

    Ranking Order:
        effective_score DESC,
        evidence_coverage DESC,
        decision_score DESC,
        stable_offer_key (str(offer_id)) ASC

    Recommendation Rule:
        The highest ranked candidate that is:
            award_eligible == True AND evidence_coverage >= minimum_coverage
        receives is_recommended = True.
        All others receive is_recommended = False.
    """
    def _ranking_key(item: CandidateRankingItem):
        eff = item.effective_score if item.effective_score is not None else Decimal("-1")
        cov = item.evidence_coverage if item.evidence_coverage is not None else Decimal("-1")
        dec = item.decision_score if item.decision_score is not None else Decimal("-1")
        return (-eff, -cov, -dec, str(item.offer_id))

    sorted_candidates = sorted(candidates, key=_ranking_key)

    recommended_assigned = False
    for idx, item in enumerate(sorted_candidates, start=1):
        item.rank = idx
        cov = item.evidence_coverage if item.evidence_coverage is not None else Decimal("0")

        if (
            not recommended_assigned
            and item.award_eligible
            and cov >= minimum_coverage
        ):
            item.is_recommended = True
            recommended_assigned = True
        else:
            item.is_recommended = False

    return sorted_candidates
