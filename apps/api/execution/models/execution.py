import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from execution.enums import ExecutionStatus, WorkflowVersionStatus


def lock_executions(ids):
    """Serialize execution mutations with select_for_update ordered by pk."""
    valid_ids = [i for i in ids if i]
    if not valid_ids:
        return
    list(Execution.objects.select_for_update().filter(pk__in=valid_ids).order_by("pk"))


class Execution(models.Model):
    """
    Execution Aggregate Root (Epic 10 Contract §4, §5, §6, §8, T1003).

    Represents operational progress and lifecycle monitoring for an immutable Deal.

    Invariants:
    - 1 Deal -> exactly 1 Execution (enforced via OneToOneField & DB unique constraint).
    - Status is strictly OPEN or CLOSED; no milestone names duplicated in Execution.status.
    - Bound workflow_template_version is strictly immutable once bound at creation.
    - An Execution never rebinds to newer or retired workflow template versions.
    - Deal commercial truth is never mutated by operational execution updates.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deal = models.OneToOneField(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="execution",
        help_text="Authoritative source Deal aggregate (1 Deal -> exactly 1 Execution).",
    )
    workflow_template_version = models.ForeignKey(
        "execution.ExecutionWorkflowTemplateVersion",
        on_delete=models.PROTECT,
        related_name="executions",
        help_text="Immutable workflow template version bound at creation time.",
    )
    status = models.CharField(
        max_length=20,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.OPEN,
        db_index=True,
        help_text="Execution operational lifecycle status (OPEN or CLOSED).",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when execution monitoring started.",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when execution reached CLOSED status.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Execution"
        verbose_name_plural = "Executions"
        constraints = [
            models.UniqueConstraint(
                fields=["deal"],
                name="unique_execution_deal",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[ExecutionStatus.OPEN, ExecutionStatus.CLOSED]),
                name="check_valid_execution_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_execution_version",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="idx_exec_status_created"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        if self._state.adding:
            # Creation rules
            if self.workflow_template_version_id:
                version = getattr(self, "workflow_template_version", None)
                if version and version.status != WorkflowVersionStatus.PUBLISHED:
                    errors["workflow_template_version"] = (
                        f"Cannot bind execution to workflow version in '{version.status}' status. "
                        "Only PUBLISHED workflow versions can be used for new executions."
                    )
        else:
            # Immutability & transition rules on update
            orig = Execution.objects.filter(pk=self.pk).first()
            if orig:
                if orig.deal_id != self.deal_id:
                    errors["deal"] = "Execution deal is immutable."
                if orig.workflow_template_version_id != self.workflow_template_version_id:
                    errors["workflow_template_version"] = "Execution workflow_template_version is immutable."

                if orig.status == ExecutionStatus.CLOSED:
                    if self.status != ExecutionStatus.CLOSED:
                        errors["status"] = "A closed execution cannot be reopened."

        if self.status == ExecutionStatus.CLOSED and not self.closed_at:
            errors["closed_at"] = "closed_at must be set when execution status is CLOSED."

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Execution {self.id} for Deal {self.deal_id} ({self.status})"
