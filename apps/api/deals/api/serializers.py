from rest_framework import serializers

from deals.models import Deal


class DealResponseSerializer(serializers.ModelSerializer):
    """Minimal durable Deal aggregate representation (T0901)."""

    class Meta:
        model = Deal
        fields = [
            "id",
            "award_id",
            "award_allocation_id",
            "rfq_id",
            "offer_id",
            "offer_version_id",
            "buyer_organization_id",
            "seller_organization_id",
            "seller_external_counterparty_id",
            "created_by_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DealMaterializeRequestSerializer(serializers.Serializer):
    """Payload for materializing Deals from a finalized Award."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="Optional expected aggregate version of the finalized Award for optimistic locking.",
    )


class DealErrorResponseSerializer(serializers.Serializer):
    """Error response detail schema."""

    detail = serializers.CharField(help_text="Error description or failure reason.")
