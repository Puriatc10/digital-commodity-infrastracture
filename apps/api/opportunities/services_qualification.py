"""
Authoritative Opportunity Qualification Service (T0608).

Defines the centralized qualification evaluator that validates a persisted
Opportunity against the authoritative Product Specification contract:
- Product Specification §§12 (RFQ), 14 (Supply Listing), 15 (Matching), 17 (Desk),
  18 (Sources), 19 (Data), 20 (Lifecycle), 21 (External Counterparty), 23 (Matching + Opp), 24 (Offer).

Invariants:
- Deterministic, machine-readable qualification issues.
- Enforces Supply vs Demand business differentiation:
  * Supply leads require an Indicative Price (> 0) and Currency.
  * Demand leads have optional Target/Indicative Price (Spec §12).
- Validates active Commodity, positive Quantity, Unit, Geography, Delivery Window,
  Payment Terms, and Broker attribution consistency.
- Contact Attempts and follow-up tasks are NOT prerequisites.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
)
from organizations.models import OrganizationCapability


@dataclass(frozen=True)
class QualificationIssue:
    """Represents a deterministic machine-readable qualification issue."""

    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class QualificationResult:
    """Deterministic result of evaluating an Opportunity's qualification readiness."""

    is_qualifiable: bool
    missing_requirements: list[QualificationIssue]
    invalid_requirements: list[QualificationIssue]

    @property
    def qualifiable(self) -> bool:
        return self.is_qualifiable

    @property
    def all_issues(self) -> list[QualificationIssue]:
        return self.missing_requirements + self.invalid_requirements

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualifiable": self.is_qualifiable,
            "missing_requirements": [i.to_dict() for i in self.missing_requirements],
            "invalid_requirements": [i.to_dict() for i in self.invalid_requirements],
        }


def evaluate_qualification(opportunity: Opportunity) -> QualificationResult:
    """
    Authoritative evaluation of an Opportunity's qualification readiness.

    Validates persisted fields against the exact Product Specification qualification contract.
    Does NOT accept or evaluate transient/unpersisted client payloads.

    Returns:
        QualificationResult with is_qualifiable, missing_requirements, and invalid_requirements.
    """
    missing: list[QualificationIssue] = []
    invalid: list[QualificationIssue] = []

    # 1. Counterparty (Mutually exclusive: internal Organization OR off-platform ExternalCounterparty)
    if not opportunity.organization_id and not opportunity.external_counterparty_id:
        missing.append(
            QualificationIssue(
                field="counterparty",
                code="required",
                message="Opportunity must reference an internal Organization or an ExternalCounterparty.",
            )
        )
    elif opportunity.organization_id and opportunity.external_counterparty_id:
        invalid.append(
            QualificationIssue(
                field="counterparty",
                code="invalid",
                message="Opportunity cannot reference both an internal Organization and an ExternalCounterparty.",
            )
        )
    elif opportunity.external_counterparty_id:
        # Off-platform external counterparty must have a non-blank company name
        ext = opportunity.external_counterparty
        if ext is not None and (not ext.company_name or not ext.company_name.strip()):
            invalid.append(
                QualificationIssue(
                    field="external_counterparty",
                    code="invalid",
                    message="External counterparty must have a non-blank company name.",
                )
            )

    # 2. Commodity (Must reference an active CommodityDefinition)
    if not opportunity.commodity_id:
        missing.append(
            QualificationIssue(
                field="commodity",
                code="required",
                message="Commodity is required for qualification.",
            )
        )
    else:
        commodity = opportunity.commodity
        if commodity is not None and not commodity.is_active:
            invalid.append(
                QualificationIssue(
                    field="commodity",
                    code="inactive_commodity",
                    message="Referenced commodity is inactive and cannot be qualified.",
                )
            )

    # 3. Quantity and Unit
    if opportunity.quantity is None:
        missing.append(
            QualificationIssue(
                field="quantity",
                code="required",
                message="Quantity is required for qualification.",
            )
        )
    elif opportunity.quantity <= Decimal("0"):
        invalid.append(
            QualificationIssue(
                field="quantity",
                code="min_value",
                message="Quantity must be strictly positive.",
            )
        )

    if not opportunity.unit or not str(opportunity.unit).strip():
        missing.append(
            QualificationIssue(
                field="unit",
                code="required",
                message="Unit of measurement is required for qualification.",
            )
        )

    # 4. Geography (Origin / Destination / Location for matching)
    if not opportunity.geography or not str(opportunity.geography).strip():
        missing.append(
            QualificationIssue(
                field="geography",
                code="required",
                message="Geography is required for qualification.",
            )
        )

    # 5. Availability / Delivery Window
    if opportunity.delivery_window_start is None:
        missing.append(
            QualificationIssue(
                field="delivery_window_start",
                code="required",
                message="Delivery window start date is required for qualification.",
            )
        )
    if opportunity.delivery_window_end is None:
        missing.append(
            QualificationIssue(
                field="delivery_window_end",
                code="required",
                message="Delivery window end date is required for qualification.",
            )
        )
    if (
        opportunity.delivery_window_start is not None
        and opportunity.delivery_window_end is not None
        and opportunity.delivery_window_end < opportunity.delivery_window_start
    ):
        invalid.append(
            QualificationIssue(
                field="delivery_window_end",
                code="invalid_date_order",
                message="Delivery window end date must be on or after delivery window start date.",
            )
        )

    # 6. Commercial Terms & Payment Terms
    if not opportunity.payment_terms or not str(opportunity.payment_terms).strip():
        missing.append(
            QualificationIssue(
                field="payment_terms",
                code="required",
                message="Payment terms are required for qualification.",
            )
        )

    # 7. Direction-Specific Commercial Requirements (Supply vs Demand)
    if opportunity.direction == OpportunityDirection.SUPPLY:
        # Supply Opportunity requires Indicative Price (> 0) and Currency (Spec §14, §24)
        if opportunity.indicative_price is None:
            missing.append(
                QualificationIssue(
                    field="indicative_price",
                    code="required",
                    message="Indicative price is required for Supply opportunity qualification.",
                )
            )
        elif opportunity.indicative_price <= Decimal("0"):
            invalid.append(
                QualificationIssue(
                    field="indicative_price",
                    code="min_value",
                    message="Indicative price must be strictly positive for Supply opportunities.",
                )
            )

        if not opportunity.currency or not str(opportunity.currency).strip():
            missing.append(
                QualificationIssue(
                    field="currency",
                    code="required",
                    message="Currency is required for qualification.",
                )
            )
    elif opportunity.direction == OpportunityDirection.DEMAND:
        # Demand Opportunity: Indicative/Target Price is OPTIONAL (Spec §12).
        # If specified, it must be non-negative, and currency must be provided.
        if opportunity.indicative_price is not None:
            if opportunity.indicative_price < Decimal("0"):
                invalid.append(
                    QualificationIssue(
                        field="indicative_price",
                        code="min_value",
                        message="Indicative price cannot be negative.",
                    )
                )
            if not opportunity.currency or not str(opportunity.currency).strip():
                missing.append(
                    QualificationIssue(
                        field="currency",
                        code="required",
                        message="Currency is required when indicative price is specified.",
                    )
                )

    # 8. Broker Attribution Consistency
    if opportunity.source == OpportunitySource.BROKER_REFERRAL:
        if not opportunity.broker_id:
            missing.append(
                QualificationIssue(
                    field="broker",
                    code="required",
                    message="Attributed broker organization is required when source is Broker Referral.",
                )
            )
        else:
            if not OrganizationCapability.objects.filter(
                organization_id=opportunity.broker_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists():
                invalid.append(
                    QualificationIssue(
                        field="broker",
                        code="invalid_broker",
                        message="Attributed organization must possess Broker capability.",
                    )
                )

    is_qualifiable = len(missing) == 0 and len(invalid) == 0
    return QualificationResult(
        is_qualifiable=is_qualifiable,
        missing_requirements=missing,
        invalid_requirements=invalid,
    )
