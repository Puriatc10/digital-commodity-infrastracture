import datetime
from decimal import Decimal
from typing import Any
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from opportunities.exceptions import (
    ContactAttemptNotFoundError,
    InvalidTransitionError,
    OpportunityNotFoundError,
    OpportunityTaskNotFoundError,
)
from opportunities.models import (
    ContactAttemptType,
    Opportunity,
    OpportunityContactAttempt,
    OpportunityIdentifierSequence,
    OpportunitySource,
    OpportunityTask,
    OpportunityTaskStatus,
)
from opportunities.services_lifecycle import (
    TERMINAL_STATUSES,
    OpportunityLifecycleService,
    _extract_opportunity_id,
    convert_opportunity,
    expire_opportunity,
    mark_opportunity_contacted,
    mark_opportunity_lost,
    put_opportunity_on_hold,
    qualify_opportunity,
    reject_opportunity,
    resume_opportunity,
    start_opportunity_matching,
)
from organizations.models import Organization, OrganizationCapability

__all__ = [
    "OpportunityLifecycleService",
    "convert_opportunity",
    "expire_opportunity",
    "mark_opportunity_contacted",
    "mark_opportunity_lost",
    "put_opportunity_on_hold",
    "qualify_opportunity",
    "reject_opportunity",
    "resume_opportunity",
    "start_opportunity_matching",
    "format_opportunity_identifier",
    "allocate_opportunity_sequence",
    "allocate_opportunity_identifier",
    "validate_opportunity_source_and_broker",
    "check_opportunity_mutation_allowed",
    "create_opportunity",
    "update_opportunity",
    "record_contact_attempt",
    "list_contact_attempts",
    "get_contact_attempt",
    "create_opportunity_task",
    "update_opportunity_task",
    "complete_opportunity_task",
    "cancel_opportunity_task",
    "list_opportunity_tasks",
    "get_opportunity_task",
    "get_tasks_assigned_to_user",
    "get_follow_up_required_tasks",
]



def format_opportunity_identifier(year: int, sequence: int) -> str:
    """
    Constructs the canonical human-readable Opportunity reference.

    Format:
        OPP-{YEAR}-{SEQUENCE}

    Rules:
        - Exact 'OPP' prefix
        - Four-digit calendar year
        - Minimum six-digit zero-padded sequence (e.g. OPP-2026-000001, OPP-2026-000124)
        - Sequences exceeding six digits are NOT truncated (e.g. OPP-2026-1000000)
    """
    return f"OPP-{year:04d}-{sequence:06d}"


def allocate_opportunity_sequence(year: int) -> int:
    """
    Allocates the next sequence integer for the specified calendar year.

    Guarantees concurrency safety across multiple processes and threads
    using PostgreSQL row-level locking (`select_for_update`) on
    `OpportunityIdentifierSequence`.

    Sequence Semantics:
        - Separate sequence per calendar year (2026 -> 1, 2, 3...; 2027 -> 1, 2, 3...).
        - Resets to 1 at the beginning of each calendar year.

    Gap Semantics:
        If an allocated sequence number is rolled back due to subsequent
        transaction failure, that sequence integer is not reclaimed.
        Sequence gaps are normal and acceptable in transactional database systems
        to preserve high concurrency and prevent blocking bottlenecks.
    """
    while True:
        try:
            with transaction.atomic():
                seq_record = (
                    OpportunityIdentifierSequence.objects
                    .select_for_update()
                    .filter(year=year)
                    .first()
                )
                if seq_record is None:
                    # Initialize sequence record for this calendar year.
                    # next_value is initialized to 2 since 1 is returned to the caller.
                    OpportunityIdentifierSequence.objects.create(
                        year=year,
                        next_value=2,
                    )
                    return 1

                allocated = seq_record.next_value
                seq_record.next_value = allocated + 1
                seq_record.save(update_fields=["next_value", "updated_at"])
                return allocated
        except IntegrityError:
            # Concurrent initial row insertion collision on the primary key (year).
            # The inner atomic savepoint rolls back cleanly without corrupting
            # the outer transaction. The loop retries and acquires the committed row lock.
            continue


def allocate_opportunity_identifier(
    as_of: datetime.datetime | None = None,
    year: int | None = None,
) -> str:
    """
    Allocates and formats a unique Opportunity identifier.

    Year resolution:
        If `year` is not explicitly provided, it is extracted from `as_of`
        or server-side `timezone.now()`. Client-supplied years are never trusted.
    """
    if year is None:
        ref_time = as_of or timezone.now()
        year = ref_time.year

    seq = allocate_opportunity_sequence(year)
    return format_opportunity_identifier(year, seq)


def validate_opportunity_source_and_broker(
    *,
    source: str,
    broker_id: uuid.UUID | str | None = None,
) -> None:
    """
    Centralized domain validation for Opportunity source and Broker attribution.

    Invariants:
    1. Source must be one of the six approved enum values.
    2. When source == BROKER_REFERRAL:
       - broker_id is mandatory.
       - Referenced Organization must exist.
       - Referenced Organization must possess the Broker capability.
    3. When source != BROKER_REFERRAL:
       - broker_id must be None (stale broker attribution is strictly prohibited).
    """
    errors: dict[str, str] = {}

    if source not in OpportunitySource.values:
        errors["source"] = f"Source must be one of: {', '.join(OpportunitySource.values)}."
        raise ValidationError(errors)

    if source == OpportunitySource.BROKER_REFERRAL:
        if not broker_id:
            errors["broker"] = "Broker organization is required when source is Broker Referral."
        else:
            if not Organization.objects.filter(id=broker_id).exists():
                errors["broker"] = "Attributed broker organization does not exist."
            elif not OrganizationCapability.objects.filter(
                organization_id=broker_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists():
                errors["broker"] = "Attributed organization must possess Broker capability."
    else:
        if broker_id:
            errors["broker"] = "Broker organization must not be set when source is not Broker Referral."

    if errors:
        raise ValidationError(errors)


def check_opportunity_mutation_allowed(
    opportunity: Opportunity,
    field_name: str,
) -> None:
    """
    Guards Opportunity field mutation based on lifecycle state and immutability invariants.
    """
    # Immutable identifier invariant
    if field_name == "identifier":
        raise ValidationError({"identifier": "Opportunity identifier is immutable once created."})

    # Status and version are managed strictly through explicit lifecycle actions
    if field_name == "status":
        raise ValidationError({"status": "Lifecycle status cannot be modified via generic update. Use explicit lifecycle actions."})
    if field_name == "version":
        raise ValidationError({"version": "Version is managed by optimistic concurrency and cannot be directly modified."})

    # Terminal state protection: terminal opportunities cannot be generically modified
    if opportunity.status in TERMINAL_STATUSES:
        raise ValidationError({"status": f"Cannot modify Opportunity in terminal status '{opportunity.status}'."})


@transaction.atomic
def create_opportunity(
    *,
    direction: str,
    organization_id: uuid.UUID | str | None = None,
    external_counterparty_id: uuid.UUID | str | None = None,
    commodity_id: uuid.UUID | str | None = None,
    quantity: Decimal | None = None,
    unit: str = "MT",
    indicative_price: Decimal | None = None,
    currency: str = "USD",
    delivery_window_start: datetime.date | None = None,
    delivery_window_end: datetime.date | None = None,
    payment_terms: str = "",
    geography: str = "",
    notes: str = "",
    source: str = OpportunitySource.OPERATOR_SOURCING,
    broker_id: uuid.UUID | str | None = None,
    created_by: Any = None,
    as_of: datetime.datetime | None = None,
) -> Opportunity:
    """
    Authoritative Opportunity creation service.

    Transaction semantics:
        BEGIN
        -> validate source and broker attribution consistency
        -> allocate unique year/sequence safely (PostgreSQL select_for_update)
        -> construct identifier (OPP-{YEAR}-{SEQUENCE})
        -> create Opportunity
        -> full_clean & save
        -> COMMIT

    Guarantees that identifier generation occurs inside the authoritative
    creation boundary and produces an immutable record.
    """
    validate_opportunity_source_and_broker(source=source, broker_id=broker_id)

    identifier = allocate_opportunity_identifier(as_of=as_of)

    opportunity = Opportunity(
        identifier=identifier,
        direction=direction,
        organization_id=organization_id,
        external_counterparty_id=external_counterparty_id,
        commodity_id=commodity_id,
        quantity=quantity,
        unit=unit,
        indicative_price=indicative_price,
        currency=currency,
        delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end,
        payment_terms=payment_terms,
        geography=geography,
        notes=notes,
        source=source,
        broker_id=broker_id,
        created_by=created_by,
    )
    opportunity.full_clean()
    opportunity.save()
    return opportunity


@transaction.atomic
def update_opportunity(
    opportunity: Opportunity,
    *,
    data: dict[str, Any],
    expected_version: Any = None,
) -> Opportunity:
    """
    Authoritative Opportunity mutation service.

    Centralizes field-level mutation policy, source/broker validation,
    concurrency control, and lifecycle checks.
    """
    opp = Opportunity.objects.select_for_update().get(pk=opportunity.pk)

    exp_ver = expected_version
    if exp_ver is None and "expected_version" in data:
        exp_ver = data["expected_version"]

    if exp_ver is not None:
        from opportunities.services_lifecycle import _validate_expected_version

        _validate_expected_version(opp, exp_ver)

    clean_data = {k: v for k, v in data.items() if k != "expected_version"}

    for field in clean_data.keys():
        check_opportunity_mutation_allowed(opp, field)

    new_source = clean_data.get("source", opp.source)
    if "broker_id" in clean_data:
        new_broker_id = clean_data["broker_id"]
    elif "broker" in clean_data:
        broker_val = clean_data["broker"]
        new_broker_id = broker_val.id if hasattr(broker_val, "id") else broker_val
    else:
        new_broker_id = opp.broker_id

    validate_opportunity_source_and_broker(source=new_source, broker_id=new_broker_id)

    for field, value in clean_data.items():
        if field == "broker_id":
            opp.broker_id = value
        elif field == "organization_id":
            opp.organization_id = value
        elif field == "external_counterparty_id":
            opp.external_counterparty_id = value
        elif field == "commodity_id":
            opp.commodity_id = value
        else:
            setattr(opp, field, value)

    opp.version += 1
    opp.full_clean()
    opp.save()
    return opp


def record_contact_attempt(
    opportunity_or_id: Any,
    *,
    type: str,
    occurred_at: datetime.datetime | None = None,
    notes: str = "",
    actor: Any = None,
) -> OpportunityContactAttempt:
    """
    Records an append-only contact attempt for an Opportunity (Spec §22, Roadmap T0606).

    Guarantees:
    - Verifies parent Opportunity exists.
    - Normalizes and validates contact attempt type against ContactAttemptType.
    - Sets occurred_at to timezone.now() if not provided, and rejects future timestamps.
    - Server-derives recorded_by from the authenticated actor.
    - Append-only: does not alter Opportunity lifecycle state, version, or parent attributes.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    try:
        opp = Opportunity.objects.get(pk=opp_id)
    except Opportunity.DoesNotExist as exc:
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.") from exc

    normalized_type = type.strip().upper() if isinstance(type, str) else type
    if normalized_type not in ContactAttemptType.values:
        raise ValidationError({"type": f"Type must be one of: {', '.join(ContactAttemptType.values)}."})

    if occurred_at is None:
        occurred_at = timezone.now()
    elif occurred_at > timezone.now() + datetime.timedelta(minutes=5):
        raise ValidationError({"occurred_at": "occurred_at cannot be in the future."})

    recorder = actor if actor and getattr(actor, "is_authenticated", False) else None

    attempt = OpportunityContactAttempt(
        opportunity=opp,
        type=normalized_type,
        occurred_at=occurred_at,
        recorded_by=recorder,
        notes=notes or "",
    )
    attempt.full_clean()
    attempt.save()
    return attempt


def list_contact_attempts(opportunity_or_id: Any):
    """
    Retrieves contact attempts for an Opportunity in deterministic activity order:
    Primary: -occurred_at
    Secondary: -created_at
    Tertiary: -id
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    return (
        OpportunityContactAttempt.objects.filter(opportunity_id=opp_id)
        .select_related("recorded_by")
        .order_by("-occurred_at", "-created_at", "-id")
    )


def get_contact_attempt(opportunity_or_id: Any, attempt_id: Any) -> OpportunityContactAttempt:
    """
    Retrieves a single contact attempt strictly scoped to the parent Opportunity.
    Prevents IDOR by verifying that the attempt belongs to the target Opportunity.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    try:
        parsed_attempt_id = uuid.UUID(str(attempt_id))
    except (ValueError, AttributeError):
        raise ContactAttemptNotFoundError(f"Contact attempt '{attempt_id}' not found.")

    attempt = (
        OpportunityContactAttempt.objects.filter(opportunity_id=opp_id, pk=parsed_attempt_id)
        .select_related("recorded_by")
        .first()
    )
    if attempt is None:
        raise ContactAttemptNotFoundError(
            f"Contact attempt '{attempt_id}' not found on Opportunity '{opp_id}'."
        )
    return attempt


_UNSET = object()


def create_opportunity_task(
    opportunity_or_id: Any,
    *,
    title: str,
    due_at: datetime.datetime,
    description: str = "",
    assigned_to_id: Any = None,
    actor: Any = None,
) -> OpportunityTask:
    """
    Creates an operational follow-up task scoped to an Opportunity (Spec §22, Roadmap T0607).

    Guarantees:
    - Verifies parent Opportunity exists.
    - Validates title is non-empty.
    - Validates due_at is provided.
    - If assigned_to_id is provided, validates user is an active Operator or Admin.
    - Server-derives created_by from the authenticated actor.
    - Initializes task in OPEN status with completed_at=None.
    - Strictly does NOT mutate parent Opportunity lifecycle state or create contact attempts.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    try:
        opp = Opportunity.objects.get(pk=opp_id)
    except Opportunity.DoesNotExist as exc:
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.") from exc

    if not title or not title.strip():
        raise ValidationError({"title": "Title is required."})

    if not due_at:
        raise ValidationError({"due_at": "Due date and time is required."})

    if assigned_to_id is not None:
        from identity.models import SystemRoleAssignment, User

        if not User.objects.filter(id=assigned_to_id, is_active=True).exists():
            raise ValidationError({"assigned_to": "Assigned user does not exist or is inactive."})

        is_eligible = SystemRoleAssignment.objects.filter(
            user_id=assigned_to_id,
            role__in=[
                SystemRoleAssignment.SystemRole.OPERATOR,
                SystemRoleAssignment.SystemRole.ADMIN,
            ],
        ).exists()
        if not is_eligible:
            raise ValidationError({"assigned_to": "Assigned user must be an active internal Operator or Admin."})

    creator = actor if actor and getattr(actor, "is_authenticated", False) else None

    task = OpportunityTask(
        opportunity=opp,
        title=title.strip(),
        description=(description or "").strip(),
        due_at=due_at,
        status=OpportunityTaskStatus.OPEN,
        assigned_to_id=assigned_to_id,
        created_by=creator,
        completed_at=None,
    )
    task.full_clean()
    task.save()
    return task


def update_opportunity_task(
    opportunity_or_id: Any,
    task_id: Any,
    *,
    title: Any = _UNSET,
    description: Any = _UNSET,
    due_at: Any = _UNSET,
    assigned_to_id: Any = _UNSET,
    actor: Any = None,
) -> OpportunityTask:
    """
    Updates mutable attributes of an OPEN Opportunity Task.

    Guarantees:
    - Scoped strictly to parent Opportunity (prevents IDOR).
    - Can ONLY update tasks in OPEN status. Rejects updating COMPLETED or CANCELLED tasks.
    - Protects status, completed_at, created_by, and opportunity foreign key against modification.
    - Validates assigned_to_id (if updated) is an eligible Operator or Admin.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    try:
        parsed_task_id = uuid.UUID(str(task_id))
    except (ValueError, AttributeError):
        raise OpportunityTaskNotFoundError(f"Opportunity task '{task_id}' not found.")

    task = OpportunityTask.objects.filter(opportunity_id=opp_id, pk=parsed_task_id).first()
    if task is None:
        raise OpportunityTaskNotFoundError(
            f"Opportunity task '{task_id}' not found on Opportunity '{opp_id}'."
        )

    if task.status != OpportunityTaskStatus.OPEN:
        raise ValidationError(
            {"status": f"Cannot update task in status '{task.status}'. Only OPEN tasks can be updated."}
        )

    if title is not _UNSET:
        if not title or not str(title).strip():
            raise ValidationError({"title": "Title is required."})
        task.title = str(title).strip()

    if description is not _UNSET:
        task.description = (description or "").strip()

    if due_at is not _UNSET:
        if not due_at:
            raise ValidationError({"due_at": "Due date and time is required."})
        task.due_at = due_at

    if assigned_to_id is not _UNSET:
        if assigned_to_id is not None:
            from identity.models import SystemRoleAssignment, User

            if not User.objects.filter(id=assigned_to_id, is_active=True).exists():
                raise ValidationError({"assigned_to": "Assigned user does not exist or is inactive."})

            is_eligible = SystemRoleAssignment.objects.filter(
                user_id=assigned_to_id,
                role__in=[
                    SystemRoleAssignment.SystemRole.OPERATOR,
                    SystemRoleAssignment.SystemRole.ADMIN,
                ],
            ).exists()
            if not is_eligible:
                raise ValidationError({"assigned_to": "Assigned user must be an active internal Operator or Admin."})
        task.assigned_to_id = assigned_to_id

    task.full_clean()
    task.save()
    return task


def complete_opportunity_task(
    opportunity_or_id: Any,
    task_id: Any,
    *,
    actor: Any = None,
) -> OpportunityTask:
    """
    Transitions an OPEN Opportunity Task to COMPLETED.

    Guarantees:
    - Uses PostgreSQL row-level lock (`select_for_update()`) in atomic transaction.
    - Verifies parent Opportunity scoping (prevents IDOR).
    - Rejects transition if task is not in OPEN status:
      - If already COMPLETED: raises InvalidTransitionError.
      - If CANCELLED: raises InvalidTransitionError.
    - Sets completed_at to timezone.now() server-side.
    - Does NOT alter parent Opportunity lifecycle state or create contact attempts.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    try:
        parsed_task_id = uuid.UUID(str(task_id))
    except (ValueError, AttributeError):
        raise OpportunityTaskNotFoundError(f"Opportunity task '{task_id}' not found.")

    with transaction.atomic():
        task = (
            OpportunityTask.objects
            .select_for_update()
            .filter(opportunity_id=opp_id, pk=parsed_task_id)
            .first()
        )
        if task is None:
            raise OpportunityTaskNotFoundError(
                f"Opportunity task '{task_id}' not found on Opportunity '{opp_id}'."
            )

        if task.status != OpportunityTaskStatus.OPEN:
            raise InvalidTransitionError(
                f"Cannot complete task in status '{task.status}'. Only OPEN tasks can be completed."
            )

        task.status = OpportunityTaskStatus.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        return task


def cancel_opportunity_task(
    opportunity_or_id: Any,
    task_id: Any,
    *,
    actor: Any = None,
) -> OpportunityTask:
    """
    Transitions an OPEN Opportunity Task to CANCELLED.

    Guarantees:
    - Uses PostgreSQL row-level lock (`select_for_update()`) in atomic transaction.
    - Verifies parent Opportunity scoping (prevents IDOR).
    - Rejects transition if task is not in OPEN status:
      - If already CANCELLED: raises InvalidTransitionError.
      - If COMPLETED: raises InvalidTransitionError.
    - Does not delete the task.
    - Leaves completed_at null.
    - Does NOT alter parent Opportunity lifecycle state or create contact attempts.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    try:
        parsed_task_id = uuid.UUID(str(task_id))
    except (ValueError, AttributeError):
        raise OpportunityTaskNotFoundError(f"Opportunity task '{task_id}' not found.")

    with transaction.atomic():
        task = (
            OpportunityTask.objects
            .select_for_update()
            .filter(opportunity_id=opp_id, pk=parsed_task_id)
            .first()
        )
        if task is None:
            raise OpportunityTaskNotFoundError(
                f"Opportunity task '{task_id}' not found on Opportunity '{opp_id}'."
            )

        if task.status != OpportunityTaskStatus.OPEN:
            raise InvalidTransitionError(
                f"Cannot cancel task in status '{task.status}'. Only OPEN tasks can be cancelled."
            )

        task.status = OpportunityTaskStatus.CANCELLED
        task.save(update_fields=["status", "updated_at"])
        return task


def list_opportunity_tasks(
    opportunity_or_id: Any,
    *,
    status: Any = None,
    assigned_to_id: Any = None,
    overdue: Any = None,
):
    """
    Retrieves tasks for an Opportunity in deterministic order:
    Primary: due_at ASC
    Secondary: created_at ASC
    Tertiary: id ASC

    Supports filtering by status, assigned_to_id, and overdue.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    qs = (
        OpportunityTask.objects.filter(opportunity_id=opp_id)
        .select_related("assigned_to", "created_by", "opportunity")
        .order_by("due_at", "created_at", "id")
    )

    if status:
        normalized_status = status.strip().upper() if isinstance(status, str) else status
        qs = qs.filter(status=normalized_status)

    if assigned_to_id is not None:
        qs = qs.filter(assigned_to_id=assigned_to_id)

    if overdue is True:
        qs = qs.filter(status=OpportunityTaskStatus.OPEN, due_at__lt=timezone.now())
    elif overdue is False:
        qs = qs.exclude(status=OpportunityTaskStatus.OPEN, due_at__lt=timezone.now())

    return qs


def get_opportunity_task(opportunity_or_id: Any, task_id: Any) -> OpportunityTask:
    """
    Retrieves a single task strictly scoped to the parent Opportunity.
    Prevents IDOR by verifying that the task belongs to the target Opportunity.
    """
    opp_id = _extract_opportunity_id(opportunity_or_id)
    if not Opportunity.objects.filter(pk=opp_id).exists():
        raise OpportunityNotFoundError(f"Opportunity with id '{opp_id}' does not exist.")

    try:
        parsed_task_id = uuid.UUID(str(task_id))
    except (ValueError, AttributeError):
        raise OpportunityTaskNotFoundError(f"Opportunity task '{task_id}' not found.")

    task = (
        OpportunityTask.objects.filter(opportunity_id=opp_id, pk=parsed_task_id)
        .select_related("assigned_to", "created_by", "opportunity")
        .first()
    )
    if task is None:
        raise OpportunityTaskNotFoundError(
            f"Opportunity task '{task_id}' not found on Opportunity '{opp_id}'."
        )
    return task


def get_tasks_assigned_to_user(user: Any, status: str = OpportunityTaskStatus.OPEN):
    """
    Helper for T0612 Opportunity Desk 'Assigned to me' view.
    Retrieves open tasks assigned to the specified user.
    """
    user_id = getattr(user, "id", user)
    return (
        OpportunityTask.objects.filter(assigned_to_id=user_id, status=status)
        .select_related("opportunity", "assigned_to", "created_by")
        .order_by("due_at", "created_at", "id")
    )


def get_follow_up_required_tasks(now: datetime.datetime = None):
    """
    Helper for T0612 Opportunity Desk 'Follow-up required' view.
    Retrieves OPEN tasks that are due or overdue.
    """
    if now is None:
        now = timezone.now()
    return (
        OpportunityTask.objects.filter(status=OpportunityTaskStatus.OPEN, due_at__lte=now)
        .select_related("opportunity", "assigned_to", "created_by")
        .order_by("due_at", "created_at", "id")
    )
