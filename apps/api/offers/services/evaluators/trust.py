from decimal import Decimal

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.models import OfferVersion
from offers.services.evaluators.base import SignalEvaluationResult
from organizations.verification.models import VerificationStatus
from trade_hub.models import RFQ


def evaluate_trust_signal(
    rfq: RFQ,
    candidate_version: OfferVersion,
) -> SignalEvaluationResult:
    """
    Evaluate counterparty verification and trust signal (Contract §45, T0809).

    Invariants:
    - Internal Organization verification mapping:
        - Verified            -> 1.0000 (PASS)
        - Basic Verified      -> 0.7000 (PARTIAL)
        - Under Review        -> 0.3000 (PARTIAL)
        - Documents Submitted -> 0.1500 (PARTIAL)
        - Unverified          -> 0.0000 (FAIL, award-eligible)
        - Suspended           -> 0.0000 (FAIL, is_hard_failure=True -> NOT award-eligible)
    - ExternalCounterparty:
        - Evaluates strictly to UNKNOWN (raw_score=None).
        - NEVER inherits entering Broker's trust status.
    - Snapshots exact trust facts immutably.
    """
    offer = candidate_version.offer
    expected_dict = {"verification_status": "verified"}

    # 1. External Counterparty Guard
    if offer.external_counterparty_id or not offer.offering_organization_id:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.UNKNOWN,
            raw_score=None,
            reason_code="EXTERNAL_COUNTERPARTY_UNKNOWN",
            expected_value=expected_dict,
            actual_value={"is_external": True, "trust_status": "UNKNOWN"},
            snapshot_data={"is_external": True, "trust_status": "UNKNOWN"},
            is_hard_failure=False,
        )

    # 2. Internal Organization Verification Resolution
    org = offer.offering_organization
    verification = getattr(org, "verification", None)
    ver_status = (verification.status if verification else VerificationStatus.UNVERIFIED).lower()

    actual_dict = {
        "organization_id": str(org.id),
        "organization_name": org.name,
        "verification_status": ver_status,
        "is_external": False,
    }

    if ver_status == VerificationStatus.VERIFIED:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.PASS,
            raw_score=Decimal("1.0000"),
            reason_code="VERIFIED",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    if ver_status == VerificationStatus.BASIC_VERIFIED:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.PARTIAL,
            raw_score=Decimal("0.7000"),
            reason_code="BASIC_VERIFIED",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    if ver_status == VerificationStatus.UNDER_REVIEW:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.PARTIAL,
            raw_score=Decimal("0.3000"),
            reason_code="UNDER_REVIEW",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    if ver_status == VerificationStatus.DOCUMENTS_SUBMITTED:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.PARTIAL,
            raw_score=Decimal("0.1500"),
            reason_code="DOCUMENTS_SUBMITTED",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=False,
        )

    if ver_status == VerificationStatus.SUSPENDED:
        return SignalEvaluationResult(
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.FAIL,
            raw_score=Decimal("0.0000"),
            reason_code="SUSPENDED_ORGANIZATION",
            expected_value=expected_dict,
            actual_value=actual_dict,
            snapshot_data=actual_dict,
            is_hard_failure=True,  # Suspended organization is NOT award-eligible
        )

    # Default: UNVERIFIED
    return SignalEvaluationResult(
        dimension=DecisionDimension.TRUST,
        code="trust.verification",
        status=DecisionSignalStatus.FAIL,
        raw_score=Decimal("0.0000"),
        reason_code="UNVERIFIED",
        expected_value=expected_dict,
        actual_value=actual_dict,
        snapshot_data=actual_dict,
        is_hard_failure=False,  # Unverified is scored 0.00, but is NOT barred by hard failure
    )
