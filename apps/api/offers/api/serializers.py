from decimal import Decimal
from rest_framework import serializers

from offers.models import OfferCostComponent, OfferVersion


class OfferCostComponentResponseSerializer(serializers.ModelSerializer):
    """Immutable cost component line item."""

    class Meta:
        model = OfferCostComponent
        fields = [
            "id",
            "kind",
            "amount",
            "currency",
            "description",
            "created_at",
        ]
        read_only_fields = fields


class OfferVersionResponseSerializer(serializers.ModelSerializer):
    """
    Structured representation of an OfferVersion commercial snapshot.
    """

    cost_components = OfferCostComponentResponseSerializer(many=True, read_only=True)
    aggregate_version = serializers.SerializerMethodField(
        help_text="Current optimistic concurrency aggregate_version of the parent Offer."
    )

    class Meta:
        model = OfferVersion
        fields = [
            "id",
            "offer_id",
            "version_number",
            "status",
            "schema_version_id",
            "specifications",
            "offered_quantity",
            "quantity_unit",
            "unit_price",
            "currency",
            "payment_terms",
            "delivery_terms",
            "incoterm",
            "delivery_start",
            "delivery_end",
            "valid_until",
            "logistics_cost_status",
            "logistics_cost_amount",
            "notes",
            "cost_components",
            "submitted_by_id",
            "submitted_at",
            "created_by_id",
            "created_at",
            "updated_at",
            "aggregate_version",
        ]
        read_only_fields = fields

    def get_aggregate_version(self, obj: OfferVersion) -> int:
        return obj.offer.aggregate_version


class OfferVersionSubmitActionSerializer(serializers.Serializer):
    """Payload for submitting a Draft OfferVersion."""

    expected_version = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text="Expected aggregate_version of the parent Offer for optimistic concurrency control.",
    )


class OfferErrorResponseSerializer(serializers.Serializer):
    """Standardized error response payload."""

    detail = serializers.CharField(help_text="High-level error description.")
    errors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional list of error messages or validation details.",
    )
