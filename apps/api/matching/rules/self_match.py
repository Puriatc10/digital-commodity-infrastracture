from typing import Any, Optional

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


def evaluate_self_match(
    rfq_owner_organization_id: Any,
    candidate_organization_id: Optional[Any] = None,
) -> RuleResult:
    """
    Self-match eligibility gate.

    - RFQ owner organization must not match itself as Supplier or Broker.
    - Matches same organization -> FAIL (hard=True, SELF_MATCH_FORBIDDEN).
    - Different organizations -> PASS (hard=True).
    """
    rfq_org_str = str(rfq_owner_organization_id) if rfq_owner_organization_id else ""
    cand_org_str = str(candidate_organization_id) if candidate_organization_id else ""

    expected = {"rfq_owner_organization_id": rfq_org_str}
    actual = {"candidate_organization_id": cand_org_str}

    if rfq_org_str and cand_org_str and rfq_org_str == cand_org_str:
        return RuleResult(
            code="self_match",
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=None,
            reason_code="SELF_MATCH_FORBIDDEN",
            expected=expected,
            actual=actual,
        )

    return RuleResult(
        code="self_match",
        outcome=SignalOutcome.PASS,
        is_hard=True,
        raw_score=None,
        reason_code="SELF_MATCH_PERMITTED",
        expected=expected,
        actual=actual,
    )
