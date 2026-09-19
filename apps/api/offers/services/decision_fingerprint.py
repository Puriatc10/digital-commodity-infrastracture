from decimal import Decimal
from typing import Any, Mapping, Sequence

from matching.fingerprint import canonical_normalize, compute_fingerprint
from offers.models.decision import DecisionProfileVersion
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from trade_hub.models import RFQ

FORBIDDEN_SNAPSHOT_KEYS = {
    "phone",
    "email",
    "contact_attempts",
    "operator_notes",
    "notes",
    "private_opportunity_data",
    "source_opportunity",
    "source_opportunity_id",
    "source_opportunity_identifier",
}


def sanitize_snapshot_data(data: Any) -> Any:
    """
    Recursively sanitize snapshot data to ensure private CRM and contact fields
    are strictly excluded (T0808, Contract §81).
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in FORBIDDEN_SNAPSHOT_KEYS:
                continue
            sanitized[k] = sanitize_snapshot_data(v)
        return sanitized
    if isinstance(data, (list, tuple)):
        return [sanitize_snapshot_data(item) for item in data]
    return data


def build_canonical_rfq_snapshot(rfq: RFQ) -> dict[str, Any]:
    """
    Build a deterministic, privacy-safe canonical snapshot of RFQ procurement demand.
    """
    delivery_start = getattr(rfq, "delivery_window_start", None) or getattr(rfq, "delivery_start", None)
    delivery_end = getattr(rfq, "delivery_window_end", None) or getattr(rfq, "delivery_end", None)
    data = {
        "rfq_id": str(rfq.id),
        "rfq_number": getattr(rfq, "rfq_number", ""),
        "commodity_id": str(rfq.commodity_id) if rfq.commodity_id else None,
        "schema_version_id": str(rfq.schema_version_id) if rfq.schema_version_id else None,
        "quantity": Decimal(str(rfq.quantity)),
        "quantity_unit": getattr(rfq, "quantity_unit", getattr(rfq, "unit", "")),
        "currency": (rfq.currency or "").strip().upper(),
        "payment_terms": getattr(rfq, "payment_terms", ""),
        "incoterm": getattr(rfq, "incoterm", ""),
        "delivery_start": delivery_start.isoformat() if delivery_start else None,
        "delivery_end": delivery_end.isoformat() if delivery_end else None,
        "specifications": rfq.specifications or {},
    }
    return canonical_normalize(data)




def build_canonical_candidate_item(offer: Offer, version: OfferVersion) -> dict[str, Any]:
    """
    Build a deterministic, privacy-safe canonical snapshot for one candidate OfferVersion.
    Excludes private counterparty contact information, notes, and CRM tracking.
    """
    raw_item = {
        "offer_id": str(offer.id),
        "offer_version_id": str(version.id),
        "version_number": version.version_number,
        "offeror_role": offer.offeror_role,
        "offered_quantity": Decimal(str(version.offered_quantity)),
        "quantity_unit": version.quantity_unit,
        "unit_price": Decimal(str(version.unit_price)),
        "currency": (version.currency or "").strip().upper(),
        "payment_terms": version.payment_terms,
        "delivery_terms": version.delivery_terms,
        "incoterm": version.incoterm,
        "delivery_start": version.delivery_start.isoformat() if version.delivery_start else None,
        "delivery_end": version.delivery_end.isoformat() if version.delivery_end else None,
        "valid_until": version.valid_until.isoformat() if version.valid_until else None,
        "logistics_cost_status": version.logistics_cost_status,
        "logistics_cost_amount": (
            Decimal(str(version.logistics_cost_amount))
            if version.logistics_cost_amount is not None
            else None
        ),
        "specifications": canonical_normalize(version.specifications or {}),
    }
    return sanitize_snapshot_data(raw_item)


def build_canonical_policy_snapshot(profile_version: DecisionProfileVersion) -> dict[str, Any]:
    """
    Build a deterministic canonical snapshot of a DecisionProfileVersion and its dimension weights.
    """
    weights = {}
    for dw in profile_version.dimension_weights.all().order_by("dimension"):
        weights[dw.dimension] = Decimal(str(dw.weight))

    return {
        "profile_code": profile_version.profile.code,
        "version": profile_version.version,
        "minimum_coverage": Decimal(str(profile_version.minimum_coverage)),
        "dimension_weights": weights,
    }


def compute_decision_run_input_fingerprint(
    rfq: RFQ,
    candidate_items: Sequence[tuple[Offer, OfferVersion]],
    profile_version: DecisionProfileVersion,
    engine_version: str = "decision-engine-v1",
) -> str:
    """
    Compute a deterministic SHA-256 fingerprint for a DecisionRun foundation input.

    Invariants:
    - Input components: RFQ snapshot, ordered OfferVersion items, DecisionProfileVersion, engine_version.
    - Candidate items are sorted deterministically by stable key (offer_id).
    - Database insertion order and creation timestamps do NOT affect the fingerprint.
    - Uses exact Decimal representation without floating-point drift.
    """
    # Canonicalize and sort candidates deterministically by offer_id
    serialized_candidates = [
        build_canonical_candidate_item(offer, version)
        for offer, version in candidate_items
    ]
    serialized_candidates.sort(key=lambda item: str(item["offer_id"]))

    payload = {
        "engine_version": engine_version,
        "policy_version": build_canonical_policy_snapshot(profile_version),
        "rfq": build_canonical_rfq_snapshot(rfq),
        "candidates": serialized_candidates,
    }

    return compute_fingerprint(payload)


def compute_decision_run_result_fingerprint(
    run: Any,
    candidate_records: Sequence[Any],
    signals_by_candidate_id: Mapping[Any, Sequence[Any]],
) -> str:
    """
    Compute a deterministic SHA-256 fingerprint for a completed DecisionRun result (Contract §52, T0809).

    Invariants:
    - Canonical components: engine_version, policy_version snapshot, input_fingerprint,
      deterministically ordered candidate results, analytical scores, eligibility outcomes,
      ranks, recommendation status, and structured signals.
    - Excludes all timestamps and auto-generated database PKs.
    - Deterministically sorted by stable offer key (str(offer_id)).
    - Pure Decimal representation without floating-point precision loss.
    - Same semantic input -> identical result fingerprint.
    """
    candidate_payloads = []
    for cand in candidate_records:
        cand_id = cand.id if hasattr(cand, "id") else getattr(cand, "candidate_id", None)
        cand_signals = signals_by_candidate_id.get(cand_id, [])

        sorted_signals = sorted(
            cand_signals,
            key=lambda s: (str(getattr(s, "dimension", "")), str(getattr(s, "code", ""))),
        )
        sig_payloads = []
        for s in sorted_signals:
            w = getattr(s, "weight", None)
            rs = getattr(s, "raw_score", None)
            cb = getattr(s, "contribution", None)
            sig_payloads.append({
                "dimension": str(getattr(s, "dimension", "")),
                "code": str(getattr(s, "code", "")),
                "status": str(getattr(s, "status", "")),
                "weight": Decimal(str(w)) if w is not None else None,
                "raw_score": Decimal(str(rs)) if rs is not None else None,
                "contribution": Decimal(str(cb)) if cb is not None else None,
                "reason_code": str(getattr(s, "reason_code", "")),
                "expected_value": canonical_normalize(getattr(s, "expected_value", {}) or {}),
                "actual_value": canonical_normalize(getattr(s, "actual_value", {}) or {}),
                "snapshot_data": canonical_normalize(sanitize_snapshot_data(getattr(s, "snapshot_data", {}) or {})),
            })

        ds = getattr(cand, "decision_score", None)
        cov = getattr(cand, "evidence_coverage", None)
        eff = getattr(cand, "effective_score", None)

        candidate_payloads.append({
            "offer_id": str(cand.offer_id),
            "offer_version_id": str(cand.offer_version_id),
            "decision_score": Decimal(str(ds)) if ds is not None else None,
            "evidence_coverage": Decimal(str(cov)) if cov is not None else None,
            "effective_score": Decimal(str(eff)) if eff is not None else None,
            "award_eligible": cand.award_eligible,
            "eligibility_reasons": sorted(list(getattr(cand, "eligibility_reasons", []) or [])),
            "rank": cand.rank,
            "is_recommended": getattr(cand, "is_recommended", False),
            "signals": sig_payloads,
        })

    candidate_payloads.sort(key=lambda c: str(c["offer_id"]))

    payload = {
        "engine_version": run.engine_version,
        "policy_version": build_canonical_policy_snapshot(run.decision_profile_version),
        "input_fingerprint": run.input_fingerprint,
        "candidates": candidate_payloads,
    }

    return compute_fingerprint(payload)

