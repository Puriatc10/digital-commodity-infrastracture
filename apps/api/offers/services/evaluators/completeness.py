from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.utils import timezone

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from offers.services.evaluators.payment import STRUCTURED_PAYMENT_TERMS
from offers.services.normalization import NormalizedOfferVersion
from trade_hub.models import RFQ


def evaluate_completeness_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
    candidate_normalized: NormalizedOfferVersion,
    *,
    reference_time: Optional[timezone.datetime] = None,
) -> SignalEvaluationResult:
    """
    Evaluate commercial completeness based on presence of decision-critical fields (Contract §46, T0809).

    Invariants:
    - Strictly deterministic evaluation of 5 critical commercial dimensions:
        1. cost_complete: normalisation completed with complete landed cost evidence.
        2. delivery_complete: delivery_start, delivery_end, and incoterm present.
        3. payment_complete: payment_terms present and conforms to structured vocabulary.
        4. specifications_complete: non-empty specifications dictionary.
        5. validity_complete: valid_until present and unexpired.
    - Zero reward for verbosity, note length, or character counts.
    - Pure Decimal scoring: (completed_count / 5).
    """
    now = reference_time or timezone.now()

    checks = {
        "cost_evidence": bool(candidate_normalized.normalization_complete),
        "delivery_data": bool(
            candidate_version.delivery_start
            and candidate_version.delivery_end
            and (candidate_version.incoterm or "").strip()
        ),
        "payment_structure": bool(
            (candidate_version.payment_terms or "").strip().upper() in STRUCTURED_PAYMENT_TERMS
        ),
        "technical_payload": bool(
            candidate_version.specifications
            and isinstance(candidate_version.specifications, dict)
            and len(candidate_version.specifications) > 0
        ),
        "proposal_validity": bool(
            candidate_version.valid_until and candidate_version.valid_until > now
        ),
    }

    met_criteria = [k for k, v in checks.items() if v]
    missing_criteria = [k for k, v in checks.items() if not v]
    completed_count = len(met_criteria)

    score = (Decimal(completed_count) / Decimal("5")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    if completed_count == 5:
        status = DecisionSignalStatus.PASS
        reason = "COMMERCIAL_DATA_COMPLETE"
    elif completed_count > 0:
        status = DecisionSignalStatus.PARTIAL
        reason = "COMMERCIAL_DATA_PARTIAL"
    else:
        status = DecisionSignalStatus.FAIL
        reason = "COMMERCIAL_DATA_INCOMPLETE"

    expected_dict = {k: True for k in checks.keys()}
    actual_dict = checks

    return SignalEvaluationResult(
        dimension=DecisionDimension.COMPLETENESS,
        code="completeness.decision_fields",
        status=status,
        raw_score=score,
        reason_code=reason,
        expected_value=expected_dict,
        actual_value=actual_dict,
        snapshot_data={
            "met_criteria": met_criteria,
            "missing_criteria": missing_criteria,
            "completed_count": completed_count,
            "total_criteria": 5,
        },
        is_hard_failure=False,
    )
