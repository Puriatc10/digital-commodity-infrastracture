from typing import Any, Optional, Union
from uuid import UUID

from django.db import transaction

from execution.exceptions import (
    WorkflowTemplateNotFoundError,
)
from execution.models.template import ExecutionWorkflowTemplate, lock_workflow_templates
from execution.permissions import check_workflow_management_authority


def create_workflow_template(
    *,
    code: str,
    name_fa: str,
    name_en: str,
    description: str = "",
    actor: Any = None,
) -> ExecutionWorkflowTemplate:
    """
    Create a new ExecutionWorkflowTemplate identity.

    Internal operation restricted to Platform Operators and Product Admins.
    """
    check_workflow_management_authority(actor)

    template = ExecutionWorkflowTemplate(
        code=code,
        name_fa=name_fa,
        name_en=name_en,
        description=description,
        is_active=True,
    )
    template.save()
    return template


def update_workflow_template(
    template: ExecutionWorkflowTemplate,
    *,
    name_fa: Optional[str] = None,
    name_en: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    actor: Any = None,
) -> ExecutionWorkflowTemplate:
    """
    Update metadata of an existing ExecutionWorkflowTemplate.

    Code is immutable and cannot be updated.
    Internal operation restricted to Platform Operators and Product Admins.
    """
    check_workflow_management_authority(actor)

    with transaction.atomic():
        lock_workflow_templates([template.pk])
        template.refresh_from_db()

        if name_fa is not None:
            template.name_fa = name_fa
        if name_en is not None:
            template.name_en = name_en
        if description is not None:
            template.description = description
        if is_active is not None:
            template.is_active = is_active

        template.save()
        return template


def get_workflow_template(code_or_id: Union[str, UUID]) -> ExecutionWorkflowTemplate:
    """Resolve workflow template by UUID or code."""
    try:
        if isinstance(code_or_id, UUID):
            return ExecutionWorkflowTemplate.objects.get(pk=code_or_id)
        # Try UUID string first
        try:
            val = UUID(str(code_or_id))
            return ExecutionWorkflowTemplate.objects.get(pk=val)
        except (ValueError, AttributeError):
            return ExecutionWorkflowTemplate.objects.get(code=str(code_or_id))
    except ExecutionWorkflowTemplate.DoesNotExist:
        raise WorkflowTemplateNotFoundError(f"Workflow template '{code_or_id}' does not exist.")
