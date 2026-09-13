import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class RFQInvitationStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    VIEWED = "viewed", "Viewed"
    RESPONDED = "responded", "Responded"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"


class RFQInvitation(models.Model):
    """
    Represents an explicit participation invitation extended by a Buyer or Operator
    to a Supplier or Broker organization for a specific RFQ.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rfq = models.ForeignKey(
        "trade_hub.RFQ",
        on_delete=models.CASCADE,
        related_name="invitations",
        help_text="The RFQ to which the organization is invited.",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="rfq_invitations",
        help_text="The invited supplier or broker organization.",
    )

    status = models.CharField(
        max_length=30,
        choices=RFQInvitationStatus.choices,
        default=RFQInvitationStatus.INVITED,
        help_text="Current lifecycle state of the invitation.",
    )

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sent_rfq_invitations",
        help_text="The authenticated user who sent the invitation.",
    )
    invited_by_operator = models.BooleanField(
        default=False,
        help_text="True if invited by a platform operator on behalf of the buyer organization.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the invitee first viewed the RFQ/invitation.",
    )
    responded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the invitee submitted a response or offer.",
    )
    declined_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the invitee declined the invitation.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the invitation expires.",
    )
    decline_reason = models.TextField(
        blank=True,
        help_text="Optional reason provided when declining the invitation.",
    )

    def clean(self):
        super().clean()
        errors = {}

        if self.status not in RFQInvitationStatus.values:
            errors["status"] = f"Invalid invitation status: '{self.status}'."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "organization"],
                name="unique_rfq_organization_invitation",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[c[0] for c in RFQInvitationStatus.choices]
                ),
                name="check_valid_rfq_invitation_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status"], name="idx_rfq_inv_org_status"
            ),
            models.Index(fields=["rfq", "status"], name="idx_rfq_inv_rfq_status"),
            models.Index(fields=["-created_at"], name="idx_rfq_inv_created_at_desc"),
        ]

    def __str__(self):
        return f"RFQInvitation {self.id} - RFQ {self.rfq_id} -> {self.organization_id} ({self.status})"
