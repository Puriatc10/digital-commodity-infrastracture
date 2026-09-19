from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional
import uuid

from offers.enums import CostComponentKind, LogisticsCostStatus
from offers.exceptions import OfferNormalizationError, OfferVersionNotFoundError
from offers.models import OfferVersion

DEFAULT_NORMALIZATION_POLICY_VERSION: str = "v1"
SUPPORTED_POLICY_VERSIONS: frozenset[str] = frozenset({DEFAULT_NORMALIZATION_POLICY_VERSION})

# Standard repository monetary precision (2 decimal places)
CURRENCY_QUANTIZATION: Decimal = Decimal("0.01")


@dataclass(frozen=True)
class NormalizedOfferVersion:
    """
    Structured immutable normalisation result for one exact OfferVersion commercial snapshot.
    (Epic 8 Contract §28-§34, T0805).

    Invariants:
    - Pure Decimal arithmetic end-to-end.
    - Preserves exact OfferVersion currency; never applies FX.
    - Strictly distinguishes UNKNOWN logistics from KNOWN ZERO extra logistics.
    - If required logistics is UNKNOWN, landed_cost and landed_unit_cost are strictly None.
    - Exposes machine-readable missing components and deterministic policy version.
    """

    product_cost: Decimal
    known_cost_total: Decimal
    landed_cost: Optional[Decimal]
    landed_unit_cost: Optional[Decimal]
    normalization_complete: bool
    missing_components: tuple[str, ...]
    currency: str
    policy_version: str

    def __post_init__(self):
        # Enforce tuple for immutable missing_components
        if not isinstance(self.missing_components, tuple):
            object.__setattr__(self, "missing_components", tuple(self.missing_components))

        # Disallow binary floats
        for field_name in ("product_cost", "known_cost_total", "landed_cost", "landed_unit_cost"):
            val = getattr(self, field_name)
            if isinstance(val, float):
                raise OfferNormalizationError(
                    f"Binary float is forbidden for monetary field '{field_name}' in NormalizedOfferVersion."
                )

        # Invariant: landed_unit_cost can only exist when landed_cost exists
        if self.landed_cost is None and self.landed_unit_cost is not None:
            raise OfferNormalizationError("landed_unit_cost cannot exist without landed_cost.")

        # Invariant: normalization_complete implies landed_cost exists and no missing components
        if self.normalization_complete:
            if self.landed_cost is None:
                raise OfferNormalizationError("Complete normalisation must have landed_cost.")
            if len(self.missing_components) > 0:
                raise OfferNormalizationError("Complete normalisation cannot have missing components.")
        else:
            if self.landed_cost is not None:
                raise OfferNormalizationError("Incomplete normalisation cannot have landed_cost.")
            if len(self.missing_components) == 0:
                raise OfferNormalizationError("Incomplete normalisation must list missing components.")

    def to_dict(self) -> dict[str, Any]:
        """Return a structured dictionary suitable for serialization or API responses."""
        return {
            "product_cost": str(self.product_cost),
            "known_cost_total": str(self.known_cost_total),
            "landed_cost": str(self.landed_cost) if self.landed_cost is not None else None,
            "landed_unit_cost": str(self.landed_unit_cost) if self.landed_unit_cost is not None else None,
            "normalization_complete": self.normalization_complete,
            "missing_components": list(self.missing_components),
            "currency": self.currency,
            "policy_version": self.policy_version,
        }


def _resolve_offer_version(version_or_id: Any) -> OfferVersion:
    if isinstance(version_or_id, OfferVersion):
        return version_or_id
    if isinstance(version_or_id, (str, uuid.UUID)):
        version = (
            OfferVersion.objects.filter(pk=version_or_id)
            .select_related("offer", "offer__rfq")
            .prefetch_related("cost_components")
            .first()
        )
        if not version:
            raise OfferVersionNotFoundError(f"OfferVersion '{version_or_id}' does not exist.")
        return version
    raise OfferNormalizationError(f"Invalid offer version input: '{version_or_id}'.")


def _to_decimal(val: Any, field_name: str) -> Decimal:
    if isinstance(val, float):
        raise OfferNormalizationError(
            f"Binary float is strictly forbidden for '{field_name}'. Must use Decimal."
        )
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception as exc:
        raise OfferNormalizationError(f"Invalid Decimal value for '{field_name}': '{val}'.") from exc


def normalize_offer_version(
    offer_version: OfferVersion | uuid.UUID | str,
    *,
    policy_version: str = DEFAULT_NORMALIZATION_POLICY_VERSION,
    cost_components: Optional[Iterable[Any]] = None,
) -> NormalizedOfferVersion:
    """
    Pure and deterministic domain normalisation engine for one exact OfferVersion (T0805).

    Calculates:
    - product_cost = unit_price * offered_quantity (using offered_quantity, never RFQ quantity; surplus uncapped)
    - known_cost_total = product_cost + known separate logistics + known OTHER components
    - landed_cost = product_cost + logistics_addition + other_known_costs (None if logistics is UNKNOWN)
    - landed_unit_cost = landed_cost / offered_quantity (None if landed_cost is None)
    - normalization_complete = True if required logistics evidence is known, False otherwise
    - missing_components = ("LOGISTICS",) if UNKNOWN, () otherwise
    - currency = exact OfferVersion currency (never converted)
    - policy_version = explicit semantic policy version

    Invariants:
    - Pure computation; never mutates OfferVersion.
    - No persistence table; derived on demand.
    - Deterministic: no system time, no external HTTP, no FX, no market data, no randomness.
    - Strictly enforces UNKNOWN != KNOWN ZERO.
    - External counterparty offers (T0804) use the exact same calculation path.
    - Zero commodity-specific branches or attribute key dependencies.
    """
    # 1. Policy Version Validation
    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        raise OfferNormalizationError(
            f"Unsupported normalisation policy version '{policy_version}'. "
            f"Supported versions: {sorted(SUPPORTED_POLICY_VERSIONS)}"
        )

    # 2. OfferVersion Snapshot Resolution
    version = _resolve_offer_version(offer_version)

    # 3. Commercial Field Validations
    if version.offered_quantity is None:
        raise OfferNormalizationError("OfferVersion offered_quantity is missing.")
    offered_qty = _to_decimal(version.offered_quantity, "offered_quantity")
    if offered_qty <= Decimal("0"):
        raise OfferNormalizationError(f"offered_quantity must be strictly positive, got {offered_qty}.")

    if version.unit_price is None:
        raise OfferNormalizationError("OfferVersion unit_price is missing.")
    unit_price = _to_decimal(version.unit_price, "unit_price")
    if unit_price <= Decimal("0"):
        raise OfferNormalizationError(f"unit_price must be strictly positive, got {unit_price}.")

    currency = (version.currency or "").strip().upper()
    if len(currency) != 3:
        raise OfferNormalizationError(f"Invalid currency code '{version.currency}'. Must be 3-letter ISO code.")

    logistics_status = (version.logistics_cost_status or "").strip()
    if logistics_status not in LogisticsCostStatus.values:
        raise OfferNormalizationError(f"Invalid logistics_cost_status: '{version.logistics_cost_status}'.")

    # 4. Logistics Consistency Checks on OfferVersion
    version_logistics_amount: Optional[Decimal] = None
    if logistics_status == LogisticsCostStatus.KNOWN_SEPARATE:
        if version.logistics_cost_amount is None:
            raise OfferNormalizationError(
                "logistics_cost_amount is required on OfferVersion when logistics_cost_status is KNOWN_SEPARATE."
            )
        version_logistics_amount = _to_decimal(version.logistics_cost_amount, "logistics_cost_amount")
        if version_logistics_amount < Decimal("0"):
            raise OfferNormalizationError("logistics_cost_amount cannot be negative.")
    else:
        if version.logistics_cost_amount is not None:
            raise OfferNormalizationError(
                f"logistics_cost_amount must be absent when logistics_cost_status is {logistics_status}."
            )

    # 5. Cost Components Resolution and Validation
    if cost_components is not None:
        component_list = list(cost_components)
    elif version.pk is not None and hasattr(version, "cost_components"):
        component_list = list(version.cost_components.all())
    else:
        component_list = []

    other_costs_sum = Decimal("0.00")
    additional_logistics_sum = Decimal("0.00")

    for comp in component_list:
        # Extract kind
        c_kind = getattr(comp, "kind", None) if hasattr(comp, "kind") else comp.get("kind")
        if c_kind not in CostComponentKind.values:
            raise OfferNormalizationError(f"Unsupported cost component kind '{c_kind}'.")

        # Extract amount
        c_amt_raw = getattr(comp, "amount", None) if hasattr(comp, "amount") else comp.get("amount")
        if c_amt_raw is None:
            raise OfferNormalizationError(f"Cost component of kind '{c_kind}' is missing amount.")
        c_amt = _to_decimal(c_amt_raw, f"cost_component[{c_kind}].amount")
        if c_amt <= Decimal("0"):
            raise OfferNormalizationError(f"Cost component amount must be positive, got {c_amt}.")

        # Extract & validate currency (must strictly match OfferVersion currency; no FX)
        c_curr = getattr(comp, "currency", None) if hasattr(comp, "currency") else comp.get("currency")
        c_curr_clean = (c_curr or "").strip().upper()
        if c_curr_clean != currency:
            raise OfferNormalizationError(
                f"Cost component currency '{c_curr_clean}' does not match OfferVersion currency '{currency}'."
            )

        # Classify by kind
        if c_kind == CostComponentKind.OTHER:
            other_costs_sum += c_amt
        elif c_kind == CostComponentKind.LOGISTICS:
            if logistics_status != LogisticsCostStatus.KNOWN_SEPARATE:
                raise OfferNormalizationError(
                    f"Child LOGISTICS cost components cannot be specified when logistics_cost_status is {logistics_status}."
                )
            additional_logistics_sum += c_amt

    # 6. Exact Product Cost Arithmetic (unit_price * offered_quantity)
    # Strict Decimal multiplication, uncapped, quantized to standard currency precision.
    product_cost = (unit_price * offered_qty).quantize(CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP)
    other_costs_total = other_costs_sum.quantize(CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP)

    # 7. Logistics and Landed Cost Semantics
    if logistics_status == LogisticsCostStatus.KNOWN_SEPARATE:
        assert version_logistics_amount is not None
        known_logistics_total = (version_logistics_amount + additional_logistics_sum).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        known_cost_total = (product_cost + known_logistics_total + other_costs_total).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        landed_cost: Optional[Decimal] = known_cost_total
        landed_unit_cost: Optional[Decimal] = (landed_cost / offered_qty).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        normalization_complete = True
        missing_components: tuple[str, ...] = ()

    elif logistics_status in (LogisticsCostStatus.INCLUDED_IN_PRICE, LogisticsCostStatus.NOT_APPLICABLE):
        # Known zero extra cost for logistics
        known_cost_total = (product_cost + other_costs_total).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        landed_cost = known_cost_total
        landed_unit_cost = (landed_cost / offered_qty).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        normalization_complete = True
        missing_components = ()

    elif logistics_status == LogisticsCostStatus.UNKNOWN:
        # UNKNOWN is never zero. No numeric logistics value is substituted.
        # Known cost total captures product cost and other known costs.
        # Landed cost and landed unit cost cannot be computed.
        known_cost_total = (product_cost + other_costs_total).quantize(
            CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP
        )
        landed_cost = None
        landed_unit_cost = None
        normalization_complete = False
        missing_components = ("LOGISTICS",)

    else:
        raise OfferNormalizationError(f"Unhandled logistics_cost_status: '{logistics_status}'.")

    return NormalizedOfferVersion(
        product_cost=product_cost,
        known_cost_total=known_cost_total,
        landed_cost=landed_cost,
        landed_unit_cost=landed_unit_cost,
        normalization_complete=normalization_complete,
        missing_components=missing_components,
        currency=currency,
        policy_version=policy_version,
    )
