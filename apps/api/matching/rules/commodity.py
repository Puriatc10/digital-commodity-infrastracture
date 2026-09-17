from typing import Any, Iterable, Optional

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


def evaluate_commodity(
    requested_commodity_id: Any,
    candidate_commodity_id: Optional[Any] = None,
    candidate_supported_commodity_ids: Optional[Iterable[Any]] = None,
) -> RuleResult:
    """
    Exact commodity identity gate.

    - Exact ID match -> PASS (hard=True)
    - Mismatch -> FAIL (hard=True, candidate ineligible)
    - No category or label similarity guessing.
    """
    req_str = str(requested_commodity_id) if requested_commodity_id else ""
    cand_str = str(candidate_commodity_id) if candidate_commodity_id else ""
    supported_set = (
        {str(c) for c in candidate_supported_commodity_ids}
        if candidate_supported_commodity_ids
        else set()
    )

    expected = {"commodity_id": req_str}
    actual = {
        "commodity_id": cand_str,
        "supported_commodity_ids": sorted(list(supported_set)),
    }

    matched = False
    if cand_str and req_str == cand_str:
        matched = True
    elif not cand_str and req_str in supported_set:
        matched = True

    if matched:
        return RuleResult(
            code="commodity",
            outcome=SignalOutcome.PASS,
            is_hard=True,
            raw_score=None,
            reason_code="COMMODITY_MATCH",
            expected=expected,
            actual=actual,
        )
    return RuleResult(
        code="commodity",
        outcome=SignalOutcome.FAIL,
        is_hard=True,
        raw_score=None,
        reason_code="COMMODITY_MISMATCH",
        expected=expected,
        actual=actual,
    )
