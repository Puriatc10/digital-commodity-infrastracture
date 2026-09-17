from dataclasses import dataclass
from typing import Any, Optional
import uuid

from matching.enums import MatchingAudience


@dataclass(frozen=True)
class CandidateContext:
    """
    Discovery context defining the procurement demand target.

    Contains strictly the attributes required for candidate discovery,
    without embedding scoring state or generic abstractions. Target remains RFQ v1.
    """

    rfq_id: uuid.UUID
    rfq_owner_organization_id: uuid.UUID
    commodity_id: uuid.UUID
    audience: str
    target_rfq: Optional[Any] = None

    def __post_init__(self):
        if self.audience not in MatchingAudience.values:
            raise ValueError(
                f"Invalid audience '{self.audience}'. Must be one of: {', '.join(MatchingAudience.values)}."
            )
        if not isinstance(self.rfq_id, uuid.UUID):
            object.__setattr__(self, "rfq_id", uuid.UUID(str(self.rfq_id)))
        if not isinstance(self.rfq_owner_organization_id, uuid.UUID):
            object.__setattr__(
                self,
                "rfq_owner_organization_id",
                uuid.UUID(str(self.rfq_owner_organization_id)),
            )
        if not isinstance(self.commodity_id, uuid.UUID):
            object.__setattr__(self, "commodity_id", uuid.UUID(str(self.commodity_id)))


@dataclass(frozen=True)
class ActorScope:
    """
    Contextual caller identity and authorization scope.

    Separates system-level roles (Operator/Admin) from organization capabilities.
    """

    user: Any
    organization: Optional[Any] = None
    is_operator_or_admin: bool = False
