from typing import Union
from uuid import UUID

from execution.enums import WorkflowVersionStatus
from execution.exceptions import (
    NoActiveWorkflowVersionError,
    WorkflowTemplateInactiveError,
)
from execution.models.template import ExecutionWorkflowTemplate
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.services.template_service import get_workflow_template


def get_active_workflow_template_version(
    template_or_code: Union[str, UUID, ExecutionWorkflowTemplate],
) -> ExecutionWorkflowTemplateVersion:
    """
    Deterministically resolve the currently active published workflow template version.

    Invariants (Epic 10 Contract §11, §20):
    - Template must exist and have is_active=True.
    - Template must have an active_version set.
    - The active_version must have status=PUBLISHED.
    - RETIRED and DRAFT versions NEVER resolve as active.
    - Never infers active version from arbitrary row ordering or timestamps.
    """
    if isinstance(template_or_code, ExecutionWorkflowTemplate):
        template = ExecutionWorkflowTemplate.objects.select_related("active_version").get(pk=template_or_code.pk)
    else:
        template = get_workflow_template(template_or_code)
        template.refresh_from_db()

    if not template.is_active:
        raise WorkflowTemplateInactiveError(f"Workflow template '{template.code}' is inactive.")

    if not template.active_version_id:
        raise NoActiveWorkflowVersionError(
            f"Workflow template '{template.code}' has no active workflow version."
        )

    active_version = template.active_version
    if active_version.status != WorkflowVersionStatus.PUBLISHED:
        raise NoActiveWorkflowVersionError(
            f"Active version for template '{template.code}' is '{active_version.status}'; only PUBLISHED versions can be active."
        )

    return active_version
