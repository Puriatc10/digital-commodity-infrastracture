import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import WorkflowVersionStatus


class ExecutionMilestoneDefinition(models.Model):
    """
    Execution Milestone Definition (Epic 10 Contract §13).

    Defines an operational milestone within an ExecutionWorkflowTemplateVersion.
    Code is the stable machine identity; labels are localized presentation metadata.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_template_version = models.ForeignKey(
        "ExecutionWorkflowTemplateVersion",
        on_delete=models.CASCADE,
        related_name="milestones",
        help_text="Parent workflow template version",
    )
    code = models.CharField(
        max_length=100,
        help_text="Canonical uppercase machine code (e.g. AWARDED, LOADING_SCHEDULED)",
    )
    name_fa = models.CharField(max_length=255, help_text="Persian display label")
    name_en = models.CharField(max_length=255, help_text="English display label")
    sort_order = models.PositiveIntegerField(
        help_text="Deterministic display and logical order within the version",
    )

    required = models.BooleanField(
        default=True,
        help_text="Whether this milestone is required for workflow completion",
    )
    blocking = models.BooleanField(
        default=False,
        help_text="Whether downstream milestones are blocked until this milestone is completed",
    )
    terminal = models.BooleanField(
        default=False,
        help_text="Whether completing this milestone marks the execution as CLOSED",
    )

    expected_offset_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Default expected offset days from execution start",
    )
    category = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Optional category (e.g. COMMERCIAL, LOGISTICS, QUALITY, PAYMENT, CLOSURE)",
    )

    prerequisites = models.ManyToManyField(
        "self",
        symmetrical=False,
        through="ExecutionMilestoneDependency",
        through_fields=("milestone", "prerequisite"),
        related_name="downstream_milestones",
        blank=True,
        help_text="Prerequisite milestones that must be completed before this milestone",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow_template_version", "code"],
                name="unique_version_milestone_code",
            ),
            models.UniqueConstraint(
                fields=["workflow_template_version", "sort_order"],
                name="unique_version_milestone_sort_order",
            ),
        ]
        ordering = ["workflow_template_version", "sort_order", "code"]

    def clean(self):
        super().clean()
        if not self.code or not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code):
            raise ValidationError({"code": "Milestone code must be canonical uppercase alphanumeric with underscores."})

        # Immutability check against parent version status
        version = getattr(self, "workflow_template_version", None)
        if version and version.status != WorkflowVersionStatus.DRAFT:
            raise ValidationError("Cannot add or modify milestone definitions in a published or retired workflow version.")

        if self.pk:
            orig = (
                ExecutionMilestoneDefinition.objects.filter(pk=self.pk)
                .select_related("workflow_template_version")
                .first()
            )
            if orig:
                if orig.workflow_template_version_id != self.workflow_template_version_id:
                    raise ValidationError({"workflow_template_version": "Cannot move milestone to a different workflow version."})
                if orig.workflow_template_version.status != WorkflowVersionStatus.DRAFT:
                    raise ValidationError("Cannot modify milestones belonging to a published or retired workflow version.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        from execution.models.template import lock_workflow_templates
        if self.workflow_template_version_id:
            version = self.workflow_template_version
            lock_workflow_templates([version.template_id])
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.workflow_template_version.status != WorkflowVersionStatus.DRAFT:
            raise ValidationError("Cannot delete milestone definitions from a published or retired workflow version.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.workflow_template_version} - {self.code}"
