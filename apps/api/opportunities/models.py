import uuid

from django.conf import settings
from django.db import models


class ExternalCounterparty(models.Model):
    """
    Represents an off-platform real-world commercial counterparty recorded by an Operator.

    Critical Invariant:
        ExternalCounterparty != User
        ExternalCounterparty != Organization

    This entity does NOT create or require a platform User, Organization,
    OrganizationMembership, or OrganizationCapability row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core commercial & contact fields (Product Specification §21)
    company_name = models.CharField(
        max_length=255,
        help_text="Display or legal entity name of the external counterparty.",
    )
    contact_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the individual representative or contact person.",
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone number for operational contact.",
    )
    email = models.EmailField(
        max_length=254,
        blank=True,
        help_text="Email address for operational contact.",
    )
    geography = models.CharField(
        max_length=255,
        blank=True,
        help_text="Country, port, or regional jurisdiction.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Free-form operational notes by the Operator.",
    )

    # Internal actor tracking (nullable: can exist without platform user)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_external_counterparties",
        help_text="Operator who recorded this external counterparty (null if unassigned/system).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "External Counterparty"
        verbose_name_plural = "External Counterparties"
        indexes = [
            models.Index(fields=["company_name"], name="idx_ext_cp_company_name"),
            models.Index(fields=["-created_at"], name="idx_ext_cp_created_at_desc"),
        ]

    def __str__(self):
        if self.contact_name:
            return f"{self.company_name} ({self.contact_name})"
        return self.company_name
