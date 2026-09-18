from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from matching.enums import SignalDimension, SignalOutcome


@dataclass(frozen=True)
class RuleResult:
    """
    Standardized, immutable analytical result produced by a core matching rule evaluator.

    Directly compatible with MatchingSignal persistence attributes in later stages.
    """

    code: str
    outcome: str
    is_hard: bool = False
    raw_score: Optional[Decimal] = None
    reason_code: str = ""
    expected: Optional[Dict[str, Any]] = None
    actual: Optional[Dict[str, Any]] = None
    dimension: Optional[str] = None

    def __post_init__(self):
        if self.outcome not in SignalOutcome.values:
            raise ValueError(
                f"Invalid outcome '{self.outcome}'. Must be one of: {', '.join(SignalOutcome.values)}."
            )
        if self.raw_score is not None:
            if not (Decimal("0.0000") <= self.raw_score <= Decimal("1.0000")):
                raise ValueError(f"raw_score must be between 0 and 1, got {self.raw_score}.")
        if self.dimension is not None and self.dimension not in SignalDimension.values:
            raise ValueError(
                f"Invalid dimension '{self.dimension}'. Must be one of: {', '.join(SignalDimension.values)}."
            )

    @property
    def is_eligible(self) -> bool:
        """A candidate remains eligible unless an applicable hard constraint produces FAIL."""
        if self.is_hard and self.outcome == SignalOutcome.FAIL:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize rule result for snapshotting or explanation logs."""
        data = asdict(self)
        if self.raw_score is not None:
            data["raw_score"] = str(self.raw_score)
        return data
