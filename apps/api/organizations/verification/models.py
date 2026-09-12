import uuid
from django.conf import settings
from django.db import models
from organizations.models import Organization

class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    DOCUMENTS_SUBMITTED = "documents_submitted", "Documents Submitted"
    UNDER_REVIEW = "under_review", "Under Review"
    BASIC_VERIFIED = "basic_verified", "Basic Verified"
    VERIFIED = "verified", "Verified"
    SUSPENDED = "suspended", "Suspended"

class OrganizationVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="verification")
    status = models.CharField(
        max_length=50,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in VerificationStatus.choices]),
                name="check_valid_verification_status"
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.get_status_display()}"

class VerificationAction(models.TextChoices):
    SUBMIT = "submit", "Submit"
    START_REVIEW = "start_review", "Start Review"
    APPROVE_BASIC = "approve_basic", "Approve Basic"
    APPROVE_FULL = "approve_full", "Approve Full"
    REJECT = "reject", "Reject"
    SUSPEND = "suspend", "Suspend"
    REOPEN = "reopen", "Reopen"
    EVIDENCE_REPLACEMENT_INVALIDATION = "evidence_replacement_invalidation", "Evidence Replacement Invalidation"

class VerificationDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(OrganizationVerification, on_delete=models.CASCADE, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="verification_decisions")
    action = models.CharField(max_length=50, choices=VerificationAction.choices, null=True, blank=True)
    previous_status = models.CharField(max_length=50, choices=VerificationStatus.choices)
    new_status = models.CharField(max_length=50, choices=VerificationStatus.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(previous_status__in=[c[0] for c in VerificationStatus.choices]),
                name="check_valid_previous_status"
            ),
            models.CheckConstraint(
                condition=models.Q(new_status__in=[c[0] for c in VerificationStatus.choices]),
                name="check_valid_new_status"
            ),
            models.CheckConstraint(
                # Null action is permitted ONLY for legacy migration records. New records must supply a valid action.
                # However, since this check is database wide, we can just allow null OR a valid choice.
                condition=models.Q(action__isnull=True) | models.Q(action__in=[c[0] for c in VerificationAction.choices]),
                name="check_valid_decision_action"
            )
        ]

    def __str__(self):
        return f"{self.verification.organization.name}: {self.get_previous_status_display()} -> {self.get_new_status_display()}"

class VerificationNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(OrganizationVerification, on_delete=models.CASCADE, related_name="notes")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="verification_notes")
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note for {self.verification.organization.name} at {self.created_at}"

class VerificationChecklistReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(OrganizationVerification, on_delete=models.CASCADE, related_name="checklist_reviews")
    document = models.ForeignKey("documents.VerificationDocument", on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="checklist_reviews")
    outcome = models.CharField(
        max_length=50,
        choices=[("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected")]
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=["pending", "accepted", "rejected"]),
                name="check_valid_review_outcome"
            )
        ]

    def __str__(self):
        return f"Review {self.outcome} by {self.reviewer} for {self.document.file_name}"
