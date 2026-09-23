import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import WorkflowVersionStatus


class ExecutionWorkflowTemplateVersion(models.Model):
    """
    Workflow Template Version (Epic 10 Contract §9, §10, §11).

    Represents an immutable semantic workflow version.
    Lifecycle:
        DRAFT -> PUBLISHED -> RETIRED
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        "ExecutionWorkflowTemplate",
        on_delete=models.CASCADE,
        related_name="versions",
        help_text="Parent workflow template",
    )
    version_number = models.PositiveIntegerField(help_text="Monotonically increasing version number within the template")
    status = models.CharField(
        max_length=20,
        choices=WorkflowVersionStatus.choices,
        default=WorkflowVersionStatus.DRAFT,
        db_index=True,
    )
    change_summary = models.TextField(blank=True, default="", help_text="Summary of changes in this version")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Internal user who created this draft version",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version_number"],
                name="unique_workflow_template_version_number",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[
                    WorkflowVersionStatus.DRAFT,
                    WorkflowVersionStatus.PUBLISHED,
                    WorkflowVersionStatus.RETIRED,
                ]),
                name="check_valid_workflow_version_status",
            ),
        ]
        ordering = ["template", "version_number"]

    @property
    def is_active(self) -> bool:
        """Check if this version is the currently active version of its template."""
        return self.template.active_version_id == self.id

    def clean(self):
        super().clean()
        if self._state.adding and self.status == WorkflowVersionStatus.RETIRED:
            raise ValidationError({"status": "New workflow versions cannot start in RETIRED status."})

        if self.pk:
            try:
                orig = ExecutionWorkflowTemplateVersion.objects.get(pk=self.pk)
                # Template and version_number immutability
                if orig.template_id != self.template_id:
                    raise ValidationError({"template": "Cannot change the template of an existing version."})
                if orig.version_number != self.version_number:
                    raise ValidationError({"version_number": "Cannot change the version number of an existing version."})

                # Status transition rules
                if orig.status == WorkflowVersionStatus.DRAFT:
                    if self.status == WorkflowVersionStatus.RETIRED:
                        raise ValidationError({"status": "Draft versions must be published before retirement."})
                elif orig.status == WorkflowVersionStatus.PUBLISHED:
                    if self.status == WorkflowVersionStatus.DRAFT:
                        raise ValidationError({"status": "Cannot revert a published workflow version to draft."})
                    if self.status == WorkflowVersionStatus.PUBLISHED:
                        # Published version fields immutability
                        if orig.change_summary != self.change_summary:
                            raise ValidationError("Cannot modify change summary of a published workflow version.")
                    elif self.status == WorkflowVersionStatus.RETIRED:
                        # Check if retiring active version
                        from execution.models.template import ExecutionWorkflowTemplate
                        if ExecutionWorkflowTemplate.objects.filter(pk=self.template_id, active_version_id=self.pk).exists():
                            raise ValidationError({"status": "Cannot retire the currently active workflow version. Change or clear the active version first."})
                elif orig.status == WorkflowVersionStatus.RETIRED:
                    if self.status != WorkflowVersionStatus.RETIRED:
                        raise ValidationError({"status": "Retired workflow version cannot change status."})
                    if orig.change_summary != self.change_summary:
                        raise ValidationError("Cannot modify a retired workflow version.")
            except ExecutionWorkflowTemplateVersion.DoesNotExist:
                pass

    @transaction.atomic
    def save(self, *args, **kwargs):
        original = ExecutionWorkflowTemplateVersion.objects.filter(pk=self.pk).first()
        from execution.models.template import lock_workflow_templates
        lock_workflow_templates([self.template_id] + ([original.template_id] if original else []))
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in [WorkflowVersionStatus.PUBLISHED, WorkflowVersionStatus.RETIRED]:
            raise ValidationError("Cannot delete published or retired workflow version history.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.template.code} v{self.version_number} ({self.get_status_display()})"
