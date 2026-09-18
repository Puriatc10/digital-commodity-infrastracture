from decimal import Decimal

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from trade_hub.models import RFQ

STRUCTURED_PAYMENT_TERMS: frozenset[str] = frozenset({
    "CAD",
    "LC",
    "DLC",
    "SBLC",
    "ADVANCE",
    "NET_30",
    "NET_60",
    "NET_90",
    "DP",
    "DA",
    "TT",
    "ESCROW",
})


def evaluate_payment_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
) -> SignalEvaluationResult:
    """
    Evaluate payment terms signal (Contract §44, T0809).

    Invariants:
    - Only recognized structured comparable payment codes produce a score.
    - Free-text, unstructured, or ambiguous terms produce status=UNKNOWN.
    - Zero heuristic NLP, regex parsing, or LLM interpretation.
    - If RFQ has no payment terms, produces NOT_APPLICABLE.
    - Matching structured term -> PASS (1.0000).
    - Divergent structured term -> PARTIAL (0.5000).
    """
    rfq_raw = (rfq.payment_terms or "").strip()
    cand_raw = (candidate_version.payment_terms or "").strip()

    expected_dict = {"payment_terms": rfq_raw}
    actual_dict = {"payment_terms": cand_raw}

    # 1. Genuinely Not Applicable Guard
    if not rfq_raw:
        return SignalEvaluationResult(
            dimension=DecisionDimension.PAYMENT,
            code="payment.terms_structure",
            status=DecisionSignalStatus.NOT_APPLICABLE,
            raw_score=None,
            reason_code="NO_PAYMENT_TERMS_REQUESTED",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data={},
            is_hard_failure=False,
        )

    cand_upper = cand_raw.upper()
    rfq_upper = rfq_raw.upper()

    # 2. Free-text or Unstructured Guard
    # If term contains multiple words/whitespace or is not in recognized structured vocabulary:
    is_cand_structured = (
        bool(cand_upper)
        and " " not in cand_upper
        and cand_upper in STRUCTURED_PAYMENT_TERMS
    )

    if not is_cand_structured:
        return SignalEvaluationResult(
            dimension=DecisionDimension.PAYMENT,
            code="payment.terms_structure",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="FREE_TEXT_PAYMENT_UNKNOWN",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data={"is_structured": False},
            is_hard_failure=False,
        )

    # 3. Structured Comparison
    if cand_upper == rfq_upper:
        return SignalEvaluationResult(
            dimension=DecisionDimension.PAYMENT,
            code="payment.terms_structure",
            status=DecisionSignalStatus.PASS,
            raw_score=Decimal("1.0000"),
            reason_code="PAYMENT_TERMS_MATCH",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data={"is_structured": True, "canonical_term": cand_upper},
            is_hard_failure=False,
        )

    return SignalEvaluationResult(
        dimension=DecisionDimension.PAYMENT,
        code="payment.terms_structure",
        status=DecisionSignalStatus.PARTIAL,
        raw_score=Decimal("0.5000"),
        reason_code="PAYMENT_TERMS_DEVIATION",
        expected_value=expected_dict,
        actual_value=actual_dict,
        snapshot_data={"is_structured": True, "canonical_term": cand_upper},
        is_hard_failure=False,
    )
