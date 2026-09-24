import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import WorkflowVersionStatus


class ExecutionMilestoneDependency(models.Model):
    """
    Milestone Prerequisite Dependency (Epic 10 Contract §14).

    Explicit join table modeling prerequisite requirements between milestone definitions.
    Enforces same-version scope, no self-dependency, and published/retired immutability.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        "ExecutionMilestoneDefinition",
        on_delete=models.CASCADE,
        related_name="prerequisite_dependencies",
        help_text="The milestone that requires the prerequisite",
    )
    prerequisite = models.ForeignKey(
        "ExecutionMilestoneDefinition",
        on_delete=models.CASCADE,
        related_name="downstream_dependencies",
        help_text="The prerequisite milestone that must precede",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["milestone", "prerequisite"],
                name="unique_milestone_dependency",
            ),
            models.CheckConstraint(
                condition=~models.Q(milestone=models.F("prerequisite")),
                name="check_no_self_dependency",
            ),
        ]

    def clean(self):
        super().clean()
        if self.milestone_id and self.prerequisite_id:
            if self.milestone_id == self.prerequisite_id:
                raise ValidationError({"prerequisite": "A milestone cannot depend on itself."})

            m = getattr(self, "milestone", None)
            p = getattr(self, "prerequisite", None)
            if m and p:
                if m.workflow_template_version_id != p.workflow_template_version_id:
                    raise ValidationError(
                        {"prerequisite": "Prerequisites must belong to the exact same workflow template version."}
                    )
                if m.workflow_template_version.status != WorkflowVersionStatus.DRAFT:
                    raise ValidationError(
                        "Cannot add or modify dependencies in a published or retired workflow version."
                    )

    @transaction.atomic
    def save(self, *args, **kwargs):
        from execution.models.template import lock_workflow_templates
        if self.milestone_id:
            version = self.milestone.workflow_template_version
            lock_workflow_templates([version.template_id])
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.milestone.workflow_template_version.status != WorkflowVersionStatus.DRAFT:
            raise ValidationError(
                "Cannot delete dependencies from a published or retired workflow version."
            )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.milestone.code} requires {self.prerequisite.code}"
