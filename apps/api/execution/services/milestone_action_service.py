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

    # Authoritative completion transition
    completion_time = actual_at or timezone.now()
    milestone.status = MilestoneStatus.COMPLETED
    milestone.actual_at = completion_time
    milestone.recorded_at = timezone.now()
    milestone.completed_by = actor
    if notes is not None:
        milestone.notes = notes
    milestone.version += 1
    milestone.save()

    # Terminal close side-effect (Epic 10 Contract §31)
    if milestone.definition.terminal:
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
