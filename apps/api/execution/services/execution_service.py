from typing import Any, Optional, Union
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from deals.models import Deal
from execution.enums import ExecutionStatus, MilestoneStatus, WorkflowVersionStatus
from execution.exceptions import (
    ExecutionNotFoundError,
    ExecutionValidationError,
    NoActiveWorkflowVersionError,
    WorkflowTemplateInactiveError,
    WorkflowVersionNotFoundError,
)
from execution.models.execution import Execution, lock_executions
from execution.models.milestone import ExecutionMilestone
from execution.models.template import ExecutionWorkflowTemplate
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.permissions import check_execution_mutation_access
from execution.services.active_resolution_service import get_active_workflow_template_version


def resolve_workflow_version_for_deal(
    deal: Deal,
    *,
    workflow_template_code: Optional[str] = None,
    workflow_template_id: Optional[Union[UUID, str]] = None,
    workflow_template_version_id: Optional[Union[UUID, str]] = None,
) -> ExecutionWorkflowTemplateVersion:
    """
    Deterministically resolve the workflow template version to bind for a new Deal Execution.

    Invariants:
    - Must resolve to a PUBLISHED version.
    - DRAFT and RETIRED versions are strictly rejected.
    - If explicit version is specified, it must be PUBLISHED.
    - If explicit template is specified, its active published version is resolved.
    - If unspecified, generic resolution resolves the standard template matching the deal commodity code.
    - No hard-coded branching on specific commodity codes in generic service.
    """
    if workflow_template_version_id:
        try:
            version = ExecutionWorkflowTemplateVersion.objects.select_related("template").get(
                pk=workflow_template_version_id
            )
        except ExecutionWorkflowTemplateVersion.DoesNotExist:
            raise WorkflowVersionNotFoundError(
                f"Workflow template version '{workflow_template_version_id}' not found."
            )
        if version.status != WorkflowVersionStatus.PUBLISHED:
            raise ExecutionValidationError(
                f"Cannot bind execution to workflow version in '{version.status}' status. "
                "Only PUBLISHED workflow versions can be used for new executions."
            )
        return version

    if workflow_template_code or workflow_template_id:
        target = workflow_template_code or workflow_template_id
        return get_active_workflow_template_version(target)

    # Generic convention resolution based on Deal RFQ commodity code
    commodity = getattr(getattr(deal, "rfq", None), "commodity", None)
    if commodity and commodity.code:
        candidate_codes = [f"{commodity.code}_standard", commodity.code]
        for c_code in candidate_codes:
            template = ExecutionWorkflowTemplate.objects.filter(code=c_code, is_active=True).first()
            if template and template.active_version_id:
                try:
                    return get_active_workflow_template_version(template)
                except (WorkflowTemplateInactiveError, NoActiveWorkflowVersionError):
                    continue

    # Fallback to single active template if only one exists on platform
    active_templates = list(ExecutionWorkflowTemplate.objects.filter(is_active=True).exclude(active_version=None))
    if len(active_templates) == 1:
        return get_active_workflow_template_version(active_templates[0])

    raise ExecutionValidationError(
        "Could not resolve an active workflow template for this deal. "
        "Please provide explicit workflow_template_code or workflow_template_version_id."
    )


@transaction.atomic
def create_or_get_execution_for_deal(
    deal_id: Union[UUID, str],
    *,
    workflow_template_code: Optional[str] = None,
    workflow_template_id: Optional[Union[UUID, str]] = None,
    workflow_template_version_id: Optional[Union[UUID, str]] = None,
    actor: Any = None,
) -> Execution:
    """
    Explicit idempotent domain action to materialize or retrieve the Execution aggregate for a Deal.

    Invariants (Epic 10 Contract §5, §6, §7, §20, §22, T1003):
    - 1 Deal -> exactly 1 Execution.
    - Repeated calls return the existing Execution instance without duplicating rows or re-initializing milestones.
    - Bound workflow_template_version is set at creation and never re-bound.
    - Milestone definitions from the bound version are materialized in deterministic sort order.
    - AWARDED milestone auto-completes at creation using the authoritative source timestamp (Award.finalized_at
      or deal.created_at) without fabricating fake actors.
    - All other milestones are initialized as PENDING.
    - Protected against real PostgreSQL concurrent creation races via database uniqueness and transaction locking.
    """
    try:
        deal = (
            Deal.objects.select_related("award", "rfq__commodity", "buyer_organization", "seller_organization")
            .get(pk=deal_id)
        )
    except Deal.DoesNotExist:
        raise ExecutionValidationError(f"Deal '{deal_id}' does not exist.")

    if actor is not None:
        check_execution_mutation_access(actor, deal)

    # 1. Fast check: return existing if already present
    existing = (
        Execution.objects.select_related("workflow_template_version__template")
        .prefetch_related("milestones__definition")
        .filter(deal=deal)
        .first()
    )
    if existing:
        return existing

    # 2. Concurrency-safe creation under savepoint
    version = resolve_workflow_version_for_deal(
        deal,
        workflow_template_code=workflow_template_code,
        workflow_template_id=workflow_template_id,
        workflow_template_version_id=workflow_template_version_id,
    )

    # Determine execution start timestamp and AWARDED source completion timestamp
    source_finalized_at = getattr(deal.award, "finalized_at", None) if getattr(deal, "award", None) else None
    start_time = source_finalized_at or getattr(deal, "created_at", None) or timezone.now()

    try:
        with transaction.atomic():
            execution = Execution.objects.create(
                deal=deal,
                workflow_template_version=version,
                status=ExecutionStatus.OPEN,
                version=1,
                started_at=start_time,
            )
    except IntegrityError:
        # Concurrent creation race: another transaction committed or is committing Execution for this deal
        # Acquire row lock to wait for winning transaction's full milestone initialization to finish
        execution = (
            Execution.objects.select_for_update()
            .select_related("workflow_template_version__template")
            .get(deal=deal)
        )
        return execution

    # Lock this new execution
    lock_executions([execution.pk])

    # 3. Materialize milestones from bound version definitions
    definitions = list(version.milestones.all().order_by("sort_order"))
    milestones_to_create = []

    awarded_completed_by = getattr(deal.award, "finalized_by", None) if getattr(deal, "award", None) else None

    for defn in definitions:
        if defn.code == "AWARDED":
            # AWARDED auto-completes at creation from authoritative Award/Deal source facts
            milestone = ExecutionMilestone(
                execution=execution,
                definition=defn,
                status=MilestoneStatus.COMPLETED,
                expected_at=start_time,
                actual_at=start_time,
                recorded_at=timezone.now(),
                completed_by=awarded_completed_by,
                notes="Auto-completed upon execution creation from finalized Award.",
                version=1,
            )
        else:
            milestone = ExecutionMilestone(
                execution=execution,
                definition=defn,
                status=MilestoneStatus.PENDING,
                version=1,
            )
        milestones_to_create.append(milestone)

    ExecutionMilestone.objects.bulk_create(milestones_to_create)

    # Idempotently initialize ExecutionLogistics (Epic 10 Contract §35, T1004)
    from execution.models.logistics import ExecutionLogistics

    ExecutionLogistics.objects.get_or_create(
        execution=execution,
        defaults={"version": 1},
    )

    # Idempotently initialize ExecutionInspection (Epic 10 Contract §43, §46, T1005)
    from execution.enums import InspectionResult, InspectionStatus
    from execution.models.inspection import ExecutionInspection

    rfq = getattr(deal, "rfq", None)
    is_required = bool(rfq and getattr(rfq, "inspection_required", False))
    init_status = InspectionStatus.PENDING if is_required else InspectionStatus.NOT_REQUIRED

    ExecutionInspection.objects.get_or_create(
        execution=execution,
        defaults={
            "required": is_required,
            "status": init_status,
            "result": InspectionResult.UNKNOWN,
            "version": 1,
        },
    )

    # Idempotently initialize ExecutionPayment (Epic 10 Contract §50–§59, T1006)
    from execution.services.payment_service import get_or_create_execution_payment

    get_or_create_execution_payment(execution.id)

    return execution



def get_execution_for_deal(deal_id: Union[UUID, str], *, actor: Any = None) -> Execution:
    """Retrieve the execution aggregate for a Deal."""
    try:
        execution = (
            Execution.objects.select_related("deal", "workflow_template_version__template")
            .prefetch_related("milestones__definition")
            .get(deal_id=deal_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution for Deal '{deal_id}' does not exist.")

    if actor is not None:
        from execution.permissions import check_execution_read_access
        check_execution_read_access(actor, execution)

    return execution


def get_execution_by_id(execution_id: Union[UUID, str], *, actor: Any = None) -> Execution:
    """Retrieve the execution aggregate by UUID."""
    try:
        execution = (
            Execution.objects.select_related("deal", "workflow_template_version__template")
            .prefetch_related("milestones__definition")
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if actor is not None:
        from execution.permissions import check_execution_read_access
        check_execution_read_access(actor, execution)

    return execution
