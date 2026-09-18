from datetime import date
from decimal import Decimal
from typing import Optional

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


def evaluate_availability(
    requested_start: Optional[date],
    requested_end: Optional[date],
    candidate_start: Optional[date],
    candidate_end: Optional[date],
) -> RuleResult:
    """
    Availability matching rule evaluator based on calendar date intervals.

    - Full coverage of requested delivery window -> PASS (raw_score=1.0000).
    - Partial overlap -> PARTIAL (raw_score=overlap_days / requested_days, is_hard=False).
    - No overlap -> FAIL (hard=True, raw_score=0.0000).
    - Missing date bounds -> UNKNOWN (never guess dates).
    """
    expected = {
        "start": requested_start.isoformat() if requested_start else None,
        "end": requested_end.isoformat() if requested_end else None,
    }
    actual = {
        "start": candidate_start.isoformat() if candidate_start else None,
        "end": candidate_end.isoformat() if candidate_end else None,
    }

    if not requested_start or not requested_end or not candidate_start or not candidate_end:
        return RuleResult(
            code="availability",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="AVAILABILITY_MISSING_EVIDENCE",
            expected=expected,
            actual=actual,
        )

    if requested_end < requested_start or candidate_end < candidate_start:
        return RuleResult(
            code="availability",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="AVAILABILITY_INVALID_WINDOW",
            expected=expected,
            actual=actual,
        )

    overlap_start = max(requested_start, candidate_start)
    overlap_end = min(requested_end, candidate_end)

    if overlap_end < overlap_start:
        return RuleResult(
            code="availability",
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=Decimal("0.0000"),
            reason_code="AVAILABILITY_NO_OVERLAP",
            expected=expected,
            actual=actual,
        )

    if candidate_start <= requested_start and candidate_end >= requested_end:
        return RuleResult(
            code="availability",
            outcome=SignalOutcome.PASS,
            is_hard=False,
            raw_score=Decimal("1.0000"),
            reason_code="AVAILABILITY_FULL_MATCH",
            expected=expected,
            actual=actual,
        )

    overlap_days = (overlap_end - overlap_start).days + 1
    requested_days = (requested_end - requested_start).days + 1

    ratio = (Decimal(overlap_days) / Decimal(requested_days)).quantize(Decimal("0.0001"))
    ratio = min(ratio, Decimal("1.0000"))

    return RuleResult(
        code="availability",
        outcome=SignalOutcome.PARTIAL,
        is_hard=False,
        raw_score=ratio,
        reason_code="AVAILABILITY_PARTIAL_OVERLAP",
        expected=expected,
        actual=actual,
    )
