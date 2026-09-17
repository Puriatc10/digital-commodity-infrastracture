from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple
import uuid

from matching.enums import CandidateKind, CandidateLane
from matching.rules.geography import CandidateGeographySnapshot, GeographicEvidenceRole
from matching.rules.trust import CandidateTrustSnapshot


@dataclass(frozen=True)
class CandidateAreaRef:
    """
    Structured geographic area reference carrying both canonical code and stable identifier.
    Directly compatible with T0702 evaluate_geography relation determination.
    """

    id: Optional[str] = None
    code: str = ""

    def __str__(self) -> str:
        return self.code or str(self.id or "")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, CandidateAreaRef):
            return (self.id, self.code) == (other.id, other.code)
        if isinstance(other, str):
            return self.id == other or self.code == other
        return False


@dataclass(frozen=True)
class CandidateSnapshot:
    """
    Immutable, normalized candidate snapshot produced by a CandidateProvider.

    Contains exclusively matching-relevant evidence with zero live mutable Django
    model references. Enforces exact lane mapping, typed candidate kind, and
    deterministic stable_candidate_key.
    """

    lane: str
    candidate_kind: str
    source_id: str
    stable_candidate_key: str
    evidence: Dict[str, Any]

    def __post_init__(self):
        if self.lane not in CandidateLane.values:
            raise ValueError(
                f"Invalid candidate lane '{self.lane}'. Must be one of: {', '.join(CandidateLane.values)}."
            )
        if self.candidate_kind not in CandidateKind.values:
            raise ValueError(
                f"Invalid candidate kind '{self.candidate_kind}'. Must be one of: {', '.join(CandidateKind.values)}."
            )

        # Validate exact source kind to lane matrix
        expected_lane_map = {
            CandidateKind.SUPPLY_LISTING: CandidateLane.DIRECT_SUPPLY,
            CandidateKind.SUPPLY_OPPORTUNITY: CandidateLane.DIRECT_SUPPLY,
            CandidateKind.SUPPLIER_ORGANIZATION: CandidateLane.POTENTIAL_SUPPLIER,
            CandidateKind.BROKER_ORGANIZATION: CandidateLane.BROKER_PATH,
        }
        expected_lane = expected_lane_map.get(self.candidate_kind)
        if self.lane != expected_lane:
            raise ValueError(
                f"Candidate kind '{self.candidate_kind}' must map to lane '{expected_lane}', got '{self.lane}'."
            )

        # Canonical stable candidate key format: KIND:UUID
        expected_key = f"{self.candidate_kind}:{self.source_id}"
        if self.stable_candidate_key != expected_key:
            raise ValueError(
                f"Invalid stable_candidate_key '{self.stable_candidate_key}'. Expected '{expected_key}'."
            )

    @classmethod
    def create(
        cls,
        *,
        candidate_kind: str,
        source_id: uuid.UUID | str,
        evidence: Dict[str, Any],
        lane: Optional[str] = None,
    ) -> "CandidateSnapshot":
        """Factory method to create a validated immutable CandidateSnapshot."""
        kind_to_lane = {
            CandidateKind.SUPPLY_LISTING: CandidateLane.DIRECT_SUPPLY,
            CandidateKind.SUPPLY_OPPORTUNITY: CandidateLane.DIRECT_SUPPLY,
            CandidateKind.SUPPLIER_ORGANIZATION: CandidateLane.POTENTIAL_SUPPLIER,
            CandidateKind.BROKER_ORGANIZATION: CandidateLane.BROKER_PATH,
        }
        resolved_lane = lane or kind_to_lane.get(candidate_kind)
        if not resolved_lane:
            raise ValueError(f"Unknown candidate kind '{candidate_kind}'.")

        sid_str = str(source_id)
        stable_key = f"{candidate_kind}:{sid_str}"
        return cls(
            lane=resolved_lane,
            candidate_kind=candidate_kind,
            source_id=sid_str,
            stable_candidate_key=stable_key,
            evidence=dict(evidence),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a clean dictionary representation of this snapshot."""
        return asdict(self)

    def to_candidate_geography_snapshot(self) -> CandidateGeographySnapshot:
        """
        Convert snapshot geography evidence into a structured CandidateGeographySnapshot
        for direct evaluation by the T0702 evaluate_geography engine rule.
        """
        geo = self.evidence.get("geography") or {}
        role = geo.get("evidence_role", GeographicEvidenceRole.SUPPLY_LOCATION)

        area_id = geo.get("area_id")
        area_code = geo.get("area_code", "")
        cand_area = (
            CandidateAreaRef(id=area_id, code=area_code)
            if area_id or area_code
            else None
        )

        operating_areas: Tuple[Any, ...] = ()
        raw_ops = geo.get("operating_areas")
        if raw_ops:
            operating_areas = tuple(
                CandidateAreaRef(
                    id=oa.get("area_id"), code=oa.get("area_code", "")
                )
                if isinstance(oa, dict)
                else (
                    CandidateAreaRef(
                        id=str(getattr(oa, "id", oa)),
                        code=getattr(oa, "code", ""),
                    )
                    if not isinstance(oa, CandidateAreaRef)
                    else oa
                )
                for oa in raw_ops
            )

        return CandidateGeographySnapshot(
            evidence_role=role,
            area=cand_area,
            area_code=area_code,
            operating_areas=operating_areas,
            has_only_free_text=geo.get("has_only_free_text", False),
            organization_hq_only=geo.get("organization_hq_only", False),
        )

    def to_candidate_trust_snapshot(self) -> "CandidateTrustSnapshot":
        """
        Extract normalized trust and verification evidence for the T0704 evaluate_trust rule.
        Guarantees deterministic, audience-safe evaluation without live DB traversal.
        """
        if self.candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY:
            cp = self.evidence.get("counterparty") or {}
            is_external = bool(cp.get("is_external"))
            v_status = cp.get("verification_status") if not is_external else None
            org_id = cp.get("organization_id")
            broker_attr = self.evidence.get("broker_attribution")
            return CandidateTrustSnapshot(
                candidate_kind=self.candidate_kind,
                is_external=is_external,
                verification_status=v_status,
                organization_id=org_id,
                broker_attribution=broker_attr,
            )

        # SUPPLY_LISTING, SUPPLIER_ORGANIZATION, BROKER_ORGANIZATION
        org_id = self.evidence.get("organization_id")
        v_status = self.evidence.get("verification_status")
        return CandidateTrustSnapshot(
            candidate_kind=self.candidate_kind,
            is_external=False,
            verification_status=v_status,
            organization_id=org_id,
            broker_attribution=None,
        )

