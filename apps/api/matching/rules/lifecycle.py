from typing import Optional

from matching.enums import CandidateKind, SignalOutcome
from matching.rules.result import RuleResult


def evaluate_lifecycle(
    candidate_kind: str,
    status: str,
    direction: Optional[str] = None,
    is_active: bool = True,
) -> RuleResult:
    """
    Source lifecycle eligibility gate.

    - SupplyListing: only 'active' status is usable for matching.
    - SupplyOpportunity: direction must be 'Supply' and status must be 'Qualified'.
    - Organization: is_active must be True.
    - Pure evaluator: NEVER mutates domain entity status or lifecycle.
    """
    expected = {"candidate_kind": candidate_kind}
    actual = {
        "status": status,
        "direction": direction,
        "is_active": is_active,
    }

    if candidate_kind == CandidateKind.SUPPLY_LISTING:
        expected["required_status"] = "active"
        if status.lower() == "active":
            return RuleResult(
                code="source_lifecycle",
                outcome=SignalOutcome.PASS,
                is_hard=True,
                raw_score=None,
                reason_code="LIFECYCLE_SUPPLY_LISTING_ACTIVE",
                expected=expected,
                actual=actual,
            )
        return RuleResult(
            code="source_lifecycle",
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=None,
            reason_code="LIFECYCLE_SUPPLY_LISTING_INACTIVE",
            expected=expected,
            actual=actual,
        )

    if candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY:
        expected["required_direction"] = "Supply"
        expected["required_status"] = "Qualified"
        is_supply = direction is not None and direction.lower() == "supply"
        is_qualified = status.lower() == "qualified"

        if is_supply and is_qualified:
            return RuleResult(
                code="source_lifecycle",
                outcome=SignalOutcome.PASS,
                is_hard=True,
                raw_score=None,
                reason_code="LIFECYCLE_OPPORTUNITY_QUALIFIED_SUPPLY",
                expected=expected,
                actual=actual,
            )
        reason = (
            "LIFECYCLE_OPPORTUNITY_NOT_SUPPLY"
            if not is_supply
            else "LIFECYCLE_OPPORTUNITY_NOT_QUALIFIED"
        )
        return RuleResult(
            code="source_lifecycle",
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=None,
            reason_code=reason,
            expected=expected,
            actual=actual,
        )

    if candidate_kind in (
        CandidateKind.SUPPLIER_ORGANIZATION,
        CandidateKind.BROKER_ORGANIZATION,
    ):
        expected["required_active"] = True
        if is_active:
            return RuleResult(
                code="source_lifecycle",
                outcome=SignalOutcome.PASS,
                is_hard=True,
                raw_score=None,
                reason_code="LIFECYCLE_ORGANIZATION_ACTIVE",
                expected=expected,
                actual=actual,
            )
        return RuleResult(
            code="source_lifecycle",
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=None,
            reason_code="LIFECYCLE_ORGANIZATION_INACTIVE",
            expected=expected,
            actual=actual,
        )

    # Unknown candidate kind defaults to FAIL
    return RuleResult(
        code="source_lifecycle",
        outcome=SignalOutcome.FAIL,
        is_hard=True,
        raw_score=None,
        reason_code="LIFECYCLE_UNKNOWN_CANDIDATE_KIND",
        expected=expected,
        actual=actual,
    )
