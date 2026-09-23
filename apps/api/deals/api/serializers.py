from rest_framework import serializers

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealCostSnapshot,
    DealPartySnapshot,
    DealTermsSnapshot,
)
from deals.services.materialization import _is_operator_or_admin


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


class DealAttributionSerializer(serializers.ModelSerializer):
    """
    Role-scoped DealAttribution representation (Epic 9 Contract §78, §79, T0903).

    Projection rules:
    - Internal (Operator / Product Admin): Full provenance view including evidence_snapshot,
      resolved_by_id, and resolution_reason.
    - Customer (Buyer / Seller): Privacy-preserving customer projection exposing only
      status, primary_channel, resolution_method, resolved_at, version, created_at.
      Private evidence_snapshot, resolved_by_id, and resolution_reason are withheld (null).
    """

    deal_id = serializers.UUIDField(source="deal.id", read_only=True)
    resolved_by_id = serializers.UUIDField(
        source="resolved_by.id", read_only=True, allow_null=True
    )
    resolution_reason = serializers.CharField(
        read_only=True, allow_null=True, allow_blank=True
    )
    evidence_snapshot = serializers.JSONField(
        read_only=True, allow_null=True
    )

    class Meta:
        model = DealAttribution
        fields = [
            "id",
            "deal_id",
            "status",
            "primary_channel",
            "resolution_method",
            "resolved_by_id",
            "resolved_at",
            "resolution_reason",
            "evidence_snapshot",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def to_representation(self, instance: DealAttribution) -> dict:
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not _is_operator_or_admin(user):
            data["evidence_snapshot"] = None
            data["resolved_by_id"] = None
            data["resolution_reason"] = None
        return data


class DealAttributionResolveRequestSerializer(serializers.Serializer):
    """Payload for manual resolution of a PENDING DealAttribution (Contract §47, §101, T0903)."""

    primary_channel = serializers.ChoiceField(
        choices=DealAttributionChannel.choices,
        help_text="Primary origin attribution category to assign.",
    )
    reason = serializers.CharField(
        min_length=1,
        help_text="Operational explanation or justification for the manual resolution decision.",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="Optional expected version of DealAttribution for optimistic locking.",
    )


class DealResponseSerializer(serializers.ModelSerializer):
    """Minimal durable Deal aggregate representation (T0901, T0902, T0903)."""

    terms = DealTermsSnapshotSerializer(source="terms_snapshot", read_only=True)
    parties = DealPartySnapshotSerializer(source="party_snapshots", many=True, read_only=True)
    attribution = DealAttributionSerializer(read_only=True)

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
            "attribution",
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

