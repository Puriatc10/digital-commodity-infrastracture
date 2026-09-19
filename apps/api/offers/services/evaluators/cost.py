from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from offers.services.normalization import NormalizedOfferVersion
from trade_hub.models import RFQ


def find_best_same_currency_cost(
    rfq: RFQ,
    normalized_candidates: Sequence[tuple[OfferVersion, NormalizedOfferVersion]],
) -> Optional[Decimal]:
    """
    Find the lowest landed unit cost among all candidates sharing the RFQ's target currency.
    (Contract §41, T0809).
    """
    rfq_currency = (rfq.currency or "").strip().upper()
    comparable_costs = [
        norm.landed_unit_cost
        for ver, norm in normalized_candidates
        if (ver.currency or "").strip().upper() == rfq_currency
        and norm.landed_unit_cost is not None
        and norm.landed_unit_cost > Decimal("0")
    ]
    if comparable_costs:
        return min(comparable_costs)
    return None


def evaluate_cost_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
    candidate_normalized: NormalizedOfferVersion,
    best_comparable_cost: Optional[Decimal],
) -> SignalEvaluationResult:
    """
    Evaluate commercial cost signal for one candidate OfferVersion (Contract §41, T0809).

    Invariants:
    - Strictly uses T0805 landed_unit_cost; NEVER falls back to headline unit_price.
    - If landed_unit_cost is None (e.g. unknown logistics), signal is strictly UNKNOWN.
    - Cross-currency proposals cannot be compared without FX and evaluate strictly to UNKNOWN.
    - Same-currency candidates with complete landed costs are scored:
        score = best_cost / candidate_cost bounded in [0.0000, 1.0000].
    - Best cost candidate receives score = 1.0000 (PASS).
    - Higher cost candidates receive proportional score (PARTIAL).
    """
    rfq_currency = (rfq.currency or "").strip().upper()
    candidate_currency = (candidate_version.currency or "").strip().upper()

    # 1. Cross-Currency Guard
    if candidate_currency != rfq_currency:
        return SignalEvaluationResult(
            dimension=DecisionDimension.COST,
            code="cost.landed_unit_cost",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="CROSS_CURRENCY_UNKNOWN",
            expected_value={"currency": rfq_currency},
            actual_value={"currency": candidate_currency},
            snapshot_data={
                "rfq_currency": rfq_currency,
                "candidate_currency": candidate_currency,
                "landed_unit_cost": (
                    str(candidate_normalized.landed_unit_cost)
                    if candidate_normalized.landed_unit_cost is not None
                    else None
                ),
            },
        )

    # 2. Incomplete Landed Cost Guard
    if candidate_normalized.landed_unit_cost is None:
        return SignalEvaluationResult(
            dimension=DecisionDimension.COST,
            code="cost.landed_unit_cost",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="INCOMPLETE_LANDED_COST",
            expected_value={"currency": rfq_currency, "landed_cost_status": "KNOWN"},
            actual_value={"currency": candidate_currency, "landed_cost_status": "UNKNOWN"},
            snapshot_data={
                "missing_components": list(candidate_normalized.missing_components),
                "product_cost": str(candidate_normalized.product_cost),
                "currency": candidate_currency,
            },
        )

    # 3. Context Guard (no valid benchmark)
    if best_comparable_cost is None or best_comparable_cost <= Decimal("0"):
        return SignalEvaluationResult(
            dimension=DecisionDimension.COST,
            code="cost.landed_unit_cost",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="NO_COMPARABLE_COST_CONTEXT",
            expected_value={"currency": rfq_currency},
            actual_value={
                "currency": candidate_currency,
                "landed_unit_cost": str(candidate_normalized.landed_unit_cost),
            },
            snapshot_data={"currency": candidate_currency},
        )

    # 4. Proportional Same-Currency Scoring
    candidate_cost = candidate_normalized.landed_unit_cost
    raw_ratio = (best_comparable_cost / candidate_cost).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    score = min(max(raw_ratio, Decimal("0.0000")), Decimal("1.0000"))

    if score == Decimal("1.0000"):
        status = DecisionSignalStatus.PASS
        reason = "BEST_COST"
    else:
        status = DecisionSignalStatus.PARTIAL
        reason = "PROPORTIONAL_COST"

    return SignalEvaluationResult(
        dimension=DecisionDimension.COST,
        code="cost.landed_unit_cost",
        status=status,
        raw_score=score,
        reason_code=reason,
        expected_value={
            "currency": rfq_currency,
            "best_cost": str(best_comparable_cost),
        },
        actual_value={
            "currency": candidate_currency,
            "landed_unit_cost": str(candidate_cost),
        },
        snapshot_data={
            "best_cost": str(best_comparable_cost),
            "landed_unit_cost": str(candidate_cost),
            "currency": rfq_currency,
        },
    )
