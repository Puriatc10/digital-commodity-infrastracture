import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import MilestoneStatus


class ExecutionMilestone(models.Model):
    """
    Execution Milestone Instance (Epic 10 Contract §15, §16, §17, T1003).

    Materialized milestone instance representing operational progress against a definition
    from the Execution's bound workflow template version.

    Invariants:
    - Exactly one instance per (execution, definition) pair.
    - Materialized definitions must belong strictly to the execution's bound workflow version.
    - Completed milestones are authoritative historical facts; ordinary mutation of actual_at,
      completed_by, recorded_at, and completion status is strictly rejected (no reopen).
    - Transitions are guarded by optimistic concurrency (expected_version).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="milestones",
        help_text="Parent execution instance.",
    )
    definition = models.ForeignKey(
        "execution.ExecutionMilestoneDefinition",
        on_delete=models.PROTECT,
        related_name="instances",
        help_text="Milestone definition from the bound workflow template version.",
    )
    status = models.CharField(
        max_length=20,
        choices=MilestoneStatus.choices,
        default=MilestoneStatus.PENDING,
        db_index=True,
        help_text="Runtime status of this milestone instance.",
    )
    expected_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Target expected completion date/time.",
    )
    actual_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual historical occurrence timestamp.",
    )
    recorded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when milestone completion was recorded.",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="User who authoritatively recorded completion.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Operational notes or transition reasons.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency version counter.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["execution", "definition__sort_order", "created_at"]
        verbose_name = "Execution Milestone"
        verbose_name_plural = "Execution Milestones"
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "definition"],
                name="unique_execution_milestone_definition",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        MilestoneStatus.PENDING,
                        MilestoneStatus.IN_PROGRESS,
                        MilestoneStatus.COMPLETED,
                        MilestoneStatus.BLOCKED,
                        MilestoneStatus.SKIPPED,
                    ]
                ),
                name="check_valid_milestone_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_milestone_version",
            ),
        ]
        indexes = [
            models.Index(fields=["execution", "status"], name="idx_exec_milestone_status"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        # Bound version integrity check
        if self.execution_id and self.definition_id:
            execution = getattr(self, "execution", None)
            definition = getattr(self, "definition", None)
            if execution and definition:
                if definition.workflow_template_version_id != execution.workflow_template_version_id:
                    errors["definition"] = (
                        "Milestone definition must belong to the exact workflow template version "
                        "bound to the execution aggregate."
                    )

        if not self._state.adding:
            orig = ExecutionMilestone.objects.filter(pk=self.pk).first()
            if orig:
                if orig.execution_id != self.execution_id:
                    errors["execution"] = "Execution milestone execution reference is immutable."
                if orig.definition_id != self.definition_id:
                    errors["definition"] = "Execution milestone definition reference is immutable."

                # Immutability of completed milestone facts (Contract §17)
                if orig.status == MilestoneStatus.COMPLETED:
                    if self.status != MilestoneStatus.COMPLETED:
                        errors["status"] = (
                            "Completed milestones cannot be reopened or transitioned to another status."
                        )
                    if orig.actual_at != self.actual_at:
                        errors["actual_at"] = "Completed milestone actual_at is immutable."
                    if orig.completed_by_id != self.completed_by_id:
                        errors["completed_by"] = "Completed milestone completed_by is immutable."
                    if orig.recorded_at != self.recorded_at:
                        errors["recorded_at"] = "Completed milestone recorded_at is immutable."

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        code = getattr(getattr(self, "definition", None), "code", "UNKNOWN")
        return f"Milestone {code} ({self.status}) for Execution {self.execution_id}"
