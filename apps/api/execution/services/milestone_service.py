from typing import Any, List, Optional

from django.db import transaction

from execution.enums import WorkflowVersionStatus
from execution.exceptions import (
    ExecutionValidationError,
    WorkflowImmutableError,
    WorkflowMilestoneNotFoundError,
)
from execution.models.dependency import ExecutionMilestoneDependency
from execution.models.milestone_definition import ExecutionMilestoneDefinition
from execution.models.template import lock_workflow_templates
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.permissions import check_workflow_management_authority


def add_milestone_definition(
    version: ExecutionWorkflowTemplateVersion,
    *,
    code: str,
    name_fa: str,
    name_en: str,
    sort_order: int,
    required: bool = True,
    blocking: bool = False,
    terminal: bool = False,
    expected_offset_days: Optional[int] = None,
    category: str = "",
    prerequisite_codes: Optional[List[str]] = None,
    actor: Any = None,
) -> ExecutionMilestoneDefinition:
    """
    Add a new milestone definition to a DRAFT workflow version.

    Forbidden on PUBLISHED or RETIRED versions.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()

        if version.status != WorkflowVersionStatus.DRAFT:
            raise WorkflowImmutableError(
                f"Cannot add milestones to a '{version.status}' workflow version; version is immutable."
            )

        milestone = ExecutionMilestoneDefinition(
            workflow_template_version=version,
            code=code,
            name_fa=name_fa,
            name_en=name_en,
            sort_order=sort_order,
            required=required,
            blocking=blocking,
            terminal=terminal,
            expected_offset_days=expected_offset_days,
            category=category,
        )
        milestone.save()

        if prerequisite_codes:
            for p_code in prerequisite_codes:
                try:
                    prereq = ExecutionMilestoneDefinition.objects.get(
                        workflow_template_version=version,
                        code=p_code,
                    )
                except ExecutionMilestoneDefinition.DoesNotExist:
                    raise WorkflowMilestoneNotFoundError(
                        f"Prerequisite milestone '{p_code}' not found in version."
                    )
                ExecutionMilestoneDependency.objects.create(
                    milestone=milestone,
                    prerequisite=prereq,
                )

        return milestone


def update_milestone_definition(
    milestone: ExecutionMilestoneDefinition,
    *,
    name_fa: Optional[str] = None,
    name_en: Optional[str] = None,
    sort_order: Optional[int] = None,
    required: Optional[bool] = None,
    blocking: Optional[bool] = None,
    terminal: Optional[bool] = None,
    expected_offset_days: Optional[int] = None,
    category: Optional[str] = None,
    prerequisite_codes: Optional[List[str]] = None,
    actor: Any = None,
) -> ExecutionMilestoneDefinition:
    """
    Update a milestone definition in a DRAFT workflow version.

    Code and parent version cannot be changed.
    Forbidden on PUBLISHED or RETIRED versions.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        version = milestone.workflow_template_version
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()
        milestone.refresh_from_db()

        if version.status != WorkflowVersionStatus.DRAFT:
            raise WorkflowImmutableError(
                f"Cannot modify milestones in a '{version.status}' workflow version; version is immutable."
            )

        if name_fa is not None:
            milestone.name_fa = name_fa
        if name_en is not None:
            milestone.name_en = name_en
        if sort_order is not None:
            milestone.sort_order = sort_order
        if required is not None:
            milestone.required = required
        if blocking is not None:
            milestone.blocking = blocking
        if terminal is not None:
            milestone.terminal = terminal
        if expected_offset_days is not None:
            milestone.expected_offset_days = expected_offset_days
        if category is not None:
            milestone.category = category

        milestone.save()

        if prerequisite_codes is not None:
            # Replace prerequisite dependencies
            milestone.prerequisite_dependencies.all().delete()
            for p_code in prerequisite_codes:
                try:
                    prereq = ExecutionMilestoneDefinition.objects.get(
                        workflow_template_version=version,
                        code=p_code,
                    )
                except ExecutionMilestoneDefinition.DoesNotExist:
                    raise WorkflowMilestoneNotFoundError(
                        f"Prerequisite milestone '{p_code}' not found in version."
                    )
                ExecutionMilestoneDependency.objects.create(
                    milestone=milestone,
                    prerequisite=prereq,
                )

        return milestone


def delete_milestone_definition(
    milestone: ExecutionMilestoneDefinition,
    *,
    actor: Any = None,
) -> None:
    """
    Delete a milestone definition from a DRAFT workflow version.

    Forbidden on PUBLISHED or RETIRED versions.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        version = milestone.workflow_template_version
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()

        if version.status != WorkflowVersionStatus.DRAFT:
            raise WorkflowImmutableError(
                f"Cannot delete milestones from a '{version.status}' workflow version; version is immutable."
            )

        milestone.delete()


def add_milestone_dependency(
    milestone: ExecutionMilestoneDefinition,
    prerequisite: ExecutionMilestoneDefinition,
    *,
    actor: Any = None,
) -> ExecutionMilestoneDependency:
    """
    Create a prerequisite relationship between two milestones in a DRAFT version.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        version = milestone.workflow_template_version
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()

        if version.status != WorkflowVersionStatus.DRAFT:
            raise WorkflowImmutableError(
                f"Cannot add dependencies in a '{version.status}' workflow version; version is immutable."
            )

        if milestone.workflow_template_version_id != prerequisite.workflow_template_version_id:
            raise ExecutionValidationError("Prerequisites must belong to the exact same workflow template version.")

        if milestone.id == prerequisite.id:
            raise ExecutionValidationError("A milestone cannot depend on itself.")

        dep, _ = ExecutionMilestoneDependency.objects.get_or_create(
            milestone=milestone,
            prerequisite=prerequisite,
        )
        return dep
