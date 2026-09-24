import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from execution.enums import IssueSeverity, IssueStatus, IssueType


class ExecutionIssue(models.Model):
    """
    Execution Issue Entity (Epic 10 Contract §65–§74, T1008).

    Represents an operational problem, defect, or variance occurring within an Execution instance.
    Issues provide explicit lifecycle tracking, optimistic concurrency control, and optional
    blocking semantics that govern execution closure.

    Invariants:
    - 1 Execution -> 0..N ExecutionIssue records.
    - Exact types: QUALITY, QUANTITY, LOGISTICS, PAYMENT, DOCUMENT, CONTRACT, OTHER.
    - Exact statuses: OPEN, IN_PROGRESS, RESOLVED, CANCELLED.
    - Optional exact severities: LOW, MEDIUM, HIGH, CRITICAL.
    - Explicit blocking: Blocking must come ONLY from persisted blocks_execution=True.
      Never infer blocks_execution from severity or type alone.
    - Server derives opened_by and opened_at; client cannot forge them.
    - Server derives resolved_by and resolved_at; client cannot forge them.
    - Resolution metadata must be strictly absent for OPEN and IN_PROGRESS statuses.
    - Resolution metadata is required when status is RESOLVED.
    - Historical evidence stability: No normal customer hard-delete API.
    - Terminal statuses (RESOLVED, CANCELLED) cannot be casually reopened or mutated.
    - Optimistic concurrency: mutations check expected_version and increment version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="issues",
        help_text="Parent execution instance.",
    )
    type = models.CharField(
        max_length=50,
        choices=IssueType.choices,
        db_index=True,
        help_text="Exact operational issue category.",
    )
    status = models.CharField(
        max_length=50,
        choices=IssueStatus.choices,
        default=IssueStatus.OPEN,
        db_index=True,
        help_text="Lifecycle status: OPEN, IN_PROGRESS, RESOLVED, CANCELLED.",
    )
    severity = models.CharField(
        max_length=50,
        choices=IssueSeverity.choices,
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional severity: LOW, MEDIUM, HIGH, CRITICAL.",
    )
    title = models.CharField(
        max_length=255,
        help_text="Concise title summarizing the operational issue.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Detailed operational description or context.",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_execution_issues",
        help_text="User who reported/opened this issue.",
    )
    opened_at = models.DateTimeField(
        default=timezone.now,
        help_text="Authoritative server timestamp when issue was opened.",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_execution_issues",
        help_text="User who authoritatively resolved this issue.",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when issue was marked RESOLVED.",
    )
    resolution_notes = models.TextField(
        blank=True,
        default="",
        help_text="Detailed notes explaining the resolution.",
    )
    blocks_execution = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this issue explicitly prevents execution closure while active.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency control version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Execution Issue"
        verbose_name_plural = "Execution Issues"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type__in=IssueType.values),
                name="check_valid_execution_issue_type",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=IssueStatus.values),
                name="check_valid_execution_issue_status",
            ),
            models.CheckConstraint(
                condition=models.Q(severity__isnull=True) | models.Q(severity__in=IssueSeverity.values),
                name="check_valid_execution_issue_severity",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(status=IssueStatus.RESOLVED) & models.Q(resolved_at__isnull=False))
                    | ~models.Q(status=IssueStatus.RESOLVED)
                ),
                name="check_resolved_issue_has_resolved_at",
            ),
            models.CheckConstraint(
                condition=(
                    (~models.Q(status__in=[IssueStatus.OPEN, IssueStatus.IN_PROGRESS]))
                    | (
                        models.Q(status__in=[IssueStatus.OPEN, IssueStatus.IN_PROGRESS])
                        & models.Q(resolved_at__isnull=True)
                        & models.Q(resolved_by__isnull=True)
                    )
                ),
                name="check_unresolved_issue_has_no_resolution_metadata",
            ),
        ]

    @property
    def is_active_blocker(self) -> bool:
        """
        Determine if issue actively blocks execution closing.

        Invariants:
        - Only issues with blocks_execution=True AND status in {OPEN, IN_PROGRESS} are active blockers.
        - RESOLVED or CANCELLED issues never block execution closure.
        """
        return bool(self.blocks_execution and self.status in {IssueStatus.OPEN, IssueStatus.IN_PROGRESS})

    def clean(self) -> None:
        super().clean()

        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Issue title cannot be empty."})

        if self.type not in IssueType.values:
            raise ValidationError({"type": f"Invalid issue type '{self.type}'."})

        if self.status not in IssueStatus.values:
            raise ValidationError({"status": f"Invalid issue status '{self.status}'."})

        if self.severity is not None and self.severity not in IssueSeverity.values:
            raise ValidationError({"severity": f"Invalid issue severity '{self.severity}'."})

        if self.status == IssueStatus.RESOLVED:
            if not self.resolved_at:
                raise ValidationError({"resolved_at": "Resolved issues must have resolved_at timestamp."})
        elif self.status in {IssueStatus.OPEN, IssueStatus.IN_PROGRESS}:
            if self.resolved_at or self.resolved_by_id:
                raise ValidationError({"resolved_at": "Open or in-progress issues cannot have resolution metadata."})
        elif self.status == IssueStatus.CANCELLED:
            if self.resolved_at or self.resolved_by_id:
                raise ValidationError({"resolved_at": "Cancelled issues cannot have resolution metadata."})

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"ExecutionIssue({self.id}, {self.type}, {self.status}, blocking={self.blocks_execution})"
