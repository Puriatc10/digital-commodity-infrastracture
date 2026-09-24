from typing import Any, Optional, Union
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from execution.enums import ExecutionStatus, IssueSeverity, IssueStatus, IssueType
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionIssueNotFoundError,
    ExecutionNotFoundError,
    ExecutionValidationError,
    InvalidIssueTransitionError,
    StaleVersionError,
)
from execution.models.execution import Execution
from execution.models.issue import ExecutionIssue
from execution.permissions import check_issue_mutation_authority, check_issue_read_authority


def get_active_blocking_issues(execution_id: Union[UUID, str]) -> QuerySet[ExecutionIssue]:
    """
    Centralized query returning all active blocking issues for an execution instance.

    Invariants (Epic 10 Contract §70, §71, T1008):
    - Blocking is active if and only if:
        blocks_execution = True AND status in {OPEN, IN_PROGRESS}.
    - Resolved or Cancelled issues NEVER block execution closure.
    """
    return ExecutionIssue.objects.filter(
        execution_id=execution_id,
        blocks_execution=True,
        status__in=[IssueStatus.OPEN, IssueStatus.IN_PROGRESS],
    )


@transaction.atomic
def open_issue(
    execution_id: Union[UUID, str],
    *,
    type: str,
    title: str,
    description: str = "",
    severity: Optional[str] = None,
    blocks_execution: bool = False,
    actor: Any,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionIssue:
    """
    Authoritatively open a new ExecutionIssue on an Execution instance (Epic 10 Contract §65–§74, T1008).

    Invariants:
    - Execution must exist and be OPEN. Closed executions reject new issues.
    - Server derives opened_by and opened_at; client cannot forge them.
    - Optimistic concurrency base version is initialized to 1.
    - Status is always initialized to OPEN.
    - Blocks_execution is strictly derived from explicit parameter, never inferred from severity or type.
    - Cross-object deal integrity is verified if deal_id is supplied.
    - Party authorization is verified server-side.
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
        raise ExecutionClosedError("Cannot open an issue on an Execution that is already CLOSED.")

    check_issue_mutation_authority(actor, execution, action_type="OPEN")

    if not title or not title.strip():
        raise ExecutionValidationError("Issue title cannot be empty.")

    if type not in IssueType.values:
        raise ExecutionValidationError(f"Invalid issue type '{type}'.")

    if severity is not None and severity not in IssueSeverity.values:
        raise ExecutionValidationError(f"Invalid issue severity '{severity}'.")

    issue = ExecutionIssue.objects.create(
        execution=execution,
        type=type,
        status=IssueStatus.OPEN,
        severity=severity,
        title=title.strip(),
        description=description.strip() if description else "",
        opened_by=actor if getattr(actor, "is_authenticated", False) else None,
        opened_at=timezone.now(),
        blocks_execution=bool(blocks_execution),
        version=1,
    )

    return issue


@transaction.atomic
def start_issue(
    execution_id: Union[UUID, str],
    issue_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionIssue:
    """
    Transition an ExecutionIssue from OPEN to IN_PROGRESS (investigation/resolution started).

    Invariants:
    - Execution must exist and be OPEN.
    - Issue must belong to the Execution.
    - Optimistic concurrency control verifies expected_version == issue.version.
    - Transition is strictly valid from OPEN to IN_PROGRESS.
    - Terminal states (RESOLVED, CANCELLED) cannot be started.
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
        raise ExecutionClosedError("Cannot mutate issues on an Execution that is already CLOSED.")

    try:
        issue = (
            ExecutionIssue.objects.select_for_update()
            .select_related("execution__deal")
            .get(pk=issue_id)
        )
    except ExecutionIssue.DoesNotExist:
        raise ExecutionIssueNotFoundError(f"Issue '{issue_id}' does not exist.")

    if issue.execution_id != execution.id:
        raise CrossObjectIntegrityError("Issue does not belong to the referenced Execution.")

    if issue.version != expected_version:
        raise StaleVersionError(
            f"Optimistic concurrency conflict on issue '{issue_id}': "
            f"expected version {expected_version}, but current version is {issue.version}."
        )

    if issue.status == IssueStatus.IN_PROGRESS:
        raise InvalidIssueTransitionError(f"Issue '{issue_id}' is already IN_PROGRESS.")

    if issue.status in {IssueStatus.RESOLVED, IssueStatus.CANCELLED}:
        raise InvalidIssueTransitionError(
            f"Cannot start issue '{issue_id}' in terminal status '{issue.status}'."
        )

    check_issue_mutation_authority(actor, execution, action_type="START")

    issue.status = IssueStatus.IN_PROGRESS
    issue.version += 1
    issue.save()

    return issue


@transaction.atomic
def resolve_issue(
    execution_id: Union[UUID, str],
    issue_id: Union[UUID, str],
    *,
    expected_version: int,
    resolution_notes: str,
    actor: Any,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionIssue:
    """
    Authoritatively resolve an ExecutionIssue (OPEN or IN_PROGRESS -> RESOLVED).

    Invariants:
    - Execution must exist and be OPEN.
    - Optimistic concurrency control verifies expected_version == issue.version.
    - Server derives resolved_by and resolved_at; client cannot forge them.
    - Resolution notes are strictly required.
    - Terminal states cannot be resolved again.
    - Race with concurrent cancellation produces exactly one authoritative state and 409 conflict for loser.
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
        raise ExecutionClosedError("Cannot mutate issues on an Execution that is already CLOSED.")

    try:
        issue = (
            ExecutionIssue.objects.select_for_update()
            .select_related("execution__deal")
            .get(pk=issue_id)
        )
    except ExecutionIssue.DoesNotExist:
        raise ExecutionIssueNotFoundError(f"Issue '{issue_id}' does not exist.")

    if issue.execution_id != execution.id:
        raise CrossObjectIntegrityError("Issue does not belong to the referenced Execution.")

    if issue.version != expected_version:
        raise StaleVersionError(
            f"Optimistic concurrency conflict on issue '{issue_id}': "
            f"expected version {expected_version}, but current version is {issue.version}."
        )

    if issue.status == IssueStatus.RESOLVED:
        raise InvalidIssueTransitionError(f"Issue '{issue_id}' is already RESOLVED.")

    if issue.status == IssueStatus.CANCELLED:
        raise InvalidIssueTransitionError(f"Cannot resolve cancelled issue '{issue_id}'.")

    if not resolution_notes or not resolution_notes.strip():
        raise ExecutionValidationError("Resolution notes are required when resolving an issue.")

    check_issue_mutation_authority(actor, execution, action_type="RESOLVE")

    issue.status = IssueStatus.RESOLVED
    issue.resolved_by = actor if getattr(actor, "is_authenticated", False) else None
    issue.resolved_at = timezone.now()
    issue.resolution_notes = resolution_notes.strip()
    issue.version += 1
    issue.save()

    return issue


@transaction.atomic
def cancel_issue(
    execution_id: Union[UUID, str],
    issue_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionIssue:
    """
    Authoritatively cancel an ExecutionIssue (OPEN or IN_PROGRESS -> CANCELLED).

    Invariants:
    - Execution must exist and be OPEN.
    - Optimistic concurrency control verifies expected_version == issue.version.
    - Terminal states cannot be cancelled.
    - Race with concurrent resolution produces exactly one authoritative state and 409 conflict for loser.
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
        raise ExecutionClosedError("Cannot mutate issues on an Execution that is already CLOSED.")

    try:
        issue = (
            ExecutionIssue.objects.select_for_update()
            .select_related("execution__deal")
            .get(pk=issue_id)
        )
    except ExecutionIssue.DoesNotExist:
        raise ExecutionIssueNotFoundError(f"Issue '{issue_id}' does not exist.")

    if issue.execution_id != execution.id:
        raise CrossObjectIntegrityError("Issue does not belong to the referenced Execution.")

    if issue.version != expected_version:
        raise StaleVersionError(
            f"Optimistic concurrency conflict on issue '{issue_id}': "
            f"expected version {expected_version}, but current version is {issue.version}."
        )

    if issue.status == IssueStatus.CANCELLED:
        raise InvalidIssueTransitionError(f"Issue '{issue_id}' is already CANCELLED.")

    if issue.status == IssueStatus.RESOLVED:
        raise InvalidIssueTransitionError(f"Cannot cancel resolved issue '{issue_id}'.")

    check_issue_mutation_authority(actor, execution, action_type="CANCEL")

    issue.status = IssueStatus.CANCELLED
    if notes and notes.strip():
        issue.description = (
            f"{issue.description}\n[Cancellation notes: {notes.strip()}]"
            if issue.description
            else f"[Cancellation notes: {notes.strip()}]"
        )
    issue.version += 1
    issue.save()

    return issue


def get_execution_issues(
    execution_id: Union[UUID, str],
    *,
    actor: Any = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> QuerySet[ExecutionIssue]:
    """Retrieve all ExecutionIssue records for an Execution instance with access verification."""
    try:
        execution = Execution.objects.select_related("deal").get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if actor is not None:
        check_issue_read_authority(actor, execution)

    return (
        ExecutionIssue.objects.filter(execution=execution)
        .select_related("opened_by", "resolved_by")
        .order_by("-created_at", "-id")
    )


def get_execution_issue_detail(
    execution_id: Union[UUID, str],
    issue_id: Union[UUID, str],
    *,
    actor: Any = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionIssue:
    """Retrieve a single ExecutionIssue detail with access and cross-object verification."""
    try:
        execution = Execution.objects.select_related("deal").get(pk=execution_id)
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    try:
        issue = (
            ExecutionIssue.objects.select_related("execution__deal", "opened_by", "resolved_by")
            .get(pk=issue_id)
        )
    except ExecutionIssue.DoesNotExist:
        raise ExecutionIssueNotFoundError(f"Issue '{issue_id}' does not exist.")

    if issue.execution_id != execution.id:
        raise CrossObjectIntegrityError("Issue does not belong to the referenced Execution.")

    if actor is not None:
        check_issue_read_authority(actor, execution)

    return issue
