import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction


def lock_workflow_templates(ids):
    """Serialize workflow template mutations with select_for_update."""
    valid_ids = [i for i in ids if i]
    if not valid_ids:
        return
    list(ExecutionWorkflowTemplate.objects.select_for_update().filter(pk__in=valid_ids).order_by("pk"))


class ExecutionWorkflowTemplate(models.Model):
    """
    Workflow Template Aggregate Root (Epic 10 Contract §9).

    Represents durable business workflow identity (e.g., standard physical delivery).
    Maintains a machine-readable unique code and tracks the active published version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Canonical lowercase machine code (e.g. bitumen_standard)",
    )
    name_fa = models.CharField(max_length=255, help_text="Persian name")
    name_en = models.CharField(max_length=255, help_text="English name")
    description = models.TextField(blank=True, default="", help_text="Detailed workflow description")
    is_active = models.BooleanField(default=True, help_text="Whether this template is active for new executions")

    # Currently active published version
    active_version = models.ForeignKey(
        "ExecutionWorkflowTemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The currently active published version for new execution instances.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if not self.code or not re.fullmatch(r"[a-z][a-z0-9_-]*", self.code):
            raise ValidationError({"code": "Workflow template code must be lowercase alphanumeric with underscores/hyphens."})
        original_code = (
            ExecutionWorkflowTemplate.objects.filter(pk=self.pk).values_list("code", flat=True).first()
        )
        if original_code is not None and original_code != self.code:
            raise ValidationError({"code": "Workflow template codes are immutable identifiers."})
        if self.active_version_id:
            from execution.enums import WorkflowVersionStatus
            from execution.models.version import ExecutionWorkflowTemplateVersion

            active = ExecutionWorkflowTemplateVersion.objects.filter(pk=self.active_version_id).first()
            if active:
                if active.template_id != self.id:
                    raise ValidationError({"active_version": "Active version must belong to the same template."})
                if active.status != WorkflowVersionStatus.PUBLISHED:
                    raise ValidationError({"active_version": "Only a published workflow version can be active."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        lock_workflow_templates([self.pk])
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from execution.enums import WorkflowVersionStatus
        if self.versions.filter(status__in=[WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]).exists():
            raise ValidationError("Cannot delete a workflow template with published or retired versions.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.name_en} ({self.code})"
