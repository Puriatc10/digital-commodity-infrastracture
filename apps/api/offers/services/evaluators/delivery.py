from datetime import date
from decimal import Decimal
from typing import Optional

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from trade_hub.models import RFQ


def evaluate_delivery_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
) -> SignalEvaluationResult:
    """
    Evaluate delivery signal strictly using structured delivery window dates (Contract §43, T0809).

    Invariants:
    - Zero route or freight cost inference.
    - Deterministic classification:
        - RFQ specified no delivery window -> NOT_APPLICABLE
        - Missing candidate delivery dates -> UNKNOWN
        - Candidate window fully within requested window -> PASS (1.0000)
        - Partial overlap between candidate and requested windows -> PARTIAL (0.5000)
        - No overlap / window mismatch -> FAIL (0.0000)
    """
    rfq_start: Optional[date] = getattr(rfq, "delivery_window_start", None) or getattr(
        rfq, "delivery_start", None
    )
    rfq_end: Optional[date] = getattr(rfq, "delivery_window_end", None) or getattr(
        rfq, "delivery_end", None
    )

    cand_start: Optional[date] = candidate_version.delivery_start
    cand_end: Optional[date] = candidate_version.delivery_end

    expected_dict = {
        "delivery_start": rfq_start.isoformat() if rfq_start else None,
        "delivery_end": rfq_end.isoformat() if rfq_end else None,
    }
    actual_dict = {
        "delivery_start": cand_start.isoformat() if cand_start else None,
        "delivery_end": cand_end.isoformat() if cand_end else None,
    }

    # 1. Genuinely Not Applicable Guard
    if rfq_start is None and rfq_end is None:
        return SignalEvaluationResult(
            dimension=DecisionDimension.DELIVERY,
            code="delivery.window_fit",
            status=DecisionSignalStatus.NOT_APPLICABLE,
            raw_score=None,
            reason_code="NO_DELIVERY_WINDOW_REQUESTED",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data={},
            is_hard_failure=False,
        )

    # 2. Missing Evidence Guard
    if cand_start is None or cand_end is None:
        return SignalEvaluationResult(
            dimension=DecisionDimension.DELIVERY,
            code="delivery.window_fit",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="MISSING_DELIVERY_WINDOW",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data={"missing_evidence": "delivery_dates"},
            is_hard_failure=False,
        )

    # 3. Two-sided requested window
    if rfq_start is not None and rfq_end is not None:
        if cand_start >= rfq_start and cand_end <= rfq_end:
            return SignalEvaluationResult(
                dimension=DecisionDimension.DELIVERY,
                code="delivery.window_fit",
                status=DecisionSignalStatus.PASS,
                raw_score=Decimal("1.0000"),
                reason_code="FULL_DELIVERY_SATISFACTION",
                expected_value=expected_dict,
                actual_value=actual_dict,
                snapshot_data=actual_dict,
                is_hard_failure=False,
            )
        elif cand_start <= rfq_end and cand_end >= rfq_start:
            return SignalEvaluationResult(
                dimension=DecisionDimension.DELIVERY,
                code="delivery.window_fit",
                status=DecisionSignalStatus.PARTIAL,
                raw_score=Decimal("0.5000"),
                reason_code="PARTIAL_DELIVERY_OVERLAP",
                expected_value=expected_dict,
                actual_value=actual_dict,
                snapshot_data=actual_dict,
                is_hard_failure=False,
            )
        else:
            return SignalEvaluationResult(
                dimension=DecisionDimension.DELIVERY,
                code="delivery.window_fit",
                status=DecisionSignalStatus.FAIL,
                raw_score=Decimal("0.0000"),
                reason_code="DELIVERY_WINDOW_MISMATCH",
                expected_value=expected_dict,
                actual_value=actual_dict,
                snapshot_data=actual_dict,
                is_hard_failure=False,
            )

    # 4. Single-sided upper bound
    if rfq_end is not None and rfq_start is None:
        if cand_end <= rfq_end:
            status = DecisionSignalStatus.PASS
            score = Decimal("1.0000")
            reason = "FULL_DELIVERY_SATISFACTION"
        elif cand_start <= rfq_end:
            status = DecisionSignalStatus.PARTIAL
            score = Decimal("0.5000")
            reason = "PARTIAL_DELIVERY_OVERLAP"
        else:
            status = DecisionSignalStatus.FAIL
            score = Decimal("0.0000")
            reason = "DELIVERY_WINDOW_MISMATCH"

        return SignalEvaluationResult(
            dimension=DecisionDimension.DELIVERY,
            code="delivery.window_fit",
            status=status,
            raw_score=score,
            reason_code=reason,
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    # 5. Single-sided lower bound
    if rfq_start is not None and rfq_end is None:
        if cand_start >= rfq_start:
            status = DecisionSignalStatus.PASS
            score = Decimal("1.0000")
            reason = "FULL_DELIVERY_SATISFACTION"
        elif cand_end >= rfq_start:
            status = DecisionSignalStatus.PARTIAL
            score = Decimal("0.5000")
            reason = "PARTIAL_DELIVERY_OVERLAP"
        else:
            status = DecisionSignalStatus.FAIL
            score = Decimal("0.0000")
            reason = "DELIVERY_WINDOW_MISMATCH"

        return SignalEvaluationResult(
            dimension=DecisionDimension.DELIVERY,
            code="delivery.window_fit",
            status=status,
            raw_score=score,
            reason_code=reason,
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    return SignalEvaluationResult(
        dimension=DecisionDimension.DELIVERY,
        code="delivery.window_fit",
        status=DecisionSignalStatus.UNKNOWN,
        raw_score=None,
        reason_code="MISSING_DELIVERY_WINDOW",
        expected_value=expected_dict,
        actual_value=actual_dict,
        snapshot_data={},
        is_hard_failure=False,
    )
