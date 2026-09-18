from decimal import Decimal
from typing import Optional, Sequence

from commodities.models import CommodityAttributeDefinition
from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from trade_hub.models import RFQ


def evaluate_quality_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
    *,
    schema_attributes: Optional[Sequence[CommodityAttributeDefinition]] = None,
) -> SignalEvaluationResult:
    """
    Evaluate technical specification quality fit for an OfferVersion (Contract §42, T0809).

    Invariants:
    - Pure and commodity-agnostic; zero commodity-specific branches or hardcoded keys.
    - Bound strictly to rfq.schema_version (historical immutability).
    - Hard requirement failure produces status=FAIL, score=0.0000, and is_hard_failure=True
      (which marks candidate award_eligible = False).
    - Missing technical specification evidence produces status=UNKNOWN, score=None.
    - Full match produces status=PASS, score=1.0000.
    - Soft requirement deviation produces status=PARTIAL, proportional score.
    - If RFQ has no specifications requested, produces NOT_APPLICABLE.
    """
    rfq_specs = rfq.specifications or {}
    offer_specs = candidate_version.specifications or {}

    if not rfq_specs:
        return SignalEvaluationResult(
            dimension=DecisionDimension.QUALITY,
            code="quality.specification_fit",
            status=DecisionSignalStatus.NOT_APPLICABLE,
            raw_score=None,
            reason_code="NO_SPECIFICATIONS_REQUESTED",
            expected_value={},
            actual_value=offer_specs,
            snapshot_data={},
            is_hard_failure=False,
        )

    if schema_attributes is not None:
        attributes = schema_attributes
    elif rfq.schema_version_id and hasattr(rfq, "schema_version") and rfq.schema_version:
        attributes = list(rfq.schema_version.attributes.all())
    else:
        attributes = []

    has_any_target = False
    has_unknown = False
    hard_failed = False
    soft_failed = False
    failed_keys: list[str] = []
    missing_keys: list[str] = []
    matched_count = 0
    total_requested = 0

    for attr in attributes:
        target_val = rfq_specs.get(attr.key)
        if target_val is None:
            continue

        has_any_target = True
        total_requested += 1
        cand_val = offer_specs.get(attr.key)

        if cand_val is None:
            has_unknown = True
            missing_keys.append(attr.key)
            continue

        data_type = attr.data_type
        matches = False

        if data_type in (
            CommodityAttributeDefinition.DataType.NUMBER,
            CommodityAttributeDefinition.DataType.INTEGER,
        ):
            try:
                matches = Decimal(str(cand_val)) == Decimal(str(target_val))
            except Exception:
                has_unknown = True
                missing_keys.append(attr.key)
                continue
        elif data_type == CommodityAttributeDefinition.DataType.BOOLEAN:
            matches = bool(cand_val) == bool(target_val)
        else:
            matches = str(cand_val).strip() == str(target_val).strip()

        if matches:
            matched_count += 1
        else:
            failed_keys.append(attr.key)
            if attr.is_required:
                hard_failed = True
            else:
                soft_failed = True

    if not has_any_target:
        # RFQ specs dictionary had keys not found in attribute definitions
        # Fallback to direct key comparison
        for key, target_val in rfq_specs.items():
            total_requested += 1
            cand_val = offer_specs.get(key)
            if cand_val is None:
                has_unknown = True
                missing_keys.append(key)
            elif str(cand_val).strip() != str(target_val).strip():
                hard_failed = True
                failed_keys.append(key)
            else:
                matched_count += 1

    # Evaluation outcome priority:
    # 1. Hard failure -> FAIL, is_hard_failure=True
    # 2. Missing evidence -> UNKNOWN
    # 3. Soft failure -> PARTIAL
    # 4. Pass -> PASS
    if hard_failed:
        return SignalEvaluationResult(
            dimension=DecisionDimension.QUALITY,
            code="quality.specification_fit",
            status=DecisionSignalStatus.FAIL,
            raw_score=Decimal("0.0000"),
            reason_code="HARD_SPECIFICATION_MISMATCH",
            expected_value=rfq_specs,
            actual_value=offer_specs,
            snapshot_data={
                "failed_keys": failed_keys,
                "missing_keys": missing_keys,
                "matched_count": matched_count,
                "total_requested": total_requested,
            },
            is_hard_failure=True,
        )

    if has_unknown:
        return SignalEvaluationResult(
            dimension=DecisionDimension.QUALITY,
            code="quality.specification_fit",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="MISSING_SPECIFICATION_EVIDENCE",
            expected_value=rfq_specs,
            actual_value=offer_specs,
            snapshot_data={
                "missing_keys": missing_keys,
                "matched_count": matched_count,
                "total_requested": total_requested,
            },
            is_hard_failure=False,
        )

    if soft_failed:
        score = (
            (Decimal(matched_count) / Decimal(total_requested)).quantize(Decimal("0.0001"))
            if total_requested > 0
            else Decimal("0.5000")
        )
        return SignalEvaluationResult(
            dimension=DecisionDimension.QUALITY,
            code="quality.specification_fit",
            status=DecisionSignalStatus.PARTIAL,
            raw_score=score,
            reason_code="SOFT_SPECIFICATION_DEVIATION",
            expected_value=rfq_specs,
            actual_value=offer_specs,
            snapshot_data={
                "failed_keys": failed_keys,
                "matched_count": matched_count,
                "total_requested": total_requested,
            },
            is_hard_failure=False,
        )

    return SignalEvaluationResult(
        dimension=DecisionDimension.QUALITY,
        code="quality.specification_fit",
        status=DecisionSignalStatus.PASS,
        raw_score=Decimal("1.0000"),
        reason_code="SPECIFICATIONS_MATCH",
        expected_value=rfq_specs,
        actual_value=offer_specs,
        snapshot_data={
            "matched_count": matched_count,
            "total_requested": total_requested,
        },
        is_hard_failure=False,
    )
