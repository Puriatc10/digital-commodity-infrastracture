from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from offers.enums import DecisionDimension, DecisionSignalStatus
from offers.services.decision_fingerprint import sanitize_snapshot_data


@dataclass(frozen=True)
class SignalEvaluationResult:
    """
    Structured analytical outcome returned by a dedicated signal evaluator (Contract §40, T0809).

    Invariants:
    - Pure Decimal raw_score in [0.0000, 1.0000] for known evaluations; None for UNKNOWN / NOT_APPLICABLE.
    - Zero binary float usage.
    - Never localized strings in reason_code.
    - snapshot_data is sanitized and free from private contact/CRM facts.
    - is_hard_failure: indicates if this evaluation result is a hard gate failure rejecting award_eligible.
    """

    dimension: DecisionDimension
    code: str
    status: DecisionSignalStatus
    raw_score: Optional[Decimal]
    reason_code: str
    expected_value: dict[str, Any]
    actual_value: dict[str, Any]
    snapshot_data: dict[str, Any]
    is_hard_failure: bool = False

    def __post_init__(self):
        if not isinstance(self.status, DecisionSignalStatus):
            object.__setattr__(self, "status", DecisionSignalStatus(self.status))
        if not isinstance(self.dimension, DecisionDimension):
            object.__setattr__(self, "dimension", DecisionDimension(self.dimension))

        if self.raw_score is not None:
            if isinstance(self.raw_score, float):
                raise ValueError("Binary float raw_score forbidden. Must use Decimal.")
            if not (Decimal("0.0000") <= self.raw_score <= Decimal("1.0000")):
                raise ValueError(f"raw_score must be between 0 and 1, got {self.raw_score}.")

        if self.status in (DecisionSignalStatus.UNKNOWN, DecisionSignalStatus.NOT_APPLICABLE):
            if self.raw_score is not None:
                raise ValueError(f"raw_score must be None when status is {self.status}.")
        elif self.status in (DecisionSignalStatus.PASS, DecisionSignalStatus.PARTIAL, DecisionSignalStatus.FAIL):
            if self.raw_score is None:
                raise ValueError(f"raw_score cannot be None when status is {self.status}.")

        # Sanitize snapshot_data defensively
        if self.snapshot_data:
            object.__setattr__(self, "snapshot_data", sanitize_snapshot_data(self.snapshot_data))
