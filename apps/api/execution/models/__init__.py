from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from execution.enums import WorkflowVersionStatus
from .dependency import ExecutionMilestoneDependency
from .milestone_definition import ExecutionMilestoneDefinition
from .template import ExecutionWorkflowTemplate, lock_workflow_templates
from .version import ExecutionWorkflowTemplateVersion


@receiver(pre_delete, sender=ExecutionWorkflowTemplate)
def protect_template_deletion(sender, instance, **kwargs):
    if instance.versions.filter(status__in=[WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]).exists():
        raise ValidationError("Cannot delete a workflow template with published or retired versions.")


@receiver(pre_delete, sender=ExecutionWorkflowTemplateVersion)
def protect_version_deletion(sender, instance, **kwargs):
    if instance.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
        raise ValidationError("Cannot delete published or retired workflow version history.")


@receiver(pre_delete, sender=ExecutionMilestoneDefinition)
def protect_milestone_deletion(sender, instance, **kwargs):
    version = getattr(instance, "workflow_template_version", None)
    if version and version.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
        raise ValidationError("Cannot delete milestones belonging to a published or retired workflow version.")


@receiver(pre_delete, sender=ExecutionMilestoneDependency)
def protect_dependency_deletion(sender, instance, **kwargs):
    milestone = getattr(instance, "milestone", None)
    if milestone:
        version = getattr(milestone, "workflow_template_version", None)
        if version and version.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
            raise ValidationError("Cannot delete dependencies belonging to a published or retired workflow version.")


__all__ = [
    "ExecutionWorkflowTemplate",
    "ExecutionWorkflowTemplateVersion",
    "ExecutionMilestoneDefinition",
    "ExecutionMilestoneDependency",
    "lock_workflow_templates",
]
