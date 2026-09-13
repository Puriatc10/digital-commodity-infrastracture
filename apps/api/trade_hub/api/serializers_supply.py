from decimal import Decimal

from rest_framework import serializers

from organizations.api.serializers import DirectoryOrganizationSerializer
from trade_hub.api.serializers_rfq import DynamicFieldErrorSerializer
from trade_hub.models import SupplyListing, SupplyListingVisibility


class SupplyListingErrorResponseSerializer(serializers.Serializer):
    """Standardized error response payload with optional structured dynamic field errors."""

    detail = serializers.CharField(help_text="High-level error summary.")
    errors = DynamicFieldErrorSerializer(
        many=True,
        required=False,
        help_text="Structured dynamic specification errors if applicable.",
    )


class SupplyListingCreateSerializer(serializers.Serializer):
    """Payload for creating a new Draft Supply Listing."""

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
        help_text="Supply quantity available (must be positive).",
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
    indicative_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        help_text="Optional indicative price per unit.",
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
        help_text="Indicative payment terms (e.g. LC, TT).",
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
        help_text="Origin location, facility, or port.",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Allowable destination country or port if restricted.",
    )
    availability_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Earliest availability date.",
    )
    availability_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Latest availability date.",
    )
    quality_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Quality, testing, or specification notes.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="General internal notes or comments (hidden from external counterparties).",
    )
    visibility = serializers.ChoiceField(
        choices=SupplyListingVisibility.choices,
        required=False,
        default=SupplyListingVisibility.PUBLIC,
        help_text="Participation visibility tier (public, network, private).",
    )
    organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Target supplier organization UUID. Allowed only for platform operators/admins acting on behalf.",
    )


class SupplyListingUpdateSerializer(serializers.Serializer):
    """Payload for updating an existing Draft Supply Listing."""

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
        help_text="Updated supply quantity.",
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
    indicative_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        help_text="Updated indicative price per unit.",
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
        help_text="Updated origin location or port.",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Updated allowable destination.",
    )
    availability_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Updated availability window start date.",
    )
    availability_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Updated availability window end date.",
    )
    quality_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Updated quality notes.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Updated internal notes.",
    )
    visibility = serializers.ChoiceField(
        choices=SupplyListingVisibility.choices,
        required=False,
        help_text="Updated visibility tier.",
    )


class SupplyListingActivateActionSerializer(serializers.Serializer):
    """Payload for activating a Draft Supply Listing."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current aggregate version counter for optimistic concurrency control.",
    )


class SupplyListingCloseActionSerializer(serializers.Serializer):
    """Payload for closing a Draft or Active Supply Listing."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current aggregate version counter for optimistic concurrency control.",
    )


class SupplyListingSupplierResponseSerializer(serializers.ModelSerializer):
    """
    Comprehensive Supply Listing projection for the owning Supplier organization and Platform Operators.
    Exposes full commercial, availability, technical, internal notes, and lifecycle audit details.
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
        model = SupplyListing
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
            "indicative_price",
            "currency",
            "payment_terms",
            "incoterm",
            "origin",
            "destination",
            "availability_window_start",
            "availability_window_end",
            "quality_notes",
            "notes",
            "status",
            "visibility",
            "version",
            "created_by_operator",
            "activated_at",
            "closed_at",
            "expired_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SupplyListingPublicResponseSerializer(serializers.ModelSerializer):
    """
    Safe public/counterparty Supply Listing projection for external Buyers and Brokers.
    Exposes commercial and technical terms while omitting internal notes,
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
        model = SupplyListing
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
            "indicative_price",
            "currency",
            "payment_terms",
            "incoterm",
            "origin",
            "destination",
            "availability_window_start",
            "availability_window_end",
            "quality_notes",
            "status",
            "visibility",
            "version",
            "activated_at",
            "created_at",
        ]
        read_only_fields = fields
