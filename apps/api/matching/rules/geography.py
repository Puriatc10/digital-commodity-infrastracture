from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from matching.enums import SignalOutcome
from matching.rules.result import RuleResult


class GeographicEvidenceRole(str, Enum):
    SUPPLY_LOCATION = "SUPPLY_LOCATION"
    OPERATING_AREA = "OPERATING_AREA"
    ORIGIN_REQUIREMENT = "ORIGIN_REQUIREMENT"
    DESTINATION = "DESTINATION"


class GeographyConstraintMode(str, Enum):
    REQUIRED = "REQUIRED"
    ALLOWED = "ALLOWED"
    PREFERRED = "PREFERRED"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True)
class GeographyConstraintSnapshot:
    mode: str  # REQUIRED, ALLOWED, PREFERRED, EXCLUDED
    area: Any  # GeographicArea object or area_id
    area_code: str = ""


@dataclass(frozen=True)
class TargetGeographySnapshot:
    constraints: Tuple[GeographyConstraintSnapshot, ...] = ()
    destination_area: Optional[Any] = None
    destination_area_code: str = ""


@dataclass(frozen=True)
class CandidateGeographySnapshot:
    evidence_role: str  # GeographicEvidenceRole
    area: Optional[Any] = None  # GeographicArea object or area_id
    area_code: str = ""
    operating_areas: Tuple[Any, ...] = ()
    has_only_free_text: bool = False
    organization_hq_only: bool = False


class _AreaRelation(str, Enum):
    EXACT = "EXACT"
    DESCENDANT = "DESCENDANT"  # candidate is descendant of target
    ANCESTOR = "ANCESTOR"      # candidate is ancestor of target
    DISJOINT = "DISJOINT"      # unrelated


class _MatchStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


def _get_area_identity(area: Any) -> Tuple[Optional[Any], str]:
    if area is None:
        return None, ""
    area_id = getattr(area, "id", None) or (area if not hasattr(area, "code") else None)
    code = getattr(area, "code", "")
    return area_id, code


def _get_ancestor_ids_and_codes(
    area: Any,
    ancestor_lookup: Optional[Callable[[Any], Tuple[Set[Any], Set[str]]]] = None,
) -> Tuple[Set[Any], Set[str]]:
    if ancestor_lookup is not None:
        return ancestor_lookup(area)

    # If area is a model instance with parent attribute
    ancestor_ids = set()
    ancestor_codes = set()
    curr = getattr(area, "parent", None)
    while curr is not None:
        if getattr(curr, "id", None):
            ancestor_ids.add(curr.id)
        if getattr(curr, "code", None):
            ancestor_codes.add(curr.code)
        curr = getattr(curr, "parent", None)
    return ancestor_ids, ancestor_codes


def _determine_relation(
    candidate_area: Any,
    target_area: Any,
    ancestor_lookup: Optional[Callable[[Any], Tuple[Set[Any], Set[str]]]] = None,
) -> _AreaRelation:
    c_id, c_code = _get_area_identity(candidate_area)
    t_id, t_code = _get_area_identity(target_area)

    # 1. Exact match
    if (c_id and t_id and c_id == t_id) or (c_code and t_code and c_code == t_code):
        return _AreaRelation.EXACT

    # 2. Candidate ancestors vs Target
    c_ancestor_ids, c_ancestor_codes = _get_ancestor_ids_and_codes(candidate_area, ancestor_lookup)
    if (t_id and t_id in c_ancestor_ids) or (t_code and t_code in c_ancestor_codes):
        return _AreaRelation.DESCENDANT

    # 3. Target ancestors vs Candidate
    t_ancestor_ids, t_ancestor_codes = _get_ancestor_ids_and_codes(target_area, ancestor_lookup)
    if (c_id and c_id in t_ancestor_ids) or (c_code and c_code in t_ancestor_codes):
        return _AreaRelation.ANCESTOR

    return _AreaRelation.DISJOINT


def _evaluate_pair(
    evidence_role: str,
    candidate_area: Any,
    target_area: Any,
    ancestor_lookup: Optional[Callable[[Any], Tuple[Set[Any], Set[str]]]] = None,
) -> _MatchStatus:
    rel = _determine_relation(candidate_area, target_area, ancestor_lookup)

    if evidence_role == GeographicEvidenceRole.SUPPLY_LOCATION:
        # Point-like semantics
        if rel in (_AreaRelation.EXACT, _AreaRelation.DESCENDANT):
            return _MatchStatus.MATCH
        elif rel == _AreaRelation.ANCESTOR:
            # Broad point-like evidence (province) does not prove presence in narrower target (city)
            return _MatchStatus.UNKNOWN
        else:
            return _MatchStatus.MISMATCH

    elif evidence_role == GeographicEvidenceRole.OPERATING_AREA:
        # Coverage semantics
        if rel in (_AreaRelation.EXACT, _AreaRelation.ANCESTOR):
            # Province coverage covers city
            return _MatchStatus.MATCH
        else:
            return _MatchStatus.MISMATCH

    # Default fallback
    if rel in (_AreaRelation.EXACT, _AreaRelation.DESCENDANT):
        return _MatchStatus.MATCH
    return _MatchStatus.MISMATCH


def evaluate_geography(
    target: TargetGeographySnapshot,
    candidate: CandidateGeographySnapshot,
    ancestor_lookup: Optional[Callable[[Any], Tuple[Set[Any], Set[str]]]] = None,
) -> RuleResult:
    """
    Pure, side-effect-free geography matching evaluator.

    - Evidence Roles: SUPPLY_LOCATION, OPERATING_AREA, ORIGIN_REQUIREMENT, DESTINATION.
    - Point-like vs Coverage semantics.
    - Constraint Modes: REQUIRED, ALLOWED, PREFERRED, EXCLUDED (with ANY-OF multi-area semantics).
    - No geography constraints -> NOT_APPLICABLE.
    - Free-text only or missing evidence -> UNKNOWN.
    - Organization HQ without explicit operating area -> UNKNOWN.
    """
    expected_constraints = [
        {"mode": c.mode, "area": getattr(c.area, "code", str(c.area))}
        for c in target.constraints
    ]
    expected: Dict[str, Any] = {"constraints": expected_constraints}
    if target.destination_area:
        expected["destination"] = getattr(
            target.destination_area, "code", str(target.destination_area)
        )

    cand_area_str = (
        getattr(candidate.area, "code", str(candidate.area)) if candidate.area else None
    )
    actual: Dict[str, Any] = {
        "evidence_role": candidate.evidence_role,
        "area": cand_area_str,
        "operating_areas": [
            getattr(oa, "code", str(oa)) for oa in candidate.operating_areas
        ],
        "has_only_free_text": candidate.has_only_free_text,
        "organization_hq_only": candidate.organization_hq_only,
    }

    # 1. No requirement
    if not target.constraints:
        return RuleResult(
            code="geography",
            outcome=SignalOutcome.NOT_APPLICABLE,
            is_hard=False,
            raw_score=None,
            reason_code="GEOGRAPHY_NOT_APPLICABLE",
            expected=expected,
            actual=actual,
        )

    # 2. Missing or non-structured candidate evidence
    if candidate.has_only_free_text:
        return RuleResult(
            code="geography",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="GEOGRAPHY_FREE_TEXT_ONLY",
            expected=expected,
            actual=actual,
        )

    if candidate.organization_hq_only:
        return RuleResult(
            code="geography",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="GEOGRAPHY_NO_EXPLICIT_OPERATING_AREA",
            expected=expected,
            actual=actual,
        )

    # Collect candidate areas to evaluate
    candidate_areas: List[Any] = []
    if candidate.area is not None:
        candidate_areas.append(candidate.area)
    if candidate.operating_areas:
        candidate_areas.extend(candidate.operating_areas)

    if not candidate_areas:
        return RuleResult(
            code="geography",
            outcome=SignalOutcome.UNKNOWN,
            is_hard=False,
            raw_score=None,
            reason_code="GEOGRAPHY_MISSING_EVIDENCE",
            expected=expected,
            actual=actual,
        )

    # Helper to evaluate candidate areas against a specific target constraint area
    def check_against_target(t_area: Any) -> _MatchStatus:
        statuses = [
            _evaluate_pair(candidate.evidence_role, c_area, t_area, ancestor_lookup)
            for c_area in candidate_areas
        ]
        if _MatchStatus.MATCH in statuses:
            return _MatchStatus.MATCH
        if _MatchStatus.UNKNOWN in statuses:
            return _MatchStatus.UNKNOWN
        return _MatchStatus.MISMATCH

    # Group constraints by mode
    excluded = [c for c in target.constraints if c.mode == GeographyConstraintMode.EXCLUDED]
    required = [c for c in target.constraints if c.mode == GeographyConstraintMode.REQUIRED]
    allowed = [c for c in target.constraints if c.mode == GeographyConstraintMode.ALLOWED]
    preferred = [c for c in target.constraints if c.mode == GeographyConstraintMode.PREFERRED]

    # 3. EXCLUDED constraints check
    for excl in excluded:
        st = check_against_target(excl.area)
        if st == _MatchStatus.MATCH:
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.FAIL,
                is_hard=True,
                raw_score=Decimal("0.0000"),
                reason_code="GEOGRAPHY_EXCLUDED_VIOLATION",
                expected=expected,
                actual=actual,
            )

    # 4. REQUIRED constraints check (ANY-OF)
    if required:
        req_statuses = [check_against_target(r.area) for r in required]
        if _MatchStatus.MATCH in req_statuses:
            pass  # Required condition satisfied
        elif all(s == _MatchStatus.MISMATCH for s in req_statuses):
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.FAIL,
                is_hard=True,
                raw_score=Decimal("0.0000"),
                reason_code="GEOGRAPHY_REQUIRED_MISMATCH",
                expected=expected,
                actual=actual,
            )
        else:
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.UNKNOWN,
                is_hard=True,
                raw_score=None,
                reason_code="GEOGRAPHY_UNKNOWN_EVIDENCE",
                expected=expected,
                actual=actual,
            )

    # 5. ALLOWED constraints check (ANY-OF)
    if allowed:
        allow_statuses = [check_against_target(a.area) for a in allowed]
        if _MatchStatus.MATCH in allow_statuses:
            pass  # Allowed satisfied
        elif all(s == _MatchStatus.MISMATCH for s in allow_statuses):
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.FAIL,
                is_hard=True,
                raw_score=Decimal("0.0000"),
                reason_code="GEOGRAPHY_NOT_ALLOWED",
                expected=expected,
                actual=actual,
            )
        else:
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.UNKNOWN,
                is_hard=True,
                raw_score=None,
                reason_code="GEOGRAPHY_UNKNOWN_EVIDENCE",
                expected=expected,
                actual=actual,
            )

    # 6. PREFERRED constraints check (ANY-OF)
    if preferred:
        pref_statuses = [check_against_target(p.area) for p in preferred]
        if _MatchStatus.MATCH in pref_statuses:
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.PASS,
                is_hard=False,
                raw_score=Decimal("1.0000"),
                reason_code="GEOGRAPHY_PREFERRED_MATCH",
                expected=expected,
                actual=actual,
            )
        elif all(s == _MatchStatus.MISMATCH for s in pref_statuses):
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.FAIL,
                is_hard=False,
                raw_score=Decimal("0.0000"),
                reason_code="GEOGRAPHY_PREFERRED_MISMATCH",
                expected=expected,
                actual=actual,
            )
        else:
            return RuleResult(
                code="geography",
                outcome=SignalOutcome.UNKNOWN,
                is_hard=False,
                raw_score=None,
                reason_code="GEOGRAPHY_PREFERRED_UNKNOWN",
                expected=expected,
                actual=actual,
            )

    # If required constraints passed and no preferred constraints were specified:
    if required or allowed:
        return RuleResult(
            code="geography",
            outcome=SignalOutcome.PASS,
            is_hard=True,
            raw_score=Decimal("1.0000"),
            reason_code="GEOGRAPHY_REQUIRED_MATCH",
            expected=expected,
            actual=actual,
        )

    # Fallback
    return RuleResult(
        code="geography",
        outcome=SignalOutcome.PASS,
        is_hard=False,
        raw_score=Decimal("1.0000"),
        reason_code="GEOGRAPHY_PASS",
        expected=expected,
        actual=actual,
    )
