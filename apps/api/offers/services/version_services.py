from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from commodities.services import validate_commodity_payload
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferImmutableError,
    OfferNotFoundError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    OfferVersionNotFoundError,
    StaleVersionError,
)
from offers.models import Offer, OfferCostComponent, OfferVersion
from trade_hub.models import RFQStatus


def _validate_expected_version(offer: Offer, expected_version: Any) -> None:
    """
    Validates optimistic concurrency aggregate_version on Offer.
    Raises InvalidVersionError if malformed or non-positive.
    Raises StaleVersionError if expected_version != offer.aggregate_version.
    """
    if expected_version is None:
        return
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if offer.aggregate_version != expected_version:
        raise StaleVersionError(
            f"Stale version error: Offer aggregate_version is {offer.aggregate_version}, "
            f"expected {expected_version}."
        )


def _resolve_offer(offer_or_id: Any) -> Offer:
    if isinstance(offer_or_id, Offer):
        return offer_or_id
    if isinstance(offer_or_id, (str, uuid.UUID)):
        offer = Offer.objects.filter(pk=offer_or_id).first()
        if not offer:
            raise OfferNotFoundError(f"Offer '{offer_or_id}' does not exist.")
        return offer
    raise OfferValidationError(f"Invalid offer identifier: '{offer_or_id}'.")


def _resolve_offer_version(version_or_id: Any) -> OfferVersion:
    if isinstance(version_or_id, OfferVersion):
        return version_or_id
    if isinstance(version_or_id, (str, uuid.UUID)):
        version = OfferVersion.objects.filter(pk=version_or_id).first()
        if not version:
            raise OfferVersionNotFoundError(f"OfferVersion '{version_or_id}' does not exist.")
        return version
    raise OfferValidationError(f"Invalid offer version identifier: '{version_or_id}'.")


def create_draft_offer_version(
    *,
    actor: Any,
    offer: Offer | uuid.UUID | str,
    offered_quantity: Decimal | str,
    quantity_unit: str,
    unit_price: Decimal | str,
    currency: str = "USD",
    payment_terms: str = "",
    delivery_terms: str = "",
    incoterm: str = "",
    delivery_start: Optional[date] = None,
    delivery_end: Optional[date] = None,
    valid_until: Optional[datetime] = None,
    logistics_cost_status: str = LogisticsCostStatus.UNKNOWN,
    logistics_cost_amount: Optional[Decimal | str] = None,
    specifications: Optional[dict] = None,
    notes: str = "",
    expected_version: Optional[int] = None,
    cost_components: Optional[list[dict[str, Any]]] = None,
) -> OfferVersion:
    """
    Authoritative domain service to allocate and create an OfferVersion in DRAFT status.

    Critical Invariants:
    - Server allocates version_number sequentially inside transaction.atomic() with SELECT FOR UPDATE.
    - At most ONE unsubmitted DRAFT per Offer is allowed (enforced by DB UniqueConstraint & service check).
    - Client cannot set version_number, status, submitted_by, or submitted_at.
    - Dynamic specifications are strictly locked to Offer.rfq.schema_version (never active schema).
    - Specifications must pass validate_commodity_payload.
    - offered_quantity must be strictly positive (Decimal > 0); partial and surplus quantities are permitted.
    - quantity_unit must be compatible with RFQ unit.
    - unit_price must be strictly positive (Decimal > 0); exact submitted currency is preserved without FX.
    - logistics_cost_status: KNOWN_SEPARATE requires logistics_cost_amount; all others forbid it.
    - delivery_start <= delivery_end when both dates are present.
    - Optimistic concurrency: increments Offer.aggregate_version.
    - Draft creation never updates Offer.current_submitted_version.
    """
    if not actor or not getattr(actor, "is_authenticated", False):
        raise OfferPermissionDeniedError("Authentication is required to create an offer version.")

    offer_obj = _resolve_offer(offer)

    with transaction.atomic():
        # 1. Lock Offer aggregate for atomic version allocation and concurrency control
        try:
            locked_offer = (
                Offer.objects.select_for_update()
                .select_related("rfq", "rfq__schema_version")
                .get(pk=offer_obj.pk)
            )
        except Offer.DoesNotExist as exc:
            raise OfferNotFoundError(f"Offer '{offer_obj.pk}' does not exist.") from exc

        # 2. Concurrency verification
        _validate_expected_version(locked_offer, expected_version)

        # 3. Check RFQ status & deadline
        rfq = locked_offer.rfq
        if rfq.status not in [RFQStatus.PUBLISHED, RFQStatus.COLLECTING_OFFERS]:
            raise OfferStateError(
                f"Target RFQ is in status '{rfq.status}'. Offers can only be added to "
                f"Published or Collecting Offers RFQs."
            )
        if rfq.submission_deadline and timezone.now() > rfq.submission_deadline:
            raise OfferValidationError("RFQ offer submission deadline has passed.")

        # 4. Check for existing active draft (DB constraint is final guard)
        existing_draft = OfferVersion.objects.filter(
            offer=locked_offer,
            status=OfferVersionStatus.DRAFT,
        ).first()
        if existing_draft:
            raise OfferConflictError(
                f"Offer '{locked_offer.id}' already has an active draft "
                f"(version {existing_draft.version_number})."
            )

        # 5. Type and Domain Validations
        # Quantity
        try:
            q_val = Decimal(str(offered_quantity))
        except Exception as exc:
            raise OfferValidationError(f"Invalid offered_quantity: '{offered_quantity}'.") from exc
        if q_val <= Decimal("0"):
            raise OfferValidationError("Offered quantity must be positive.")

        # Unit compatibility
        if not quantity_unit:
            raise OfferValidationError("quantity_unit is required.")
        rfq_unit = (rfq.unit or "").strip().upper()
        offer_unit = quantity_unit.strip().upper()
        if rfq_unit and offer_unit != rfq_unit:
            raise OfferValidationError(
                f"Offer quantity unit '{quantity_unit}' is incompatible with RFQ unit '{rfq.unit}'."
            )

        # Price & Currency
        try:
            p_val = Decimal(str(unit_price))
        except Exception as exc:
            raise OfferValidationError(f"Invalid unit_price: '{unit_price}'.") from exc
        if p_val <= Decimal("0"):
            raise OfferValidationError("Unit price must be positive.")

        clean_currency = (currency or "USD").strip().upper()
        if len(clean_currency) != 3:
            raise OfferValidationError("currency must be a valid 3-letter ISO code.")

        # Delivery dates
        if delivery_start and delivery_end and delivery_start > delivery_end:
            raise OfferValidationError("delivery_start cannot be after delivery_end.")

        # Logistics cost validation
        clean_logistics_status = (logistics_cost_status or LogisticsCostStatus.UNKNOWN).strip()
        if clean_logistics_status not in LogisticsCostStatus.values:
            raise OfferValidationError(f"Invalid logistics_cost_status: '{logistics_cost_status}'.")

        clean_logistics_amount: Optional[Decimal] = None
        if clean_logistics_status == LogisticsCostStatus.KNOWN_SEPARATE:
            if logistics_cost_amount is None:
                raise OfferValidationError(
                    "logistics_cost_amount is required when logistics_cost_status is KNOWN_SEPARATE."
                )
            try:
                clean_logistics_amount = Decimal(str(logistics_cost_amount))
            except Exception as exc:
                raise OfferValidationError(
                    f"Invalid logistics_cost_amount: '{logistics_cost_amount}'."
                ) from exc
            if clean_logistics_amount < Decimal("0"):
                raise OfferValidationError("logistics_cost_amount cannot be negative.")
        else:
            if logistics_cost_amount is not None:
                raise OfferValidationError(
                    f"logistics_cost_amount must be absent when logistics_cost_status is {clean_logistics_status}."
                )

        # 6. Dynamic Specifications Validation (RFQ Schema Lock)
        specs_payload = specifications or {}
        rfq_schema = rfq.schema_version
        try:
            validate_commodity_payload(rfq_schema, specs_payload)
        except ValidationError as exc:
            raise OfferValidationError(
                f"Dynamic specifications failed schema validation: {exc}"
            ) from exc

        # 7. Sequential Version Number Allocation
        max_v = (
            OfferVersion.objects.filter(offer=locked_offer).aggregate(
                models.Max("version_number")
            )["version_number__max"]
            or 0
        )
        allocated_version_number = max_v + 1

        # 8. Create OfferVersion
        try:
            version = OfferVersion.objects.create(
                offer=locked_offer,
                version_number=allocated_version_number,
                status=OfferVersionStatus.DRAFT,
                schema_version=rfq_schema,
                specifications=specs_payload,
                offered_quantity=q_val,
                quantity_unit=quantity_unit.strip(),
                unit_price=p_val,
                currency=clean_currency,
                payment_terms=payment_terms or "",
                delivery_terms=delivery_terms or "",
                incoterm=incoterm or "",
                delivery_start=delivery_start,
                delivery_end=delivery_end,
                valid_until=valid_until,
                logistics_cost_status=clean_logistics_status,
                logistics_cost_amount=clean_logistics_amount,
                notes=notes or "",
                created_by=actor,
            )
        except IntegrityError as exc:
            # Handle concurrent draft creation or version number conflict race
            raise OfferConflictError(
                f"Concurrent creation conflict on Offer '{locked_offer.id}': {exc}"
            ) from exc

        # 9. Optional Cost Components Creation
        if cost_components:
            for item in cost_components:
                kind = item.get("kind")
                if kind not in CostComponentKind.values:
                    raise OfferValidationError(f"Invalid cost component kind '{kind}'.")
                amount = item.get("amount")
                try:
                    c_amount = Decimal(str(amount))
                except Exception as exc:
                    raise OfferValidationError(
                        f"Invalid cost component amount: '{amount}'."
                    ) from exc
                if c_amount <= Decimal("0"):
                    raise OfferValidationError("Cost component amount must be positive.")
                c_curr = (item.get("currency") or clean_currency).strip().upper()
                if c_curr != clean_currency:
                    raise OfferValidationError(
                        f"Cost component currency '{c_curr}' must match OfferVersion currency '{clean_currency}'."
                    )
                OfferCostComponent.objects.create(
                    offer_version=version,
                    kind=kind,
                    amount=c_amount,
                    currency=clean_currency,
                    description=item.get("description", ""),
                )

        # 10. Mutate Offer aggregate state
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

    return version


def update_draft_offer_version(
    *,
    actor: Any,
    offer_version: OfferVersion | uuid.UUID | str,
    expected_version: Optional[int] = None,
    offered_quantity: Optional[Decimal | str] = None,
    quantity_unit: Optional[str] = None,
    unit_price: Optional[Decimal | str] = None,
    currency: Optional[str] = None,
    payment_terms: Optional[str] = None,
    delivery_terms: Optional[str] = None,
    incoterm: Optional[str] = None,
    delivery_start: Optional[date] = None,
    delivery_end: Optional[date] = None,
    valid_until: Optional[datetime] = None,
    logistics_cost_status: Optional[str] = None,
    logistics_cost_amount: Optional[Decimal | str] = None,
    specifications: Optional[dict] = None,
    notes: Optional[str] = None,
    cost_components: Optional[list[dict[str, Any]]] = None,
) -> OfferVersion:
    """
    Focused mutation service for OfferVersion in DRAFT status only.

    Critical Invariants:
    - Only DRAFT versions can be edited; SUBMITTED versions reject mutation.
    - Server-owned fields (version_number, offer, schema_version, status, submitted_by, submitted_at,
      created_by, created_at) cannot be mutated.
    - Dynamic specifications are re-validated against RFQ schema_version.
    - offered_quantity and unit_price must remain positive Decimals.
    - quantity_unit must remain compatible with RFQ unit.
    - Increments Offer.aggregate_version upon successful update.
    """
    if not actor or not getattr(actor, "is_authenticated", False):
        raise OfferPermissionDeniedError("Authentication is required to edit an offer version.")

    version_obj = _resolve_offer_version(offer_version)

    with transaction.atomic():
        # Lock OfferVersion and parent Offer
        try:
            locked_version = (
                OfferVersion.objects.select_for_update()
                .select_related("offer", "offer__rfq", "offer__rfq__schema_version", "schema_version")
                .get(pk=version_obj.pk)
            )
        except OfferVersion.DoesNotExist as exc:
            raise OfferVersionNotFoundError(
                f"OfferVersion '{version_obj.pk}' does not exist."
            ) from exc

        locked_offer = (
            Offer.objects.select_for_update()
            .get(pk=locked_version.offer_id)
        )

        # Immutability guard: only DRAFT versions are editable
        if locked_version.status != OfferVersionStatus.DRAFT:
            raise OfferImmutableError(
                f"OfferVersion {locked_version.version_number} is in status '{locked_version.status}' "
                f"and cannot be edited (only DRAFT versions can be edited)."
            )

        # Concurrency verification
        _validate_expected_version(locked_offer, expected_version)

        rfq = locked_offer.rfq
        if rfq.status not in [RFQStatus.PUBLISHED, RFQStatus.COLLECTING_OFFERS]:
            raise OfferStateError(
                f"Target RFQ is in status '{rfq.status}'. Offers cannot be edited."
            )

        # Apply Quantity
        if offered_quantity is not None:
            try:
                q_val = Decimal(str(offered_quantity))
            except Exception as exc:
                raise OfferValidationError(
                    f"Invalid offered_quantity: '{offered_quantity}'."
                ) from exc
            if q_val <= Decimal("0"):
                raise OfferValidationError("Offered quantity must be positive.")
            locked_version.offered_quantity = q_val

        # Apply Unit
        if quantity_unit is not None:
            rfq_unit = (rfq.unit or "").strip().upper()
            offer_unit = quantity_unit.strip().upper()
            if rfq_unit and offer_unit != rfq_unit:
                raise OfferValidationError(
                    f"Offer quantity unit '{quantity_unit}' is incompatible with RFQ unit '{rfq.unit}'."
                )
            locked_version.quantity_unit = quantity_unit.strip()

        # Apply Price
        if unit_price is not None:
            try:
                p_val = Decimal(str(unit_price))
            except Exception as exc:
                raise OfferValidationError(f"Invalid unit_price: '{unit_price}'.") from exc
            if p_val <= Decimal("0"):
                raise OfferValidationError("Unit price must be positive.")
            locked_version.unit_price = p_val

        # Apply Currency
        if currency is not None:
            clean_curr = currency.strip().upper()
            if len(clean_curr) != 3:
                raise OfferValidationError("currency must be a valid 3-letter ISO code.")
            locked_version.currency = clean_curr

        # Commercial terms
        if payment_terms is not None:
            locked_version.payment_terms = payment_terms
        if delivery_terms is not None:
            locked_version.delivery_terms = delivery_terms
        if incoterm is not None:
            locked_version.incoterm = incoterm
        if delivery_start is not None:
            locked_version.delivery_start = delivery_start
        if delivery_end is not None:
            locked_version.delivery_end = delivery_end
        if valid_until is not None:
            locked_version.valid_until = valid_until
        if notes is not None:
            locked_version.notes = notes

        # Delivery window check
        if (
            locked_version.delivery_start
            and locked_version.delivery_end
            and locked_version.delivery_start > locked_version.delivery_end
        ):
            raise OfferValidationError("delivery_start cannot be after delivery_end.")

        # Logistics
        if logistics_cost_status is not None:
            clean_logistics_status = logistics_cost_status.strip()
            if clean_logistics_status not in LogisticsCostStatus.values:
                raise OfferValidationError(
                    f"Invalid logistics_cost_status: '{logistics_cost_status}'."
                )
            locked_version.logistics_cost_status = clean_logistics_status

        if logistics_cost_amount is not None:
            try:
                locked_version.logistics_cost_amount = Decimal(str(logistics_cost_amount))
            except Exception as exc:
                raise OfferValidationError(
                    f"Invalid logistics_cost_amount: '{logistics_cost_amount}'."
                ) from exc
            if locked_version.logistics_cost_amount < Decimal("0"):
                raise OfferValidationError("logistics_cost_amount cannot be negative.")
        elif (
            logistics_cost_status is not None
            and locked_version.logistics_cost_status != LogisticsCostStatus.KNOWN_SEPARATE
        ):
            locked_version.logistics_cost_amount = None

        # Re-check logistics consistency
        if locked_version.logistics_cost_status == LogisticsCostStatus.KNOWN_SEPARATE:
            if locked_version.logistics_cost_amount is None:
                raise OfferValidationError(
                    "logistics_cost_amount is required when logistics_cost_status is KNOWN_SEPARATE."
                )
        else:
            if locked_version.logistics_cost_amount is not None:
                raise OfferValidationError(
                    f"logistics_cost_amount must be absent when logistics_cost_status is "
                    f"{locked_version.logistics_cost_status}."
                )

        # Specifications
        if specifications is not None:
            try:
                validate_commodity_payload(locked_version.schema_version, specifications)
            except ValidationError as exc:
                raise OfferValidationError(
                    f"Dynamic specifications failed schema validation: {exc}"
                ) from exc
            locked_version.specifications = specifications

        locked_version.save()

        # Update cost components if provided
        if cost_components is not None:
            locked_version.cost_components.all().delete()
            for item in cost_components:
                kind = item.get("kind")
                if kind not in CostComponentKind.values:
                    raise OfferValidationError(f"Invalid cost component kind '{kind}'.")
                amount = item.get("amount")
                try:
                    c_amount = Decimal(str(amount))
                except Exception as exc:
                    raise OfferValidationError(
                        f"Invalid cost component amount: '{amount}'."
                    ) from exc
                if c_amount <= Decimal("0"):
                    raise OfferValidationError("Cost component amount must be positive.")
                c_curr = (item.get("currency") or locked_version.currency).strip().upper()
                if c_curr != locked_version.currency:
                    raise OfferValidationError(
                        f"Cost component currency '{c_curr}' must match OfferVersion currency '{locked_version.currency}'."
                    )
                OfferCostComponent.objects.create(
                    offer_version=locked_version,
                    kind=kind,
                    amount=c_amount,
                    currency=locked_version.currency,
                    description=item.get("description", ""),
                )

        # Mutate Offer aggregate version
        locked_offer.aggregate_version += 1
        locked_offer.save(update_fields=["aggregate_version", "updated_at"])

    return locked_version


def submit_offer_version(
    *,
    actor: Any,
    offer_version: OfferVersion | uuid.UUID | str,
    expected_version: Optional[int] = None,
    require_expected_version: bool = False,
) -> OfferVersion:
    """
    Authoritative domain service to submit an internal Supplier or Broker OfferVersion (T0803).
    Delegates to submit_internal_offer_version in offers.services.submission.
    """
    from offers.services.submission import submit_internal_offer_version

    return submit_internal_offer_version(
        actor=actor,
        offer_version=offer_version,
        expected_version=expected_version,
        require_expected_version=require_expected_version,
    )

