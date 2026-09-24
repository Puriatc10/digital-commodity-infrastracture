from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from execution.enums import WorkflowVersionStatus
from .dependency import ExecutionMilestoneDependency
from .document import ExecutionDocument
from .execution import Execution, lock_executions
from .inspection import ExecutionInspection
from .issue import ExecutionIssue
from .logistics import ExecutionLogistics
from .milestone import ExecutionMilestone
from .milestone_definition import ExecutionMilestoneDefinition
from .payment import ExecutionPayment
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
    if instance.executions.exists():
        raise ValidationError("Cannot delete workflow versions bound to existing execution instances.")


@receiver(pre_delete, sender=ExecutionMilestoneDefinition)
def protect_milestone_deletion(sender, instance, **kwargs):
    version = getattr(instance, "workflow_template_version", None)
    if version and version.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
        raise ValidationError("Cannot delete milestones belonging to a published or retired workflow version.")
    if instance.instances.exists():
        raise ValidationError("Cannot delete milestone definitions referenced by runtime milestone instances.")


@receiver(pre_delete, sender=ExecutionMilestoneDependency)
def protect_dependency_deletion(sender, instance, **kwargs):
    milestone = getattr(instance, "milestone", None)
    if milestone:
        version = getattr(milestone, "workflow_template_version", None)
        if version and version.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
            raise ValidationError("Cannot delete dependencies belonging to a published or retired workflow version.")


@receiver(pre_delete, sender=Execution)
def protect_execution_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution aggregates represent historical operational audit trails and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionMilestone)
def protect_execution_milestone_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution milestones represent historical operational facts and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionLogistics)
def protect_execution_logistics_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution logistics represent historical operational facts and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionInspection)
def protect_execution_inspection_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution inspection records represent historical operational facts and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionPayment)
def protect_execution_payment_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution payment records represent historical operational facts and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionDocument)
def protect_execution_document_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution documents represent historical operational evidence and cannot be deleted.")


@receiver(pre_delete, sender=ExecutionIssue)
def protect_execution_issue_deletion(sender, instance, **kwargs):
    raise ValidationError("Execution issues represent historical operational records and cannot be deleted.")


__all__ = [
    "ExecutionWorkflowTemplate",
    "ExecutionWorkflowTemplateVersion",
    "ExecutionMilestoneDefinition",
    "ExecutionMilestoneDependency",
    "Execution",
    "ExecutionMilestone",
    "ExecutionLogistics",
    "ExecutionInspection",
    "ExecutionPayment",
    "ExecutionDocument",
    "ExecutionIssue",
    "lock_workflow_templates",
    "lock_executions",
]


