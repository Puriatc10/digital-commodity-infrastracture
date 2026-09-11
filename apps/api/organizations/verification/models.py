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

class VerificationDecision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.ForeignKey(OrganizationVerification, on_delete=models.CASCADE, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="verification_decisions")
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
