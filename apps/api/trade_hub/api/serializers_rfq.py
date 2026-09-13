from decimal import Decimal

from rest_framework import serializers

from organizations.api.serializers import DirectoryOrganizationSerializer
from trade_hub.models import RFQ, RFQVisibility


class DynamicFieldErrorSerializer(serializers.Serializer):
    """Structured representation of a dynamic specification validation error."""

    field = serializers.CharField(help_text="Specification attribute key.")
    code = serializers.CharField(help_text="Machine-readable error code.")
    message = serializers.CharField(help_text="Human-readable error description.")


class RFQErrorResponseSerializer(serializers.Serializer):
    """Standardized error response payload with optional structured dynamic field errors."""

    detail = serializers.CharField(help_text="High-level error summary.")
    errors = DynamicFieldErrorSerializer(
        many=True,
        required=False,
        help_text="Structured dynamic specification errors if applicable.",
    )


class RFQCreateSerializer(serializers.Serializer):
    """Payload for creating a new Draft RFQ."""

    commodity_id = serializers.UUIDField(
        help_text="UUID of the referenced commodity definition."
    )
    schema_version_id = serializers.UUIDField(
        help_text="UUID of the exact referenced commodity schema version."
    )
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        help_text="Procurement quantity (must be positive).",
    )
    unit = serializers.CharField(
        max_length=20,
        required=False,
        default="MT",
        help_text="Unit of measurement (e.g. MT, Barrels).",
    )
    specifications = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Dynamic technical specifications JSON payload.",
    )
    target_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        help_text="Optional target price per unit.",
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
        default="USD",
        help_text="ISO 4217 3-letter currency code (e.g. USD, EUR).",
    )
    payment_terms = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested payment terms (e.g. LC at sight, TT).",
    )
    incoterm = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        default="",
        help_text="Incoterm code (e.g. FOB, CIF, CFR).",
    )
    origin = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested origin country or port.",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested destination country or port.",
    )
    delivery_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Earliest acceptable delivery date.",
    )
    delivery_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Latest acceptable delivery date.",
    )
    submission_deadline = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Offer submission deadline timestamp.",
    )
    inspection_required = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether third-party quality inspection is required.",
    )
    quality_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Quality, testing, or inspection instructions.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="General procurement notes or comments.",
    )
    visibility = serializers.ChoiceField(
        choices=RFQVisibility.choices,
        required=False,
        default=RFQVisibility.PRIVATE,
        help_text="Participation visibility tier (private, network, public).",
    )
    organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Target buyer organization UUID. Allowed only for platform operators/admins acting on behalf.",
    )


class RFQUpdateSerializer(serializers.Serializer):
    """Payload for updating an existing Draft RFQ."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current aggregate version counter for optimistic concurrency control.",
    )
    commodity_id = serializers.UUIDField(
        required=False,
        help_text="UUID of new commodity definition if updating product.",
    )
    schema_version_id = serializers.UUIDField(
        required=False,
        help_text="UUID of new schema version if updating product.",
    )
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        help_text="Updated procurement quantity.",
    )
    unit = serializers.CharField(
        max_length=20,
        required=False,
        help_text="Updated unit of measurement.",
    )
    specifications = serializers.JSONField(
        required=False,
        help_text="Updated dynamic technical specifications JSON payload.",
    )
    target_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        help_text="Updated target price per unit.",
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
        help_text="Updated ISO 4217 currency code.",
    )
    payment_terms = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Updated payment terms.",
    )
    incoterm = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        help_text="Updated incoterm code.",
    )
    origin = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Updated origin country or port.",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Updated destination country or port.",
    )
    delivery_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Updated delivery window start date.",
    )
    delivery_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Updated delivery window end date.",
    )
    submission_deadline = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Updated offer submission deadline timestamp.",
    )
    inspection_required = serializers.BooleanField(
        required=False,
        help_text="Updated inspection requirement flag.",
    )
    quality_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Updated quality notes.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Updated general procurement notes.",
    )
    visibility = serializers.ChoiceField(
        choices=RFQVisibility.choices,
        required=False,
        help_text="Updated visibility tier.",
    )


class RFQPublishActionSerializer(serializers.Serializer):
    """Payload for publishing a Draft RFQ."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current aggregate version counter for optimistic concurrency control.",
    )


class RFQBuilderResponseSerializer(serializers.ModelSerializer):
    """
    Comprehensive RFQ projection for the owning Buyer organization and Platform Operators.
    Exposes full commercial, delivery, technical, administrative, and lifecycle audit details.
    """

    organization = DirectoryOrganizationSerializer(read_only=True)
    commodity_id = serializers.UUIDField(source="commodity.id", read_only=True)
    commodity_code = serializers.CharField(source="commodity.code", read_only=True)
    commodity_name_fa = serializers.CharField(source="commodity.name_fa", read_only=True)
    commodity_name_en = serializers.CharField(source="commodity.name_en", read_only=True)
    schema_version_id = serializers.UUIDField(source="schema_version.id", read_only=True)
    schema_version_number = serializers.IntegerField(
        source="schema_version.version", read_only=True
    )

    class Meta:
        model = RFQ
        fields = [
            "id",
            "organization",
            "commodity_id",
            "commodity_code",
            "commodity_name_fa",
            "commodity_name_en",
            "schema_version_id",
            "schema_version_number",
            "specifications",
            "quantity",
            "unit",
            "target_price",
            "currency",
            "payment_terms",
            "incoterm",
            "origin",
            "destination",
            "delivery_window_start",
            "delivery_window_end",
            "submission_deadline",
            "inspection_required",
            "quality_notes",
            "notes",
            "status",
            "visibility",
            "version",
            "created_by_operator",
            "published_at",
            "closed_at",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class RFQPublicResponseSerializer(serializers.ModelSerializer):
    """
    Safe public/counterparty RFQ projection for external Suppliers and Brokers.
    Exposes commercial and technical procurement terms while omitting internal buyer notes,
    operator provenance, and internal administrative audit details.
    """

    organization = DirectoryOrganizationSerializer(read_only=True)
    commodity_id = serializers.UUIDField(source="commodity.id", read_only=True)
    commodity_code = serializers.CharField(source="commodity.code", read_only=True)
    commodity_name_fa = serializers.CharField(source="commodity.name_fa", read_only=True)
    commodity_name_en = serializers.CharField(source="commodity.name_en", read_only=True)
    schema_version_id = serializers.UUIDField(source="schema_version.id", read_only=True)
    schema_version_number = serializers.IntegerField(
        source="schema_version.version", read_only=True
    )

    class Meta:
        model = RFQ
        fields = [
            "id",
            "organization",
            "commodity_id",
            "commodity_code",
            "commodity_name_fa",
            "commodity_name_en",
            "schema_version_id",
            "schema_version_number",
            "specifications",
            "quantity",
            "unit",
            "target_price",
            "currency",
            "payment_terms",
            "incoterm",
            "origin",
            "destination",
            "delivery_window_start",
            "delivery_window_end",
            "submission_deadline",
            "inspection_required",
            "quality_notes",
            "status",
            "visibility",
            "version",
            "published_at",
            "created_at",
        ]
        read_only_fields = fields
