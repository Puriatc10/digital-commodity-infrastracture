from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from django.db import transaction

from deals.services.specifications import project_deal_specifications
from execution.enums import ExecutionStatus, InspectionResult, InspectionStatus
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionNotFoundError,
    ExecutionValidationError,
    InvalidInspectionTransitionError,
    StaleVersionError,
)
from execution.models.execution import Execution
from execution.models.inspection import ExecutionInspection
from execution.permissions import (
    check_execution_read_access,
    check_inspection_mutation_authority,
)


def _validate_expected_version(current: int, expected: Any) -> None:
    """Validate optimistic concurrency expected_version."""
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ExecutionValidationError("expected_version must be a positive integer.")
    if current != expected:
        raise StaleVersionError(
            f"Optimistic concurrency conflict: expected_version={expected}, current version={current}."
        )


@transaction.atomic
def get_or_create_execution_inspection(
    execution_id: Union[UUID, str],
    *,
    actor: Any = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionInspection:
    """
    Idempotently retrieve or initialize the ExecutionInspection record for an Execution.

    Invariants (Epic 10 Contract §43, §46, T1005):
    - Exactly 1 ExecutionInspection per Execution.
    - Idempotent: repeated calls return existing instance.
    - Required flag is derived solely from reliable persisted commercial context (RFQ.inspection_required).
      Never inferred from commodity type, active schema, or assumptions.
    - Preserves honest unknown semantics.
    - Checks read authorization if actor is provided.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal__rfq")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if actor is not None:
        check_execution_read_access(actor, execution)

    rfq = getattr(execution.deal, "rfq", None)
    is_required = bool(rfq and getattr(rfq, "inspection_required", False))
    init_status = InspectionStatus.PENDING if is_required else InspectionStatus.NOT_REQUIRED

    inspection, _ = ExecutionInspection.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={
            "required": is_required,
            "status": init_status,
            "result": InspectionResult.UNKNOWN,
            "version": 1,
        },
    )
    return inspection


@transaction.atomic
def schedule_inspection(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    scheduled_at: datetime,
    agency: Optional[str] = None,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionInspection:
    """
    Seller/Operator operational action: schedule inspection agency and appointment (Contract §44, §80, T1005).

    Invariants:
    - Restricted to Seller organization non-viewers and Operator/Admin.
    - Concurrency protected via select_for_update and expected_version.
    - Execution must be OPEN.
    - Transitions status to SCHEDULED, marks required = True, result remains UNKNOWN.
    - Reject transition if already COMPLETED or CANCELLED.
    """
    if scheduled_at is None:
        raise ExecutionValidationError("scheduled_at is mandatory to schedule an inspection.")

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal__rfq")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot schedule inspection on an execution that is already CLOSED.")

    check_inspection_mutation_authority(actor, execution, "SCHEDULE")

    inspection = get_or_create_execution_inspection(execution.id, deal_id=deal_id)
    inspection = ExecutionInspection.objects.select_for_update().get(pk=inspection.pk)

    _validate_expected_version(inspection.version, expected_version)

    if inspection.status == InspectionStatus.COMPLETED:
        raise InvalidInspectionTransitionError("Cannot schedule an inspection that is already COMPLETED.")
    if inspection.status == InspectionStatus.CANCELLED:
        raise InvalidInspectionTransitionError("Cannot schedule an inspection that is CANCELLED.")

    inspection.scheduled_at = scheduled_at
    if agency is not None:
        inspection.agency = agency.strip()
    if notes is not None:
        inspection.notes = notes
    inspection.status = InspectionStatus.SCHEDULED
    inspection.required = True
    inspection.result = InspectionResult.UNKNOWN
    inspection.version += 1
    inspection.save()

    return inspection


@transaction.atomic
def complete_inspection(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    inspection_at: datetime,
    result: str,
    agency: Optional[str] = None,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionInspection:
    """
    Seller/Operator operational action: record authoritative completion facts of quality inspection.

    Invariants (Contract §44, §45, §49, T1005):
    - Restricted to Seller organization non-viewers and Operator/Admin.
    - inspection_at is mandatory.
    - result must be one of exact InspectionResult choices (PASS, FAIL, CONDITIONAL, UNKNOWN).
    - Result is NEVER inferred from free-text notes.
    - COMPLETED + FAIL represents a completed inspection whose quality outcome failed;
      it does NOT block INSPECTION_COMPLETED milestone itself.
    - Completed inspection facts are historically immutable (no casual reopen or rewrite).
    - Concurrency protected via select_for_update and expected_version.
    """
    if inspection_at is None:
        raise ExecutionValidationError("inspection_at timestamp is mandatory to complete an inspection.")

    if not result or result not in InspectionResult.values:
        raise ExecutionValidationError(
            f"Invalid inspection result '{result}'. Must be one of {InspectionResult.values}."
        )

    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal__rfq")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot complete inspection on an execution that is already CLOSED.")

    check_inspection_mutation_authority(actor, execution, "COMPLETE")

    inspection = get_or_create_execution_inspection(execution.id, deal_id=deal_id)
    inspection = ExecutionInspection.objects.select_for_update().get(pk=inspection.pk)

    _validate_expected_version(inspection.version, expected_version)

    if inspection.status == InspectionStatus.COMPLETED:
        raise InvalidInspectionTransitionError("Inspection is already COMPLETED.")
    if inspection.status == InspectionStatus.CANCELLED:
        raise InvalidInspectionTransitionError("Cannot complete an inspection that is CANCELLED.")

    inspection.status = InspectionStatus.COMPLETED
    inspection.inspection_at = inspection_at
    inspection.result = result
    if agency is not None:
        inspection.agency = agency.strip()
    if notes is not None:
        inspection.notes = notes
    inspection.version += 1
    inspection.save()

    return inspection


@transaction.atomic
def cancel_inspection(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionInspection:
    """
    Seller/Operator operational action: cancel scheduled or pending inspection (Contract §44, T1005).

    Invariants:
    - Restricted to Seller organization non-viewers and Operator/Admin.
    - Concurrency protected via select_for_update and expected_version.
    - Execution must be OPEN.
    - Completed inspections cannot be cancelled.
    - Stale concurrent race with complete_inspection results in exactly one winner and 409 for loser.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal__rfq")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot cancel inspection on an execution that is already CLOSED.")

    check_inspection_mutation_authority(actor, execution, "CANCEL")

    inspection = get_or_create_execution_inspection(execution.id, deal_id=deal_id)
    inspection = ExecutionInspection.objects.select_for_update().get(pk=inspection.pk)

    _validate_expected_version(inspection.version, expected_version)

    if inspection.status == InspectionStatus.COMPLETED:
        raise InvalidInspectionTransitionError("Cannot cancel an inspection that is already COMPLETED.")
    if inspection.status == InspectionStatus.CANCELLED:
        raise InvalidInspectionTransitionError("Inspection is already CANCELLED.")

    inspection.status = InspectionStatus.CANCELLED
    inspection.result = InspectionResult.UNKNOWN
    if notes is not None:
        inspection.notes = notes
    inspection.version += 1
    inspection.save()

    return inspection


@transaction.atomic
def mark_inspection_not_required(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionInspection:
    """
    Buyer/Operator operational action: mark quality inspection as not required / waived (Contract §44, §80, T1005).

    Invariants:
    - Restricted to Buyer organization non-viewers (waiving party) and Operator/Admin.
    - Seller is strictly denied from unilaterally waiving inspection required by Buyer.
    - Concurrency protected via select_for_update and expected_version.
    - Execution must be OPEN.
    - Cannot mark as NOT_REQUIRED after inspection is already COMPLETED.
    - NOT_REQUIRED result must remain UNKNOWN (never fake PASS).
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .select_related("deal__rfq")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mark inspection not required on an execution that is already CLOSED.")

    check_inspection_mutation_authority(actor, execution, "MARK_NOT_REQUIRED")

    inspection = get_or_create_execution_inspection(execution.id, deal_id=deal_id)
    inspection = ExecutionInspection.objects.select_for_update().get(pk=inspection.pk)

    _validate_expected_version(inspection.version, expected_version)

    if inspection.status == InspectionStatus.COMPLETED:
        raise InvalidInspectionTransitionError("Cannot mark an inspection as NOT_REQUIRED after it is COMPLETED.")

    inspection.status = InspectionStatus.NOT_REQUIRED
    inspection.required = False
    inspection.result = InspectionResult.UNKNOWN
    inspection.scheduled_at = None
    if notes is not None:
        inspection.notes = notes
    inspection.version += 1
    inspection.save()

    return inspection


def render_execution_deal_specifications(
    execution_or_id: Union[Execution, UUID, str],
    *,
    actor: Any = None,
) -> List[Dict[str, Any]]:
    """
    Render quality specifications of an Execution Deal using strictly historical schema version.

    Invariants (Epic 9 Contract §71, Epic 10 Contract §43, T1005):
    - Strictly bound to execution.deal.terms_snapshot.schema_version.
    - Never uses CommodityDefinition.active_schema_version.
    - No hard-coding of Bitumen fields or commodity branching in generic service.
    - Enforces read authorization if actor provided.
    """
    if isinstance(execution_or_id, Execution):
        execution = execution_or_id
    else:
        try:
            execution = (
                Execution.objects.select_related(
                    "deal__terms_snapshot__schema_version",
                    "deal__terms_snapshot__commodity",
                )
                .get(pk=execution_or_id)
            )
        except Execution.DoesNotExist:
            raise ExecutionNotFoundError(f"Execution '{execution_or_id}' does not exist.")

    if actor is not None:
        check_execution_read_access(actor, execution)

    terms_snapshot = getattr(execution.deal, "terms_snapshot", None)
    if not terms_snapshot:
        return []

    return project_deal_specifications(terms_snapshot)
