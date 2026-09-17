from typing import Iterable

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


def evaluate_capability(
    required_capability: str,
    candidate_capabilities: Iterable[str],
) -> RuleResult:
    """
    Capability eligibility gate for supplier or broker paths.

    - Matches required business capability -> PASS (hard=True)
    - Missing required capability -> FAIL (hard=True)
    - Multi-capability organizations pass if the required capability is present.
    - Note: Capability is a business eligibility gate, not an authorization mechanism.
    """
    req = required_capability.strip().lower()
    cand_caps = {c.strip().lower() for c in candidate_capabilities}

    expected = {"required_capability": req}
    actual = {"capabilities": sorted(list(cand_caps))}

    if req in cand_caps:
        return RuleResult(
            code="capability",
            outcome=SignalOutcome.PASS,
            is_hard=True,
            raw_score=None,
            reason_code="CAPABILITY_MATCH",
            expected=expected,
            actual=actual,
        )

    return RuleResult(
        code="capability",
        outcome=SignalOutcome.FAIL,
        is_hard=True,
        raw_score=None,
        reason_code="CAPABILITY_MISMATCH",
        expected=expected,
        actual=actual,
    )
