from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from matching.enums import CandidateKind, SignalDimension, SignalOutcome
from matching.rules.result import RuleResult
from organizations.verification.models import OrganizationVerification, VerificationStatus


@dataclass(frozen=True)
class CandidateTrustSnapshot:
    """
    Structured trust and verification evidence extracted from a CandidateSnapshot.
    Guarantees pure analytical evaluation without live database traversal.
    """

    candidate_kind: str
    is_external: bool
    verification_status: Optional[str] = None
    organization_id: Optional[str] = None
    broker_attribution: Optional[Dict[str, Any]] = None


class TrustReasonCode(str, Enum):
    TRUST_VERIFIED = "TRUST_VERIFIED"
    TRUST_BASIC_VERIFIED = "TRUST_BASIC_VERIFIED"
    TRUST_UNDER_REVIEW = "TRUST_UNDER_REVIEW"
    TRUST_DOCUMENTS_SUBMITTED = "TRUST_DOCUMENTS_SUBMITTED"
    TRUST_UNVERIFIED = "TRUST_UNVERIFIED"
    TRUST_SUSPENDED = "TRUST_SUSPENDED"
    TRUST_EXTERNAL_COUNTERPARTY = "TRUST_EXTERNAL_COUNTERPARTY"
    TRUST_UNKNOWN = "TRUST_UNKNOWN"
    TRUST_NOT_APPLICABLE = "TRUST_NOT_APPLICABLE"


@dataclass(frozen=True)
class VerificationRuleSnapshot:
    """
    Normalized, immutable rule snapshot defining the trust score and eligibility
    for a specific organization verification status.
    """

    verification_state: str
    raw_score: Optional[Decimal]
    hard_exclude: bool = False


DEFAULT_VERIFICATION_RULES: Dict[str, VerificationRuleSnapshot] = {
    VerificationStatus.VERIFIED.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.VERIFIED.value,
        raw_score=Decimal("1.00"),
        hard_exclude=False,
    ),
    VerificationStatus.BASIC_VERIFIED.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.BASIC_VERIFIED.value,
        raw_score=Decimal("0.70"),
        hard_exclude=False,
    ),
    VerificationStatus.UNDER_REVIEW.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.UNDER_REVIEW.value,
        raw_score=Decimal("0.30"),
        hard_exclude=False,
    ),
    VerificationStatus.DOCUMENTS_SUBMITTED.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.DOCUMENTS_SUBMITTED.value,
        raw_score=Decimal("0.15"),
        hard_exclude=False,
    ),
    VerificationStatus.UNVERIFIED.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.UNVERIFIED.value,
        raw_score=Decimal("0.00"),
        hard_exclude=False,
    ),
    VerificationStatus.SUSPENDED.value: VerificationRuleSnapshot(
        verification_state=VerificationStatus.SUSPENDED.value,
        raw_score=None,
        hard_exclude=True,
    ),
}


def materialize_verification_rules(
    policy_version: Optional[Any] = None,
) -> Dict[str, VerificationRuleSnapshot]:
    """
    Materializes an immutable mapping of verification state -> VerificationRuleSnapshot
    for pure, deterministic matching rule evaluation.

    If the supplied policy_version contains persisted VerificationMatchingRule records,
    those rules are loaded and override/complete the mapping for that policy version.
    If no persisted rules exist or policy_version is None, the canonical approved
    defaults are used.
    """
    rules = dict(DEFAULT_VERIFICATION_RULES)
    if policy_version is None:
        return rules

    if hasattr(policy_version, "verification_rules"):
        persisted_rules = list(policy_version.verification_rules.all())
    else:
        from matching.models.verification_rule import VerificationMatchingRule
        persisted_rules = list(
            VerificationMatchingRule.objects.filter(policy_version=policy_version)
        )

    for pr in persisted_rules:
        rules[pr.verification_state] = VerificationRuleSnapshot(
            verification_state=pr.verification_state,
            raw_score=pr.raw_score,
            hard_exclude=pr.hard_exclude,
        )
    return rules


def resolve_candidate_trust_evidence(
    candidate: Any,
) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    Resolve (verification_status, is_external, organization_id) from a candidate snapshot.

    Source-of-truth semantics:
    - ExternalCounterparty: strictly external -> (None, True, None)
    - Internal Organization:
      If verification_status is explicitly recorded in evidence, use it.
      If absent from evidence, check DB for OrganizationVerification row;
      if no row exists, maps to 'unverified'.
    """
    if isinstance(candidate, CandidateTrustSnapshot):
        v_status = candidate.verification_status
        is_external = candidate.is_external
        org_id = candidate.organization_id
    elif hasattr(candidate, "to_candidate_trust_snapshot"):
        trust_snap = candidate.to_candidate_trust_snapshot()
        v_status = trust_snap.verification_status
        is_external = trust_snap.is_external
        org_id = trust_snap.organization_id
    elif hasattr(candidate, "candidate_kind") and hasattr(candidate, "evidence"):
        if candidate.candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY:
            cp = candidate.evidence.get("counterparty") or {}
            is_external = bool(cp.get("is_external"))
            v_status = cp.get("verification_status") if not is_external else None
            org_id = cp.get("organization_id")
        else:
            is_external = False
            v_status = candidate.evidence.get("verification_status")
            org_id = candidate.evidence.get("organization_id")
    elif isinstance(candidate, dict):
        is_external = bool(candidate.get("is_external"))
        v_status = candidate.get("verification_status")
        org_id = candidate.get("organization_id")
    else:
        is_external = getattr(candidate, "is_external", False)
        v_status = getattr(candidate, "verification_status", None)
        org_id = getattr(candidate, "organization_id", None)

    if is_external:
        return (None, True, None)

    # If verification_status was not set in snapshot evidence but organization_id is known:
    if v_status is None and org_id:
        row_status = (
            OrganizationVerification.objects.filter(organization_id=org_id)
            .values_list("status", flat=True)
            .first()
        )
        v_status = row_status if row_status else VerificationStatus.UNVERIFIED.value
    elif v_status is None and not org_id:
        v_status = VerificationStatus.UNVERIFIED.value

    return (v_status, False, str(org_id) if org_id else None)


def evaluate_trust(
    candidate: Any,
    policy_version: Optional[Any] = None,
    rules_by_state: Optional[Dict[str, VerificationRuleSnapshot]] = None,
) -> RuleResult:
    """
    Deterministic, side-effect-free evaluator for candidate trust / verification signals.

    Invariants:
    1. ExternalCounterparty produces UNKNOWN, raw_score=None, is_hard=False.
    2. Broker referral attribution never leaks into external counterparty trust.
    3. Suspended candidates always produce FAIL with is_hard=True, raw_score=None.
    4. Unverified candidates produce FAIL with is_hard=False, raw_score=Decimal('0.00').
    5. Missing OrganizationVerification row for internal organizations maps to Unverified.
    6. Exact Decimal arithmetic; no floats.
    7. Respects versioned rules configured on policy_version if present.
    """
    v_status, is_external, org_id = resolve_candidate_trust_evidence(candidate)

    # 1. External Counterparty mandatory isolation
    if is_external:
        return RuleResult(
            code="trust",
            dimension=SignalDimension.TRUST.value,
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code=TrustReasonCode.TRUST_EXTERNAL_COUNTERPARTY.value,
            expected={"requires_known_trust": False},
            actual={
                "counterparty_kind": "ExternalCounterparty",
                "is_external": True,
                "verification_status": None,
            },
        )

    # 2. Materialize versioned rules
    if rules_by_state is not None:
        rules = rules_by_state
    else:
        rules = materialize_verification_rules(policy_version)

    normalized_status = v_status.lower() if v_status else VerificationStatus.UNVERIFIED.value
    rule = rules.get(normalized_status)

    if rule is None:
        return RuleResult(
            code="trust",
            dimension=SignalDimension.TRUST.value,
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code=TrustReasonCode.TRUST_UNKNOWN.value,
            expected={"valid_states": sorted(rules.keys())},
            actual={"verification_status": normalized_status, "is_external": False},
        )

    expected = {
        "min_score": str(Decimal("0.00")),
        "exclude_suspended": True,
    }
    actual = {
        "verification_status": normalized_status,
        "is_external": False,
        "organization_id": org_id,
    }

    # 3. Hard Exclusion (Suspended)
    if rule.hard_exclude:
        reason = (
            TrustReasonCode.TRUST_SUSPENDED.value
            if normalized_status == VerificationStatus.SUSPENDED.value
            else f"TRUST_{normalized_status.upper()}_EXCLUDED"
        )
        return RuleResult(
            code="trust",
            dimension=SignalDimension.TRUST.value,
            outcome=SignalOutcome.FAIL,
            is_hard=True,
            raw_score=None,
            reason_code=reason,
            expected=expected,
            actual=actual,
        )

    # 4. Standard scoring mapping
    score = rule.raw_score if rule.raw_score is not None else Decimal("0.00")

    if score >= Decimal("1.00"):
        outcome = SignalOutcome.PASS
    elif score <= Decimal("0.00"):
        outcome = SignalOutcome.FAIL
    else:
        outcome = SignalOutcome.PARTIAL

    reason_code_map = {
        VerificationStatus.VERIFIED.value: TrustReasonCode.TRUST_VERIFIED.value,
        VerificationStatus.BASIC_VERIFIED.value: TrustReasonCode.TRUST_BASIC_VERIFIED.value,
        VerificationStatus.UNDER_REVIEW.value: TrustReasonCode.TRUST_UNDER_REVIEW.value,
        VerificationStatus.DOCUMENTS_SUBMITTED.value: TrustReasonCode.TRUST_DOCUMENTS_SUBMITTED.value,
        VerificationStatus.UNVERIFIED.value: TrustReasonCode.TRUST_UNVERIFIED.value,
    }
    reason = reason_code_map.get(
        normalized_status, f"TRUST_{normalized_status.upper()}"
    )

    return RuleResult(
        code="trust",
        dimension=SignalDimension.TRUST.value,
        outcome=outcome,
        is_hard=False,
        raw_score=score,
        reason_code=reason,
        expected=expected,
        actual=actual,
    )
