from rest_framework import serializers

from deals.models import Deal, DealCostSnapshot, DealPartySnapshot, DealTermsSnapshot


class DealCostSnapshotSerializer(serializers.ModelSerializer):
    """Immutable child cost component snapshot (T0902)."""

    class Meta:
        model = DealCostSnapshot
        fields = [
            "id",
            "kind",
            "amount",
            "currency",
            "description_snapshot",
            "created_at",
        ]
        read_only_fields = fields


class DealTermsSnapshotSerializer(serializers.ModelSerializer):
    """Immutable commercial terms snapshot (T0902)."""

    cost_snapshots = DealCostSnapshotSerializer(many=True, read_only=True)

    class Meta:
        model = DealTermsSnapshot
        fields = [
            "id",
            "deal_id",
            "commodity_id",
            "schema_version_id",
            "specifications",
            "quantity",
            "quantity_unit",
            "unit_price",
            "currency",
            "product_cost_snapshot",
            "payment_terms",
            "delivery_terms",
            "incoterm",
            "delivery_start",
            "delivery_end",
            "origin",
            "destination",
            "origin_area_id",
            "destination_area_id",
            "logistics_cost_status",
            "logistics_cost_amount",
            "cost_snapshots",
            "created_at",
        ]
        read_only_fields = fields


class DealPartySnapshotSerializer(serializers.ModelSerializer):
    """Immutable principal commercial party snapshot (T0902)."""

    class Meta:
        model = DealPartySnapshot
        fields = [
            "id",
            "deal_id",
            "role",
            "party_type",
            "organization_id",
            "external_counterparty_id",
            "name_snapshot",
            "country_snapshot",
            "registration_identifier_snapshot",
            "created_at",
        ]
        read_only_fields = fields


class DealResponseSerializer(serializers.ModelSerializer):
    """Minimal durable Deal aggregate representation (T0901, T0902)."""

    terms = DealTermsSnapshotSerializer(source="terms_snapshot", read_only=True)
    parties = DealPartySnapshotSerializer(source="party_snapshots", many=True, read_only=True)

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
            "terms",
            "parties",
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
