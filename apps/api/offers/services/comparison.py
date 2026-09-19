from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Optional, Sequence
import uuid

from django.db import connection, transaction
from django.utils import timezone

from commodities.models import CommodityAttributeDefinition
from offers.exceptions import OfferNotFoundError, OfferValidationError
from offers.models import Offer, OfferVersion
from offers.services.normalization import NormalizedOfferVersion, normalize_offer_version
from trade_hub.models import RFQ


class CostComparability(StrEnum):
    """
    Explicit machine-readable comparability classification for commercial costs.
    (Contract §37, T0806).
    """

    COMPARABLE = "COMPARABLE"
    CROSS_CURRENCY_UNKNOWN = "CROSS_CURRENCY_UNKNOWN"
    INCOMPLETE_COST = "INCOMPLETE_COST"


class TechnicalComplianceStatus(StrEnum):
    """
    Structured outcome of dynamic commodity specification compliance.
    (Contract §22, §42, T0806).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ComparisonRow:
    """
    Typed, safe commercial comparison row for a single Offer thread's current submitted version.
    (Contract §36, T0806).

    Invariants:
    - Current Submitted Version only: Drafts and older versions excluded.
    - Safe offeror identity: strictly excludes phone, email, private notes, CRM data.
    - Exact Decimal monetary and quantity values; never binary float.
    - Zero ranking, scoring, recommendation bias, or sorting by favorability.
    """

    offer_id: uuid.UUID
    offer_version_id: uuid.UUID
    version_number: int
    safe_offeror_identity: str
    offeror_name: str
    is_external: bool
    offeror_role: str

    offered_quantity: Decimal
    quantity_unit: str
    quantity_coverage: Decimal
    surplus_quantity: Decimal

    unit_price: Decimal
    currency: str

    product_cost: Decimal
    known_cost_total: Decimal
    landed_cost: Optional[Decimal]
    landed_unit_cost: Optional[Decimal]
    normalization_complete: bool
    missing_components: tuple[str, ...]
    cost_comparability: CostComparability

    payment_terms: str
    delivery_terms: str
    incoterm: str
    delivery_start: Optional[date]
    delivery_end: Optional[date]
    valid_until: Optional[datetime]
    is_expired: bool

    technical_compliance: TechnicalComplianceStatus
    trust_status: str

    aggregate_version: int = 1

    # Operator-only safe provenance (None for Buyer projection)
    source_opportunity_id: Optional[uuid.UUID] = None
    source_opportunity_identifier: Optional[str] = None
    entered_by_operator: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for DRF serialization."""
        return {
            "offer_id": str(self.offer_id),
            "offer_version_id": str(self.offer_version_id),
            "version_number": self.version_number,
            "safe_offeror_identity": self.safe_offeror_identity,
            "offeror_name": self.offeror_name,
            "is_external": self.is_external,
            "offeror_role": self.offeror_role,
            "offered_quantity": str(self.offered_quantity),
            "quantity_unit": self.quantity_unit,
            "quantity_coverage": str(self.quantity_coverage),
            "surplus_quantity": str(self.surplus_quantity),
            "unit_price": str(self.unit_price),
            "currency": self.currency,
            "product_cost": str(self.product_cost),
            "known_cost_total": str(self.known_cost_total),
            "landed_cost": str(self.landed_cost) if self.landed_cost is not None else None,
            "landed_unit_cost": str(self.landed_unit_cost) if self.landed_unit_cost is not None else None,
            "normalization_complete": self.normalization_complete,
            "missing_components": list(self.missing_components),
            "cost_comparability": self.cost_comparability.value,
            "payment_terms": self.payment_terms,
            "delivery_terms": self.delivery_terms,
            "incoterm": self.incoterm,
            "delivery_start": self.delivery_start.isoformat() if self.delivery_start else None,
            "delivery_end": self.delivery_end.isoformat() if self.delivery_end else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "is_expired": self.is_expired,
            "technical_compliance": self.technical_compliance.value,
            "trust_status": self.trust_status,
            "aggregate_version": self.aggregate_version,
            "source_opportunity_id": str(self.source_opportunity_id) if self.source_opportunity_id else None,
            "source_opportunity_identifier": self.source_opportunity_identifier,
            "entered_by_operator": self.entered_by_operator,
        }


@dataclass(frozen=True)
class RFQComparison:
    """
    Complete procurement comparison envelope for one RFQ.
    """

    rfq_id: uuid.UUID
    rfq_quantity: Decimal
    rfq_unit: str
    rfq_currency: str
    total_offers: int
    items: tuple[ComparisonRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rfq_id": str(self.rfq_id),
            "rfq_quantity": str(self.rfq_quantity),
            "rfq_unit": self.rfq_unit,
            "rfq_currency": self.rfq_currency,
            "total_offers": self.total_offers,
            "items": [item.to_dict() for item in self.items],
            "offers": [item.to_dict() for item in self.items],
        }


def evaluate_technical_compliance(
    rfq: RFQ,
    offer_version: OfferVersion,
    *,
    schema_attributes: Optional[Sequence[CommodityAttributeDefinition]] = None,
) -> TechnicalComplianceStatus:
    """
    Pure and commodity-agnostic evaluation of technical specification compliance.

    Compares RFQ requested specifications against OfferVersion offered specifications
    using the exact historical attribute definitions bound to rfq.schema_version.

    CRITICAL INVARIANT:
    - Uses rfq.schema_version ONLY.
    - NEVER queries or substitutes commodity.active_schema_version.
    - Zero commodity-specific branches or hardcoded attribute keys.
    """
    rfq_specs = rfq.specifications or {}
    offer_specs = offer_version.specifications or {}

    # Resolve attribute definitions from the historical schema_version
    if schema_attributes is not None:
        attributes = schema_attributes
    else:
        attributes = list(rfq.schema_version.attributes.all())

    # If RFQ specified no target specifications, no constraints to fail
    has_any_target = False
    has_unknown = False

    for attr in attributes:
        target_val = rfq_specs.get(attr.key)
        if target_val is None:
            # Attribute not requested by RFQ
            continue

        has_any_target = True
        candidate_val = offer_specs.get(attr.key)
        if candidate_val is None:
            # Required spec missing from OfferVersion
            has_unknown = True
            continue

        # Evaluate based on generic data type
        data_type = attr.data_type
        if data_type == CommodityAttributeDefinition.DataType.NUMBER:
            try:
                cand_dec = Decimal(str(candidate_val))
                tgt_dec = Decimal(str(target_val))
                if cand_dec != tgt_dec:
                    return TechnicalComplianceStatus.FAIL
            except Exception:
                has_unknown = True
        elif data_type in (
            CommodityAttributeDefinition.DataType.STRING,
            CommodityAttributeDefinition.DataType.ENUM,
        ):
            if str(candidate_val).strip() != str(target_val).strip():
                return TechnicalComplianceStatus.FAIL
        elif data_type == CommodityAttributeDefinition.DataType.BOOLEAN:
            if bool(candidate_val) != bool(target_val):
                return TechnicalComplianceStatus.FAIL
        else:
            # Fallback exact string match
            if str(candidate_val).strip() != str(target_val).strip():
                return TechnicalComplianceStatus.FAIL

    if not has_any_target:
        return TechnicalComplianceStatus.PASS

    if has_unknown:
        return TechnicalComplianceStatus.UNKNOWN

    return TechnicalComplianceStatus.PASS


def _resolve_rfq(rfq_or_id: Any) -> RFQ:
    if isinstance(rfq_or_id, RFQ):
        return rfq_or_id
    if isinstance(rfq_or_id, (str, uuid.UUID)):
        rfq = (
            RFQ.objects.filter(pk=rfq_or_id)
            .select_related("organization", "commodity", "schema_version")
            .first()
        )
        if not rfq:
            raise OfferNotFoundError(f"RFQ '{rfq_or_id}' does not exist.")
        return rfq
    raise OfferValidationError(f"Invalid RFQ input: '{rfq_or_id}'.")


def compare_rfq_offers(
    rfq: RFQ | uuid.UUID | str,
    actor: Any = None,
    *,
    is_operator: bool = False,
) -> RFQComparison:
    """
    Expose current commercial comparison for an RFQ across all Offer threads (T0806).

    Invariants:
    - Current Version Only: evaluates each Offer thread's current_submitted_version.
      Unsubmitted drafts and older superseded submitted versions are strictly excluded.
    - PostgreSQL REPEATABLE READ snapshot consistency where practical.
    - Neutral deterministic ordering: strictly ordered by (created_at, id), never ranked.
    - Reuses T0805 normalize_offer_version without formula duplication or mutation.
    - Decimal arithmetic end-to-end; no binary float conversions.
    - Distinguishes unknown logistics from zero extra cost.
    - Compares same-currency costs; flags cross-currency as CROSS_CURRENCY_UNKNOWN without FX.
    - Pure derived comparison; zero decision support scoring or recommendations.
    """
    with transaction.atomic():
        if connection.vendor == "postgresql" and len(connection.savepoint_ids) == 0:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

        rfq_obj = _resolve_rfq(rfq)

        # Preload historical schema attributes once to avoid N+1 queries
        schema_attributes = list(rfq_obj.schema_version.attributes.all())

        # Efficient query loading: prefetch cost components and select related parties
        offers = (
            Offer.objects.filter(rfq=rfq_obj, current_submitted_version__isnull=False)
            .select_related(
                "current_submitted_version",
                "current_submitted_version__schema_version",
                "offering_organization",
                "offering_organization__verification",
                "external_counterparty",
                "source_opportunity",
            )
            .prefetch_related(
                "current_submitted_version__cost_components",
            )
            .order_by("created_at", "id")
        )

        rfq_qty = Decimal(str(rfq_obj.quantity))
        now = timezone.now()
        comparison_rows: list[ComparisonRow] = []

        for offer in offers:
            version = offer.current_submitted_version
            if not version:
                continue

            # Safe Offeror Identity
            if offer.external_counterparty_id and offer.external_counterparty:
                safe_name = offer.external_counterparty.company_name
                is_ext = True
                trust = "UNKNOWN"
            elif offer.offering_organization_id and offer.offering_organization:
                safe_name = offer.offering_organization.name
                is_ext = False
                verification = getattr(offer.offering_organization, "verification", None)
                trust = verification.status.upper() if verification else "UNVERIFIED"
            else:
                safe_name = "Unknown"
                is_ext = False
                trust = "UNKNOWN"

            # Offered Quantity & Coverage (Decimal)
            offered_qty = Decimal(str(version.offered_quantity))
            if rfq_qty > Decimal("0"):
                coverage = min(offered_qty / rfq_qty, Decimal("1.0000"))
                surplus = max(offered_qty - rfq_qty, Decimal("0.000"))
            else:
                coverage = Decimal("1.0000")
                surplus = offered_qty

            # T0805 Normalization Engine Call
            normalized: NormalizedOfferVersion = normalize_offer_version(
                version,
                cost_components=version.cost_components.all(),
            )

            # Cost Comparability Concept
            version_currency = (version.currency or "").strip().upper()
            rfq_currency = (rfq_obj.currency or "").strip().upper()

            if version_currency != rfq_currency:
                cost_comp = CostComparability.CROSS_CURRENCY_UNKNOWN
            elif normalized.landed_cost is None:
                cost_comp = CostComparability.INCOMPLETE_COST
            else:
                cost_comp = CostComparability.COMPARABLE

            # Validity & Expiry (derived dynamically; never mutates version)
            valid_until = version.valid_until
            is_expired = bool(valid_until and valid_until < now)

            # Technical Specification Compliance
            tech_compliance = evaluate_technical_compliance(
                rfq_obj,
                version,
                schema_attributes=schema_attributes,
            )

            # Operator Provenance Projection
            opp_id = offer.source_opportunity_id if is_operator else None
            opp_ident = (
                offer.source_opportunity.identifier
                if is_operator and offer.source_opportunity
                else None
            )
            entered_by_op = is_ext if is_operator else None

            comparison_rows.append(
                ComparisonRow(
                    offer_id=offer.id,
                    offer_version_id=version.id,
                    version_number=version.version_number,
                    safe_offeror_identity=safe_name,
                    offeror_name=safe_name,
                    is_external=is_ext,
                    offeror_role=offer.offeror_role,
                    offered_quantity=offered_qty,
                    quantity_unit=version.quantity_unit,
                    quantity_coverage=coverage,
                    surplus_quantity=surplus,
                    unit_price=Decimal(str(version.unit_price)),
                    currency=version_currency,
                    product_cost=normalized.product_cost,
                    known_cost_total=normalized.known_cost_total,
                    landed_cost=normalized.landed_cost,
                    landed_unit_cost=normalized.landed_unit_cost,
                    normalization_complete=normalized.normalization_complete,
                    missing_components=normalized.missing_components,
                    cost_comparability=cost_comp,
                    payment_terms=version.payment_terms or "",
                    delivery_terms=version.delivery_terms or "",
                    incoterm=version.incoterm or "",
                    delivery_start=version.delivery_start,
                    delivery_end=version.delivery_end,
                    valid_until=valid_until,
                    is_expired=is_expired,
                    technical_compliance=tech_compliance,
                    trust_status=trust,
                    aggregate_version=offer.aggregate_version,
                    source_opportunity_id=opp_id,
                    source_opportunity_identifier=opp_ident,
                    entered_by_operator=entered_by_op,
                )
            )

        return RFQComparison(
            rfq_id=rfq_obj.id,
            rfq_quantity=rfq_qty,
            rfq_unit=rfq_obj.unit,
            rfq_currency=rfq_obj.currency,
            total_offers=len(comparison_rows),
            items=tuple(comparison_rows),
        )
