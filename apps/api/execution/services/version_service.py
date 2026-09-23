from typing import Any, Optional
from uuid import UUID

from django.db import models, transaction
from django.utils import timezone

from execution.enums import WorkflowVersionStatus
from execution.exceptions import (
    ExecutionValidationError,
    WorkflowLifecycleError,
    WorkflowVersionNotFoundError,
)
from execution.models.dependency import ExecutionMilestoneDependency
from execution.models.milestone_definition import ExecutionMilestoneDefinition
from execution.models.template import ExecutionWorkflowTemplate, lock_workflow_templates
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.permissions import check_workflow_management_authority
from execution.services.validation_service import validate_version_for_publish


def create_draft_version(
    template: ExecutionWorkflowTemplate,
    *,
    actor: Any = None,
    base_version: Optional[ExecutionWorkflowTemplateVersion] = None,
    change_summary: str = "",
) -> ExecutionWorkflowTemplateVersion:
    """
    Create a new DRAFT workflow version for a template.

    Monotonically allocates version_number under select_for_update lock.
    Optionally clones milestones and dependencies from a base_version.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([template.pk])
        template.refresh_from_db()

        max_ver = (
            ExecutionWorkflowTemplateVersion.objects.filter(template=template)
            .aggregate(max_v=models.Max("version_number"))["max_v"]
            or 0
        )
        new_version_number = max_ver + 1

        new_version = ExecutionWorkflowTemplateVersion(
            template=template,
            version_number=new_version_number,
            status=WorkflowVersionStatus.DRAFT,
            change_summary=change_summary,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        new_version.save()

        # If base version is supplied, clone its milestones and prerequisite dependencies
        if base_version:
            if base_version.template_id != template.id:
                raise ExecutionValidationError("Base version must belong to the same workflow template.")

            old_milestones = list(
                ExecutionMilestoneDefinition.objects.filter(workflow_template_version=base_version)
                .prefetch_related("prerequisite_dependencies")
                .order_by("sort_order")
            )
            # Map old milestone ID -> new milestone definition
            id_map = {}
            for om in old_milestones:
                nm = ExecutionMilestoneDefinition.objects.create(
                    workflow_template_version=new_version,
                    code=om.code,
                    name_fa=om.name_fa,
                    name_en=om.name_en,
                    sort_order=om.sort_order,
                    required=om.required,
                    blocking=om.blocking,
                    terminal=om.terminal,
                    expected_offset_days=om.expected_offset_days,
                    category=om.category,
                )
                id_map[om.id] = nm

            # Clone dependencies
            for om in old_milestones:
                for dep in om.prerequisite_dependencies.all():
                    ExecutionMilestoneDependency.objects.create(
                        milestone=id_map[om.id],
                        prerequisite=id_map[dep.prerequisite_id],
                    )

        return new_version


def publish_version(
    version: ExecutionWorkflowTemplateVersion,
    *,
    actor: Any = None,
    set_active: bool = True,
) -> ExecutionWorkflowTemplateVersion:
    """
    Publish a DRAFT workflow version.

    Validates DAG acyclicity, code uniqueness, and terminal milestone invariants.
    Freezes version graph into immutable PUBLISHED state.
    Optionally marks the version as the template's active_version.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()
        template = ExecutionWorkflowTemplate.objects.select_for_update().get(pk=version.template_id)

        if version.status != WorkflowVersionStatus.DRAFT:
            raise WorkflowLifecycleError(
                f"Cannot publish version in '{version.status}' status; only DRAFT versions can be published."
            )

        # Validate graph & semantic invariants
        validate_version_for_publish(version)

        version.status = WorkflowVersionStatus.PUBLISHED
        version.published_at = timezone.now()
        version.published_by = actor if getattr(actor, "is_authenticated", False) else None
        version.save()

        if set_active:
            template.active_version = version
            template.save()

        return version


def retire_version(
    version: ExecutionWorkflowTemplateVersion,
    *,
    actor: Any = None,
) -> ExecutionWorkflowTemplateVersion:
    """
    Transition a PUBLISHED workflow version into RETIRED.

    Retired versions are immutable and historical.
    Active published version cannot be retired without first activating another version or deactivating template.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()
        template = ExecutionWorkflowTemplate.objects.select_for_update().get(pk=version.template_id)

        if version.status == WorkflowVersionStatus.DRAFT:
            raise WorkflowLifecycleError("Draft workflow versions cannot be retired directly.")
        if version.status == WorkflowVersionStatus.RETIRED:
            raise WorkflowLifecycleError("Workflow version is already retired.")

        # Invariant: active published version cannot be retired while still designated active
        if template.active_version_id == version.id:
            raise ExecutionValidationError(
                "Cannot retire the currently active workflow version. Activate another published version first or clear the active version."
            )

        version.status = WorkflowVersionStatus.RETIRED
        version.retired_at = timezone.now()
        version.retired_by = actor if getattr(actor, "is_authenticated", False) else None
        version.save()

        return version


def activate_version(
    version: ExecutionWorkflowTemplateVersion,
    *,
    actor: Any = None,
) -> ExecutionWorkflowTemplateVersion:
    """
    Designate a PUBLISHED workflow version as the active version of its template.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([version.template_id])
        version.refresh_from_db()
        template = ExecutionWorkflowTemplate.objects.select_for_update().get(pk=version.template_id)

        if version.status != WorkflowVersionStatus.PUBLISHED:
            raise ExecutionValidationError(
                f"Cannot activate workflow version in '{version.status}' status; only PUBLISHED versions can be active."
            )

        template.active_version = version
        template.save()
        return version


def get_workflow_version(version_id: UUID) -> ExecutionWorkflowTemplateVersion:
    """Retrieve workflow version by ID."""
    try:
        return ExecutionWorkflowTemplateVersion.objects.select_related("template").get(pk=version_id)
    except ExecutionWorkflowTemplateVersion.DoesNotExist:
        raise WorkflowVersionNotFoundError(f"Workflow template version '{version_id}' does not exist.")
