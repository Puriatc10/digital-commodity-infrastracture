from typing import Any, Dict, List, Union
from uuid import UUID

from execution.enums import ExecutionStatus, MilestoneStatus, TimelineEventType
from execution.exceptions import ExecutionNotFoundError
from execution.models.execution import Execution
from execution.permissions import check_execution_read_access

# Authoritative tie-breaker priorities (Epic 10 Contract §34, T1003)
EVENT_TYPE_PRIORITY: Dict[str, int] = {
    TimelineEventType.EXECUTION_CREATED: 10,
    TimelineEventType.MILESTONE_STARTED: 20,
    TimelineEventType.MILESTONE_COMPLETED: 30,
    TimelineEventType.MILESTONE_BLOCKED: 35,
    TimelineEventType.MILESTONE_SKIPPED: 40,
    TimelineEventType.EXECUTION_CLOSED: 50,
}


def project_execution_timeline(
    execution_or_id: Union[Execution, UUID, str],
    *,
    actor: Any = None,
) -> List[Dict[str, Any]]:
    """
    Project deterministic execution timeline from underlying domain aggregate facts.

    Invariants (Epic 10 Contract §32, §33, §34, T1003):
    - Sources strictly domain facts from Execution aggregate and its ExecutionMilestone instances.
    - Historical rendering uses definitions from the Execution's bound workflow template version.
    - Deterministic ordering:
        event_at ASC -> stable_type_priority ASC -> stable_id ASC.
    - Timestamp ties are strictly and deterministically broken by type priority then ID.
    - Read authorization is enforced for requesting actor.
    """
    if isinstance(execution_or_id, Execution):
        execution = execution_or_id
    else:
        try:
            execution = (
                Execution.objects.select_related("deal__created_by", "workflow_template_version__template")
                .prefetch_related("milestones__definition", "milestones__completed_by")
                .get(pk=execution_or_id)
            )
        except Execution.DoesNotExist:
            raise ExecutionNotFoundError(f"Execution '{execution_or_id}' does not exist.")

    if actor is not None:
        check_execution_read_access(actor, execution)

    events: List[Dict[str, Any]] = []

    # 1. Execution created event
    created_actor_id = None
    created_actor_email = None
    if execution.deal and execution.deal.created_by:
        created_actor_id = str(execution.deal.created_by.id)
        created_actor_email = getattr(execution.deal.created_by, "email", None)

    events.append({
        "event_id": f"execution-{execution.id}-created",
        "event_type": TimelineEventType.EXECUTION_CREATED,
        "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.EXECUTION_CREATED],
        "event_at": execution.started_at or execution.created_at,
        "recorded_at": execution.created_at,
        "actor_id": created_actor_id,
        "actor_email": created_actor_email,
        "milestone_code": None,
        "milestone_name_fa": None,
        "milestone_name_en": None,
        "notes": "",
        "metadata": {
            "template_code": execution.workflow_template_version.template.code,
            "template_name_fa": execution.workflow_template_version.template.name_fa,
            "template_name_en": execution.workflow_template_version.template.name_en,
            "workflow_version": execution.workflow_template_version.version_number,
            "status": execution.status,
        },
    })

    # 2. Milestone domain facts
    milestones = list(
        execution.milestones.select_related("definition", "completed_by").order_by("definition__sort_order")
    )

    for m in milestones:
        defn = m.definition
        m_actor_id = str(m.completed_by.id) if m.completed_by else None
        m_actor_email = getattr(m.completed_by, "email", None) if m.completed_by else None

        if m.status == MilestoneStatus.COMPLETED:
            events.append({
                "event_id": f"milestone-{m.id}-completed",
                "event_type": TimelineEventType.MILESTONE_COMPLETED,
                "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.MILESTONE_COMPLETED],
                "event_at": m.actual_at or m.recorded_at or m.updated_at,
                "recorded_at": m.recorded_at or m.updated_at,
                "actor_id": m_actor_id,
                "actor_email": m_actor_email,
                "milestone_code": defn.code,
                "milestone_name_fa": defn.name_fa,
                "milestone_name_en": defn.name_en,
                "notes": m.notes,
                "metadata": {
                    "sort_order": defn.sort_order,
                    "terminal": defn.terminal,
                    "blocking": defn.blocking,
                    "required": defn.required,
                },
            })
        elif m.status == MilestoneStatus.IN_PROGRESS:
            events.append({
                "event_id": f"milestone-{m.id}-started",
                "event_type": TimelineEventType.MILESTONE_STARTED,
                "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.MILESTONE_STARTED],
                "event_at": m.updated_at,
                "recorded_at": m.updated_at,
                "actor_id": m_actor_id,
                "actor_email": m_actor_email,
                "milestone_code": defn.code,
                "milestone_name_fa": defn.name_fa,
                "milestone_name_en": defn.name_en,
                "notes": m.notes,
                "metadata": {
                    "sort_order": defn.sort_order,
                    "terminal": defn.terminal,
                    "blocking": defn.blocking,
                    "required": defn.required,
                },
            })
        elif m.status == MilestoneStatus.BLOCKED:
            events.append({
                "event_id": f"milestone-{m.id}-blocked",
                "event_type": TimelineEventType.MILESTONE_BLOCKED,
                "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.MILESTONE_BLOCKED],
                "event_at": m.updated_at,
                "recorded_at": m.updated_at,
                "actor_id": m_actor_id,
                "actor_email": m_actor_email,
                "milestone_code": defn.code,
                "milestone_name_fa": defn.name_fa,
                "milestone_name_en": defn.name_en,
                "notes": m.notes,
                "metadata": {
                    "sort_order": defn.sort_order,
                },
            })
        elif m.status == MilestoneStatus.SKIPPED:
            events.append({
                "event_id": f"milestone-{m.id}-skipped",
                "event_type": TimelineEventType.MILESTONE_SKIPPED,
                "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.MILESTONE_SKIPPED],
                "event_at": m.updated_at,
                "recorded_at": m.updated_at,
                "actor_id": m_actor_id,
                "actor_email": m_actor_email,
                "milestone_code": defn.code,
                "milestone_name_fa": defn.name_fa,
                "milestone_name_en": defn.name_en,
                "notes": m.notes,
                "metadata": {
                    "sort_order": defn.sort_order,
                },
            })

    # 3. Execution closed event
    if execution.status == ExecutionStatus.CLOSED:
        events.append({
            "event_id": f"execution-{execution.id}-closed",
            "event_type": TimelineEventType.EXECUTION_CLOSED,
            "type_priority": EVENT_TYPE_PRIORITY[TimelineEventType.EXECUTION_CLOSED],
            "event_at": execution.closed_at or execution.updated_at,
            "recorded_at": execution.updated_at,
            "actor_id": None,
            "actor_email": None,
            "milestone_code": None,
            "milestone_name_fa": None,
            "milestone_name_en": None,
            "notes": "Execution operational lifecycle successfully concluded.",
            "metadata": {
                "closed_at": execution.closed_at.isoformat() if execution.closed_at else None,
            },
        })

    # 4. Deterministic sort: (event_at ASC, stable_type_priority, stable_id ASC)
    events.sort(key=lambda ev: (ev["event_at"], ev["type_priority"], str(ev["event_id"])))

    return events
