import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from execution.enums import ExecutionDocumentCategory


class ExecutionDocument(models.Model):
    """
    Execution Document Evidence (Epic 10 Contract §60–§64, T1007).

    Represents authoritative operational evidence associated with an Execution instance,
    and optionally contextualized by milestone or quality inspection.

    Invariants:
    - 1 Execution -> 0..N ExecutionDocument records.
    - PostgreSQL stores metadata only; file bytes reside strictly in object storage.
    - Raw storage key (object_key) is generated server-side and never exposed to customer APIs.
    - Same-Execution Guard: Optional associations (milestone, inspection) must strictly belong
      to the same Execution instance. Cross-execution association is rejected.
    - Append-only evidence: Document uploads create new immutable records; existing bytes
      must never be overwritten in-place.
    - Historical evidence stability: No normal customer hard-delete API.
    - Clean extension seam: Leaves clear extension room for T1008 ExecutionIssue association
      without implementing Issue domain entities early.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="documents",
        help_text="Parent execution instance.",
    )
    milestone = models.ForeignKey(
        "execution.ExecutionMilestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Optional associated execution milestone instance.",
    )
    inspection = models.ForeignKey(
        "execution.ExecutionInspection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Optional associated execution inspection instance.",
    )
    issue = models.ForeignKey(
        "execution.ExecutionIssue",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Optional associated execution issue instance.",
    )
    category = models.CharField(
        max_length=50,
        choices=ExecutionDocumentCategory.choices,
        db_index=True,
        help_text="Authoritative operational document category.",
    )
    file_name = models.CharField(
        max_length=255,
        help_text="Safe original filename.",
    )
    content_type = models.CharField(
        max_length=127,
        help_text="MIME content type.",
    )
    size_bytes = models.PositiveBigIntegerField(
        help_text="File size in bytes.",
    )
    object_key = models.CharField(
        max_length=1024,
        unique=True,
        help_text="Internal storage object key in MinIO/S3. Never exposed to customer API.",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_execution_documents",
        help_text="User who uploaded this document.",
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Authoritative server timestamp when document was uploaded.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        verbose_name = "Execution Document"
        verbose_name_plural = "Execution Documents"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(category__in=ExecutionDocumentCategory.values),
                name="check_valid_execution_document_category",
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name="check_positive_execution_document_size",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        if self.size_bytes is not None and self.size_bytes <= 0:
            raise ValidationError({"size_bytes": "File size must be strictly positive."})

        if not self.file_name or not self.file_name.strip():
            raise ValidationError({"file_name": "File name cannot be empty."})

        # Same-Execution Guard (Epic 10 Contract §62)
        if self.milestone_id and self.execution_id:
            if self.milestone.execution_id != self.execution_id:
                raise ValidationError(
                    {"milestone": f"Milestone '{self.milestone_id}' does not belong to execution '{self.execution_id}'."}
                )

        if self.inspection_id and self.execution_id:
            if self.inspection.execution_id != self.execution_id:
                raise ValidationError(
                    {"inspection": f"Inspection '{self.inspection_id}' does not belong to execution '{self.execution_id}'."}
                )

        if self.issue_id and self.execution_id:
            if self.issue.execution_id != self.execution_id:
                raise ValidationError(
                    {"issue": f"Issue '{self.issue_id}' does not belong to execution '{self.execution_id}'."}
                )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"ExecutionDocument({self.id}, {self.category}, {self.file_name})"
