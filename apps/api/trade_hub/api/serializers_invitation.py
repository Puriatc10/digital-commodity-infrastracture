from rest_framework import serializers

from organizations.api.serializers import DirectoryOrganizationSerializer
from trade_hub.models import RFQInvitation


class RFQInvitationCreateSerializer(serializers.Serializer):
    """Payload for inviting an organization to an RFQ."""

    organization_id = serializers.UUIDField(
        help_text="UUID of the target supplier or broker organization."
    )
    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Optional expiration timestamp for the invitation.",
    )


class RFQInvitationDeclineSerializer(serializers.Serializer):
    """Payload for declining an RFQ invitation."""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional reason explaining why the invitation is being declined.",
    )


class RFQInvitationResponseSerializer(serializers.ModelSerializer):
    """
    Customer-safe projection of an RFQ participant invitation.
    Exposes safe directory identity for the invited organization, lifecycle timestamps,
    and current invitation status. Never leaks internal memberships, audit records, or
    competitor data.
    """

    organization = DirectoryOrganizationSerializer(read_only=True)
    rfq_id = serializers.UUIDField(source="rfq.id", read_only=True)

    class Meta:
        model = RFQInvitation
        fields = [
            "id",
            "rfq_id",
            "organization",
            "status",
            "invited_by_operator",
            "created_at",
            "viewed_at",
            "responded_at",
            "declined_at",
            "expires_at",
            "decline_reason",
        ]
        read_only_fields = fields
