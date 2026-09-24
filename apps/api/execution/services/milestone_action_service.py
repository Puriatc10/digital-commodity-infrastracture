from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from execution.enums import ExecutionStatus, MilestoneStatus
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionNotFoundError,
    ExecutionValidationError,
    InvalidMilestoneTransitionError,
    MilestoneAlreadyCompletedError,
    MilestoneNotFoundError,
    MilestonePrerequisiteUnmetError,
    StaleVersionError,
)
from execution.models.execution import Execution
from execution.models.milestone import ExecutionMilestone
from execution.permissions import check_execution_mutation_access, is_operator_or_admin


def _validate_expected_version(current: int, expected: Any) -> None:
    """Validate optimistic concurrency expected_version."""
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ExecutionValidationError("expected_version must be a positive integer.")
    if current != expected:
        raise StaleVersionError(
            f"Optimistic concurrency conflict: expected_version={expected}, current version={current}."
        )


def _check_prerequisites_satisfied(execution: Execution, milestone: ExecutionMilestone) -> None:
    """
    Verify all prerequisites defined on the milestone definition are COMPLETED for this execution.
    Prerequisites are strictly resolved from the execution's bound workflow template version.
    """
    prereq_def_ids = list(milestone.definition.prerequisites.values_list("id", flat=True))
    if not prereq_def_ids:
        return

    incomplete_prereqs = list(
        ExecutionMilestone.objects.filter(
            execution=execution,
            definition_id__in=prereq_def_ids,
        )
        .exclude(status=MilestoneStatus.COMPLETED)
        .select_related("definition")
    )

    if incomplete_prereqs:
        incomplete_codes = [m.definition.code for m in incomplete_prereqs]
        raise MilestonePrerequisiteUnmetError(
            f"Cannot advance milestone '{milestone.definition.code}'. "
            f"Prerequisite milestones {incomplete_codes} must be COMPLETED first."
        )


def _check_milestone_logistics_guards(execution: Execution, milestone: ExecutionMilestone) -> None:
    """
    Verify authoritative T1004 operational logistics facts for corresponding milestones.

    Invariants (Epic 10 Contract §25, §26, §29, T1004):
    - LOADING_SCHEDULED requires scheduled_loading_at in logistics tracking.
    - LOADED requires actual_loading_at in logistics tracking.
    - DELIVERED requires actual_delivery_at in logistics tracking.
    - DELIVERED does NOT imply ACCEPTED.
    - Does not branch on commodity code (generic milestone definition code check).
    """
    code = milestone.definition.code
    if code in {"LOADING_SCHEDULED", "LOADED", "DELIVERED"}:
        from execution.models.logistics import ExecutionLogistics

        logistics = ExecutionLogistics.objects.filter(execution=execution).first()
        if code == "LOADING_SCHEDULED":
            if not logistics or not logistics.scheduled_loading_at:
                raise ExecutionValidationError(
                    "Milestone 'LOADING_SCHEDULED' requires scheduled loading date/time in logistics tracking."
                )
        elif code == "LOADED":
            if not logistics or not logistics.actual_loading_at:
                raise ExecutionValidationError(
                    "Milestone 'LOADED' requires actual loading date/time in logistics tracking."
                )
        elif code == "DELIVERED":
            if not logistics or not logistics.actual_delivery_at:
                raise ExecutionValidationError(
                    "Milestone 'DELIVERED' requires actual delivery date/time in logistics tracking."
                )


def _check_milestone_inspection_guards(execution: Execution, milestone: ExecutionMilestone) -> None:
    """
    Verify authoritative quality inspection facts for INSPECTION_COMPLETED milestone (Epic 10 Contract §49, T1005).

    Invariants:
    - Milestone 'INSPECTION_COMPLETED' may complete when:
        1. inspection.status == NOT_REQUIRED; or
        2. inspection.status == COMPLETED.
    - If status is PENDING, SCHEDULED, or CANCELLED, milestone cannot complete.
    - Result PASS is NOT required to complete milestone; COMPLETED + FAIL is valid
      (represents that inspection occurred; downstream acceptance/issues handle quality failure).
    - If inspection record does not exist, status cannot be verified -> rejects completion.
    """
    code = milestone.definition.code
    if code == "INSPECTION_COMPLETED":
        from execution.enums import InspectionStatus
        from execution.models.inspection import ExecutionInspection

        inspection = ExecutionInspection.objects.filter(execution=execution).first()
        if not inspection:
            raise ExecutionValidationError(
                "Milestone 'INSPECTION_COMPLETED' requires inspection record to be initialized."
            )
        if inspection.status not in {InspectionStatus.NOT_REQUIRED, InspectionStatus.COMPLETED}:
            raise ExecutionValidationError(
                f"Milestone 'INSPECTION_COMPLETED' requires inspection status to be COMPLETED or NOT_REQUIRED "
                f"(current status: '{inspection.status}')."
            )


def _check_milestone_payment_guards(execution: Execution, milestone: ExecutionMilestone) -> None:
    """
    Verify authoritative payment monitoring facts for PAYMENT_REPORTED milestone (Epic 10 Contract §58, T1006).

    Invariants:
    - Milestone 'PAYMENT_REPORTED' may complete when:
        1. payment.status == REPORTED; or
        2. payment.status == CONFIRMED.
    - If payment record does not exist or status is EXPECTED, rejects completion.
    - Milestone cannot independently create or alter payment state; ExecutionPayment is source of truth.
    """
    code = milestone.definition.code
    if code == "PAYMENT_REPORTED":
        from execution.enums import PaymentStatus
        from execution.models.payment import ExecutionPayment

        payment = ExecutionPayment.objects.filter(execution=execution).first()
        if not payment:
            raise ExecutionValidationError(
                "Milestone 'PAYMENT_REPORTED' requires payment monitoring record to be initialized."
            )
        if payment.status not in {PaymentStatus.REPORTED, PaymentStatus.CONFIRMED}:
            raise ExecutionValidationError(
                f"Milestone 'PAYMENT_REPORTED' requires payment status to be REPORTED or CONFIRMED "
                f"(current status: '{payment.status}')."
            )


@transaction.atomic
def complete_milestone(
    execution_id: Union[UUID, str],
    milestone_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    actual_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionMilestone:
    """
    Authoritatively complete an execution milestone (Epic 10 Contract §17, §18, §31, T1003).

    Invariants:
    - Preconditions checked under select_for_update row lock:
        1. Execution must be OPEN.
        2. Expected version matches current milestone version (raises StaleVersionError).
        3. Cross-object references belong to the same Execution and Deal.
        4. Actor has verified operational mutation authority.
        5. Milestone prerequisites are strictly COMPLETED.
        6. Reopening or casual mutation of already COMPLETED milestones is strictly rejected.
    - If milestone.definition.terminal is True:
        Atomically transitions Execution to CLOSED status and sets closed_at = milestone.actual_at.
    - Closed executions reject further mutations.
    - PostgreSQL concurrency race between complete actions produces exactly one winner and 409 for loser.
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
        raise ExecutionClosedError("Cannot mutate milestones on an execution that is already CLOSED.")

    try:
        milestone = (
            ExecutionMilestone.objects.select_for_update()
            .select_related("definition", "execution__deal")
            .get(pk=milestone_id)
        )
    except ExecutionMilestone.DoesNotExist:
        raise MilestoneNotFoundError(f"Milestone '{milestone_id}' does not exist.")

    if milestone.execution_id != execution.id:
        raise CrossObjectIntegrityError("Milestone does not belong to the referenced Execution.")

    # Optimistic concurrency check
    _validate_expected_version(milestone.version, expected_version)

    # Immutability of already COMPLETED milestone
    if milestone.status == MilestoneStatus.COMPLETED:
        raise MilestoneAlreadyCompletedError(
            f"Milestone '{milestone.definition.code}' is already COMPLETED. "
            "Completed milestones cannot be modified or reopened."
        )

    # Authorization
    check_execution_mutation_access(actor, execution, milestone_code=milestone.definition.code)

    # Prerequisites check
    _check_prerequisites_satisfied(execution, milestone)

    # Logistics authoritative facts guard (Epic 10 Contract §25, §26, §29, T1004)
    _check_milestone_logistics_guards(execution, milestone)

    # Quality & inspection authoritative facts guard (Epic 10 Contract §49, T1005)
    _check_milestone_inspection_guards(execution, milestone)

    # Payment monitoring authoritative facts guard (Epic 10 Contract §58, T1006)
    _check_milestone_payment_guards(execution, milestone)

    # Authoritative completion transition
    code = milestone.definition.code
    source_time = actual_at
    if not source_time and code in {
        "LOADING_SCHEDULED",
        "LOADED",
        "DELIVERED",
        "INSPECTION_COMPLETED",
        "PAYMENT_REPORTED",
    }:
        if code in {"LOADING_SCHEDULED", "LOADED", "DELIVERED"}:
            from execution.models.logistics import ExecutionLogistics

            logistics = ExecutionLogistics.objects.filter(execution=execution).first()
            if logistics:
                if code == "LOADING_SCHEDULED" and logistics.scheduled_loading_at:
                    source_time = logistics.scheduled_loading_at
                elif code == "LOADED" and logistics.actual_loading_at:
                    source_time = logistics.actual_loading_at
                elif code == "DELIVERED" and logistics.actual_delivery_at:
                    source_time = logistics.actual_delivery_at
        elif code == "INSPECTION_COMPLETED":
            from execution.models.inspection import ExecutionInspection

            inspection = ExecutionInspection.objects.filter(execution=execution).first()
            if inspection and inspection.inspection_at:
                source_time = inspection.inspection_at
        elif code == "PAYMENT_REPORTED":
            from execution.models.payment import ExecutionPayment

            payment = ExecutionPayment.objects.filter(execution=execution).first()
            if payment and payment.reported_at:
                source_time = payment.reported_at


    completion_time = source_time or timezone.now()
    milestone.status = MilestoneStatus.COMPLETED
    milestone.actual_at = completion_time
    milestone.recorded_at = timezone.now()
    milestone.completed_by = actor
    if notes is not None:
        milestone.notes = notes
    milestone.version += 1
    milestone.save()

    # Terminal close side-effect (Epic 10 Contract §31, §71, T1008)
    if milestone.definition.terminal:
        from execution.exceptions import ExecutionClosingBlockedError
        from execution.services.issue_service import get_active_blocking_issues

        active_blockers = list(get_active_blocking_issues(execution.id))
        if active_blockers:
            blocker_ids = [str(b.id) for b in active_blockers]
            raise ExecutionClosingBlockedError(
                message=f"Cannot close execution '{execution.id}': active blocking issue(s) exist ({', '.join(blocker_ids)}).",
                code="BLOCKING_ISSUE_OPEN",
                context={"blocking_issue_ids": blocker_ids},
            )

        execution.status = ExecutionStatus.CLOSED
        execution.closed_at = completion_time
        execution.version += 1
        execution.save()

    return milestone


@transaction.atomic
def start_milestone(
    execution_id: Union[UUID, str],
    milestone_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionMilestone:
    """Transition milestone from PENDING to IN_PROGRESS."""
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
        raise ExecutionClosedError("Cannot mutate milestones on an execution that is already CLOSED.")

    try:
        milestone = (
            ExecutionMilestone.objects.select_for_update()
            .select_related("definition", "execution__deal")
            .get(pk=milestone_id)
        )
    except ExecutionMilestone.DoesNotExist:
        raise MilestoneNotFoundError(f"Milestone '{milestone_id}' does not exist.")

    if milestone.execution_id != execution.id:
        raise CrossObjectIntegrityError("Milestone does not belong to the referenced Execution.")

    _validate_expected_version(milestone.version, expected_version)

    if milestone.status == MilestoneStatus.COMPLETED:
        raise MilestoneAlreadyCompletedError("Completed milestone cannot be started.")

    if milestone.status != MilestoneStatus.PENDING:
        raise InvalidMilestoneTransitionError(
            f"Cannot start milestone in status '{milestone.status}'. Only PENDING milestones can be started."
        )

    check_execution_mutation_access(actor, execution, milestone_code=milestone.definition.code)
    _check_prerequisites_satisfied(execution, milestone)

    milestone.status = MilestoneStatus.IN_PROGRESS
    if notes is not None:
        milestone.notes = notes
    milestone.version += 1
    milestone.save()

    return milestone


@transaction.atomic
def block_milestone(
    execution_id: Union[UUID, str],
    milestone_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    reason: str,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionMilestone:
    """Transition milestone to BLOCKED with mandatory reason."""
    if not reason or not reason.strip():
        raise ExecutionValidationError("A non-empty reason is mandatory to mark a milestone BLOCKED.")

    try:
        execution = Execution.objects.select_for_update().get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate milestones on an execution that is already CLOSED.")

    try:
        milestone = (
            ExecutionMilestone.objects.select_for_update()
            .select_related("definition", "execution__deal")
            .get(pk=milestone_id)
        )
    except ExecutionMilestone.DoesNotExist:
        raise MilestoneNotFoundError(f"Milestone '{milestone_id}' does not exist.")

    if milestone.execution_id != execution.id:
        raise CrossObjectIntegrityError("Milestone does not belong to the referenced Execution.")

    _validate_expected_version(milestone.version, expected_version)

    if milestone.status == MilestoneStatus.COMPLETED:
        raise MilestoneAlreadyCompletedError("Completed milestone cannot be marked BLOCKED.")

    check_execution_mutation_access(actor, execution, milestone_code=milestone.definition.code)

    milestone.status = MilestoneStatus.BLOCKED
    milestone.notes = reason.strip()
    milestone.version += 1
    milestone.save()

    return milestone


@transaction.atomic
def skip_milestone(
    execution_id: Union[UUID, str],
    milestone_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    reason: str,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionMilestone:
    """Transition milestone to SKIPPED with mandatory reason."""
    if not reason or not reason.strip():
        raise ExecutionValidationError("A non-empty reason is mandatory to mark a milestone SKIPPED.")

    try:
        execution = Execution.objects.select_for_update().get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot mutate milestones on an execution that is already CLOSED.")

    try:
        milestone = (
            ExecutionMilestone.objects.select_for_update()
            .select_related("definition", "execution__deal")
            .get(pk=milestone_id)
        )
    except ExecutionMilestone.DoesNotExist:
        raise MilestoneNotFoundError(f"Milestone '{milestone_id}' does not exist.")

    if milestone.execution_id != execution.id:
        raise CrossObjectIntegrityError("Milestone does not belong to the referenced Execution.")

    _validate_expected_version(milestone.version, expected_version)

    if milestone.status == MilestoneStatus.COMPLETED:
        raise MilestoneAlreadyCompletedError("Completed milestone cannot be marked SKIPPED.")

    # Only non-required milestones or Operator/Admin can skip milestones
    if milestone.definition.required and not is_operator_or_admin(actor):
        raise ExecutionValidationError(
            f"Milestone '{milestone.definition.code}' is marked required. Only Platform Operators can skip required milestones."
        )

    check_execution_mutation_access(actor, execution, milestone_code=milestone.definition.code)

    milestone.status = MilestoneStatus.SKIPPED
    milestone.notes = reason.strip()
    milestone.version += 1
    milestone.save()

    return milestone
