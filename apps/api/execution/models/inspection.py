import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import InspectionResult, InspectionStatus


class ExecutionInspection(models.Model):
    """
    Execution Quality & Inspection Aggregate (Epic 10 Contract §43–§49, T1005).

    Represents authoritative operational quality inspection facts for an Execution instance.

    Invariants:
    - 1 Execution -> exactly 1 ExecutionInspection record (OneToOneField & unique DB constraint).
    - Commercial truth separation: DealTermsSnapshot and Deal specifications are NEVER mutated.
      ExecutionInspection records what actually happened operationally; discrepancies are historically valid.
    - Exact statuses: NOT_REQUIRED, PENDING, SCHEDULED, COMPLETED, CANCELLED.
    - Exact results: PASS, FAIL, CONDITIONAL, UNKNOWN.
    - Result is never inferred from notes or active schema.
    - Unknown result is preserved explicitly.
    - NOT_REQUIRED must never become a fake PASS.
    - Inconsistent states (e.g. PENDING + PASS, SCHEDULED + FAIL, NOT_REQUIRED + PASS) are strictly rejected.
    - Completion integrity: status = COMPLETED requires inspection_at to be present.
    - Completion immutability: completed inspection facts (status, inspection_at, result, agency) cannot be
      casually rewritten or reopened.
    - Cancelled immutability: cancelled inspections cannot be casually reopened.
    - Optimistic concurrency: mutations increment version and require expected_version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.OneToOneField(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="inspection",
        help_text="Parent execution instance (1 Execution -> max 1 ExecutionInspection).",
    )
    required = models.BooleanField(
        default=False,
        help_text="Whether quality inspection is required by commercial context.",
    )
    agency = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Inspection agency or organization name (e.g. SGS, Bureau Veritas).",
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled inspection timestamp.",
    )
    inspection_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative historical inspection occurrence timestamp.",
    )
    status = models.CharField(
        max_length=20,
        choices=InspectionStatus.choices,
        default=InspectionStatus.PENDING,
        db_index=True,
        help_text="Runtime status of this inspection record.",
    )
    result = models.CharField(
        max_length=20,
        choices=InspectionResult.choices,
        default=InspectionResult.UNKNOWN,
        help_text="Authoritative quality inspection result (PASS, FAIL, CONDITIONAL, UNKNOWN).",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Operational notes or instructions. Must never be used to infer result or status.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Execution Inspection"
        verbose_name_plural = "Execution Inspections"
        constraints = [
            models.UniqueConstraint(
                fields=["execution"],
                name="unique_execution_inspection",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=InspectionStatus.values),
                name="check_valid_inspection_status",
            ),
            models.CheckConstraint(
                condition=models.Q(result__in=InspectionResult.values),
                name="check_valid_inspection_result",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_inspection_version",
            ),
        ]
        indexes = [
            models.Index(fields=["execution", "-created_at"], name="idx_exec_inspection_created"),
            models.Index(fields=["execution", "status"], name="idx_exec_inspection_status"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        # Immutability of execution reference
        if not self._state.adding:
            orig = ExecutionInspection.objects.filter(pk=self.pk).first()
            if orig and orig.execution_id != self.execution_id:
                errors["execution"] = "Execution inspection execution reference is immutable."

            # Completion immutability (Contract §44, §45, T1005)
            if orig and orig.status == InspectionStatus.COMPLETED:
                if self.status != InspectionStatus.COMPLETED:
                    errors["status"] = (
                        "Completed inspections cannot be reopened or transitioned to another status."
                    )
                if orig.inspection_at != self.inspection_at:
                    errors["inspection_at"] = "Completed inspection timestamp (inspection_at) is immutable."
                if orig.result != self.result:
                    errors["result"] = "Completed inspection result is immutable."
                if orig.agency and self.agency != orig.agency:
                    errors["agency"] = "Completed inspection agency is immutable."

            # Cancellation immutability
            if orig and orig.status == InspectionStatus.CANCELLED:
                if self.status != InspectionStatus.CANCELLED:
                    errors["status"] = (
                        "Cancelled inspections cannot be casually reopened or transitioned to another status."
                    )

        # Status and result validity
        if self.status not in InspectionStatus.values:
            errors["status"] = f"Invalid inspection status '{self.status}'."

        if self.result not in InspectionResult.values:
            errors["result"] = f"Invalid inspection result '{self.result}'."

        # State validation: Inconsistent combinations
        # Non-completed inspections must retain UNKNOWN result
        if self.status != InspectionStatus.COMPLETED and self.result != InspectionResult.UNKNOWN:
            errors["result"] = (
                f"Inspection result must remain UNKNOWN when status is '{self.status}'. "
                "Result cannot be determined prior to completion."
            )

        # NOT_REQUIRED must never become a fake PASS
        if self.status == InspectionStatus.NOT_REQUIRED and self.result != InspectionResult.UNKNOWN:
            errors["result"] = "Inspection result must be UNKNOWN when status is NOT_REQUIRED."

        # Completion integrity: status = COMPLETED requires inspection_at and a valid result
        if self.status == InspectionStatus.COMPLETED:
            if not self.inspection_at:
                errors["inspection_at"] = "inspection_at is mandatory when status is COMPLETED."
            if self.result not in InspectionResult.values:
                errors["result"] = "A valid inspection result is required when status is COMPLETED."

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"Inspection for Execution {self.execution_id} "
            f"(status={self.status}, result={self.result}, v={self.version})"
        )
