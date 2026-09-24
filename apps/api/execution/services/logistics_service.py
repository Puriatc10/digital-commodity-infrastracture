from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Union
from uuid import UUID

from django.db import transaction

from execution.enums import ExecutionStatus, TransportMode
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionNotFoundError,
    ExecutionValidationError,
    StaleVersionError,
)
from execution.models.execution import Execution
from execution.models.logistics import ExecutionLogistics
from execution.permissions import (
    check_execution_read_access,
    check_logistics_mutation_authority,
)
from geography.models import GeographicArea


def _validate_expected_version(current: int, expected: Any) -> None:
    """Validate optimistic concurrency expected_version."""
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ExecutionValidationError("expected_version must be a positive integer.")
    if current != expected:
        raise StaleVersionError(
            f"Optimistic concurrency conflict: expected_version={expected}, current version={current}."
        )


@transaction.atomic
def get_or_create_execution_logistics(
    execution_id: Union[UUID, str],
    *,
    actor: Any = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Idempotently retrieve or initialize the ExecutionLogistics record for an Execution.

    Invariants (Epic 10 Contract §5, §35, T1004):
    - Exactly 1 ExecutionLogistics per Execution.
    - Idempotent: repeated calls return existing instance.
    - Initialized with unknown operational facts as null/empty (preserves unknown semantics).
    - Checks read authorization if actor is provided.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if actor is not None:
        check_execution_read_access(actor, execution)

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )
    return logistics


@transaction.atomic
def schedule_loading(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    scheduled_loading_at: datetime,
    pickup_area_id: Optional[Union[UUID, str]] = None,
    destination_area_id: Optional[Union[UUID, str]] = None,
    pickup_location: Optional[str] = None,
    destination_location: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Seller/Operator operational action: schedule loading date and location context.

    Invariants:
    - Restricted to Seller organization non-viewers and Operator/Admin.
    - Concurrency protected via select_for_update and expected_version.
    - Execution must be OPEN.
    """
    if scheduled_loading_at is None:
        raise ExecutionValidationError("scheduled_loading_at is mandatory to schedule loading.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "SCHEDULE_LOADING")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    # Validate geographic areas if specified
    if pickup_area_id is not None:
        if not GeographicArea.objects.filter(pk=pickup_area_id).exists():
            raise ExecutionValidationError(f"Pickup geographic area '{pickup_area_id}' does not exist.")
        logistics.pickup_area_id = pickup_area_id

    if destination_area_id is not None:
        if not GeographicArea.objects.filter(pk=destination_area_id).exists():
            raise ExecutionValidationError(f"Destination geographic area '{destination_area_id}' does not exist.")
        logistics.destination_area_id = destination_area_id

    if pickup_location is not None:
        logistics.pickup_location = pickup_location.strip()
    if destination_location is not None:
        logistics.destination_location = destination_location.strip()

    logistics.scheduled_loading_at = scheduled_loading_at
    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def record_loading(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    actual_loading_at: datetime,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Seller/Operator operational action: record actual loading occurrence.

    Invariants:
    - Restricted to Seller organization non-viewers and Operator/Admin.
    - Chronology validated: actual_delivery_at cannot precede actual_loading_at.
    """
    if actual_loading_at is None:
        raise ExecutionValidationError("actual_loading_at is mandatory to record loading.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "RECORD_LOADING")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    if logistics.actual_delivery_at and actual_loading_at > logistics.actual_delivery_at:
        raise ExecutionValidationError("Actual loading timestamp cannot be later than actual delivery timestamp.")

    logistics.actual_loading_at = actual_loading_at
    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def update_transport(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    carrier_name: Optional[str] = None,
    transport_mode: Optional[str] = None,
    transport_reference: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Seller/Operator operational action: update freight carrier, mode, and transport reference.

    Invariants:
    - transport_mode must be one of canonical TransportMode choices. Never inferred.
    - Restricted to Seller and Operator.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "UPDATE_TRANSPORT")

    if transport_mode is not None and transport_mode != "":
        if transport_mode not in TransportMode.values:
            raise ExecutionValidationError(
                f"Invalid transport mode '{transport_mode}'. Allowed: {TransportMode.values}."
            )

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    if carrier_name is not None:
        logistics.carrier_name = carrier_name.strip()
    if transport_mode is not None:
        logistics.transport_mode = transport_mode if transport_mode != "" else None
    if transport_reference is not None:
        logistics.transport_reference = transport_reference.strip()

    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def update_eta(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    eta: datetime,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Seller/Operator operational action: update estimated time of arrival (ETA).

    Invariants:
    - Restricted to Seller and Operator.
    - Stale caller cannot overwrite actual delivery.
    - If shipment already delivered, updating ETA is rejected.
    """
    if eta is None:
        raise ExecutionValidationError("eta timestamp is mandatory to update ETA.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "UPDATE_ETA")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    if logistics.actual_delivery_at is not None:
        raise ExecutionValidationError("Cannot update ETA: actual delivery has already been recorded.")

    logistics.eta = eta
    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def record_delivery(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    actual_delivery_at: datetime,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Buyer/Operator operational action: record actual goods delivery receipt.

    Invariants:
    - Restricted to Buyer organization non-viewers and Operator/Admin.
    - Chronology validated: actual_delivery_at >= actual_loading_at.
    - Recording delivery does NOT imply milestone ACCEPTED.
    """
    if actual_delivery_at is None:
        raise ExecutionValidationError("actual_delivery_at is mandatory to record delivery.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "RECORD_DELIVERY")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    if logistics.actual_loading_at and actual_delivery_at < logistics.actual_loading_at:
        raise ExecutionValidationError("Actual delivery timestamp cannot precede actual loading timestamp.")

    logistics.actual_delivery_at = actual_delivery_at
    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def update_logistics_cost(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    logistics_cost: Decimal,
    currency: str,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Seller/Operator operational action: report actual or revised logistics cost.

    Invariants:
    - logistics_cost is strictly Decimal; float is forbidden.
    - currency is mandatory (ISO-4217, 3 characters).
    - No FX conversion.
    - Never mutates Deal commercial cost snapshot.
    """
    if logistics_cost is None:
        raise ExecutionValidationError("logistics_cost is mandatory.")
    if not isinstance(logistics_cost, Decimal):
        try:
            logistics_cost = Decimal(str(logistics_cost))
        except Exception:
            raise ExecutionValidationError("logistics_cost must be a valid Decimal amount.")

    if logistics_cost < 0:
        raise ExecutionValidationError("logistics_cost must be non-negative.")

    if not currency or len(currency.strip()) != 3:
        raise ExecutionValidationError("Explicit ISO-4217 3-letter currency code is mandatory.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    check_logistics_mutation_authority(actor, execution, "UPDATE_COST")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    logistics.logistics_cost = logistics_cost
    logistics.currency = currency.strip().upper()
    logistics.version += 1
    logistics.save()

    return logistics


@transaction.atomic
def mutate_logistics(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    data: Dict[str, Any],
    actor: Any,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionLogistics:
    """
    Tightly constrained operational logistics mutation (for PATCH /api/execution/{id}/logistics/).

    Invariants:
    - Mass-assignment forbidden: server-owned fields (id, execution, version, created_at, updated_at) are rejected.
    - Field-by-field side authority validation:
      - Seller fields: carrier_name, carrier, transport_mode, pickup_area_id, destination_area_id,
        pickup_location, destination_location, scheduled_loading_at, actual_loading_at, eta,
        transport_reference, logistics_cost, currency.
      - Buyer fields: actual_delivery_at.
    - Optimistic concurrency: expected_version checked and incremented under row lock.
    """
    FORBIDDEN_FIELDS = {"id", "execution", "execution_id", "version", "created_at", "updated_at"}
    attempted_forbidden = set(data.keys()) & FORBIDDEN_FIELDS
    if attempted_forbidden:
        raise ExecutionValidationError(f"Cannot mutate server-owned fields: {sorted(attempted_forbidden)}.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate logistics on an execution that is already CLOSED.")

    logistics, _ = ExecutionLogistics.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    _validate_expected_version(logistics.version, expected_version)

    SELLER_FIELDS = {
        "carrier_name",
        "carrier",
        "transport_mode",
        "pickup_area_id",
        "destination_area_id",
        "pickup_location",
        "destination_location",
        "scheduled_loading_at",
        "actual_loading_at",
        "eta",
        "transport_reference",
        "logistics_cost",
        "currency",
    }
    BUYER_FIELDS = {
        "actual_delivery_at",
    }

    has_seller_updates = bool(set(data.keys()) & SELLER_FIELDS)
    has_buyer_updates = bool(set(data.keys()) & BUYER_FIELDS)

    if has_seller_updates:
        check_logistics_mutation_authority(actor, execution, "SCHEDULE_LOADING")
    if has_buyer_updates:
        check_logistics_mutation_authority(actor, execution, "RECORD_DELIVERY")

    # Apply updates
    if "carrier_name" in data or "carrier" in data:
        val = data.get("carrier_name") if "carrier_name" in data else data.get("carrier")
        logistics.carrier_name = (val or "").strip()

    if "transport_mode" in data:
        tm = data["transport_mode"]
        if tm and tm not in TransportMode.values:
            raise ExecutionValidationError(f"Invalid transport mode '{tm}'. Allowed: {TransportMode.values}.")
        logistics.transport_mode = tm or None

    if "pickup_area_id" in data:
        pa_id = data["pickup_area_id"]
        if pa_id is not None:
            if not GeographicArea.objects.filter(pk=pa_id).exists():
                raise ExecutionValidationError(f"Pickup geographic area '{pa_id}' does not exist.")
        logistics.pickup_area_id = pa_id

    if "destination_area_id" in data:
        da_id = data["destination_area_id"]
        if da_id is not None:
            if not GeographicArea.objects.filter(pk=da_id).exists():
                raise ExecutionValidationError(f"Destination geographic area '{da_id}' does not exist.")
        logistics.destination_area_id = da_id

    if "pickup_location" in data:
        logistics.pickup_location = (data["pickup_location"] or "").strip()
    if "destination_location" in data:
        logistics.destination_location = (data["destination_location"] or "").strip()
    if "transport_reference" in data:
        logistics.transport_reference = (data["transport_reference"] or "").strip()

    if "scheduled_loading_at" in data:
        logistics.scheduled_loading_at = data["scheduled_loading_at"]
    if "actual_loading_at" in data:
        logistics.actual_loading_at = data["actual_loading_at"]
    if "eta" in data:
        if logistics.actual_delivery_at and data["eta"] is not None:
            raise ExecutionValidationError("Cannot update ETA: actual delivery has already been recorded.")
        logistics.eta = data["eta"]
    if "actual_delivery_at" in data:
        logistics.actual_delivery_at = data["actual_delivery_at"]

    if "logistics_cost" in data:
        cost = data["logistics_cost"]
        if cost is not None:
            if not isinstance(cost, Decimal):
                try:
                    cost = Decimal(str(cost))
                except Exception:
                    raise ExecutionValidationError("logistics_cost must be a valid Decimal amount.")
            if cost < 0:
                raise ExecutionValidationError("logistics_cost must be non-negative.")
        logistics.logistics_cost = cost

    if "currency" in data:
        curr = data["currency"]
        logistics.currency = (curr or "").strip().upper()

    logistics.version += 1
    logistics.clean()
    logistics.save()

    return logistics
