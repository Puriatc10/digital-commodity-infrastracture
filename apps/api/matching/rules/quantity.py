from decimal import Decimal
from typing import Optional

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


def evaluate_quantity(
    requested_quantity: Optional[Decimal],
    requested_unit: Optional[str],
    candidate_quantity: Optional[Decimal],
    candidate_unit: Optional[str],
    require_full_fulfillment: bool = False,
) -> RuleResult:
    """
    Quantity matching rule evaluator.

    - Computes coverage ratio = min(candidate / requested, 1.0000) using exact Decimals.
    - Full fulfillment (ratio == 1) -> PASS (raw_score=1.0000).
    - Partial fulfillment (0 < ratio < 1) -> PARTIAL (raw_score=ratio, candidate remains eligible).
    - If require_full_fulfillment is True and ratio < 1 -> FAIL (is_hard=True).
    - Missing quantities or incompatible units -> UNKNOWN (never guessed conversion).
    """
    expected = {
        "quantity": str(requested_quantity) if requested_quantity is not None else None,
        "unit": requested_unit,
        "require_full_fulfillment": require_full_fulfillment,
    }
    actual = {
        "quantity": str(candidate_quantity) if candidate_quantity is not None else None,
        "unit": candidate_unit,
    }

    if requested_quantity is None or candidate_quantity is None:
        return RuleResult(
            code="quantity",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="QUANTITY_MISSING_EVIDENCE",
            expected=expected,
            actual=actual,
        )

    # Unit comparison: no guessed unit conversions
    req_u = requested_unit.strip().upper() if requested_unit else ""
    cand_u = candidate_unit.strip().upper() if candidate_unit else ""
    if req_u != cand_u:
        return RuleResult(
            code="quantity",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="QUANTITY_INCOMPATIBLE_UNITS",
            expected=expected,
            actual=actual,
        )

    req_q = Decimal(str(requested_quantity))
    cand_q = Decimal(str(candidate_quantity))

    if req_q <= Decimal("0"):
        return RuleResult(
            code="quantity",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="QUANTITY_INVALID_REQUESTED",
            expected=expected,
            actual=actual,
        )

    raw_ratio = cand_q / req_q
    capped_ratio = min(raw_ratio, Decimal("1.0000"))
    score = max(Decimal("0.0000"), capped_ratio).quantize(Decimal("0.0001"))

    if score >= Decimal("1.0000"):
        return RuleResult(
            code="quantity",
            outcome=SignalOutcome.PASS,
            is_hard=False,
            raw_score=Decimal("1.0000"),
            reason_code="QUANTITY_FULL_MATCH",
            expected=expected,
            actual=actual,
        )

    if score > Decimal("0.0000"):
        if require_full_fulfillment:
            return RuleResult(
                code="quantity",
                outcome=SignalOutcome.FAIL,
                is_hard=True,
                raw_score=score,
                reason_code="QUANTITY_SHORTAGE_FULL_REQUIRED",
                expected=expected,
                actual=actual,
            )
        return RuleResult(
            code="quantity",
            outcome=SignalOutcome.PARTIAL,
            is_hard=False,
            raw_score=score,
            reason_code="QUANTITY_PARTIAL_MATCH",
            expected=expected,
            actual=actual,
        )

    # score == 0
    return RuleResult(
        code="quantity",
        outcome=SignalOutcome.FAIL,
        is_hard=require_full_fulfillment,
        raw_score=Decimal("0.0000"),
        reason_code="QUANTITY_ZERO",
        expected=expected,
        actual=actual,
    )
