import uuid
from django.conf import settings
from django.db import models

class DocumentType(models.TextChoices):
    COMPANY_REGISTRATION = "company_registration", "Company Registration"
    TAX_ID = "tax_id", "Tax ID"
    TRADE_LICENSE = "trade_license", "Trade License"
    BANK_DETAILS = "bank_details", "Bank Details"
    AUTHORIZED_REPRESENTATIVE = "authorized_representative", "Authorized Representative"
    CERTIFICATIONS = "certifications", "Certifications"

class VerificationDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="documents")
    type = models.CharField(max_length=50, choices=DocumentType.choices)

    file_name = models.CharField(max_length=255)
    object_key = models.CharField(max_length=1024, unique=True)
    mime_type = models.CharField(max_length=127)
    size_bytes = models.IntegerField()

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_documents")
    verification_status = models.CharField(max_length=50, default="pending") # e.g. pending, accepted, rejected, replaced

    # Optional tie to specific Verification version
    verification_version = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type__in=[c[0] for c in DocumentType.choices]),
                name="check_valid_document_type"
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.get_type_display()} ({self.file_name})"
