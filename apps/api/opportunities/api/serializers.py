from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from opportunities.models import ExternalCounterparty, Opportunity, OpportunityDirection



class ExternalCounterpartySerializer(serializers.ModelSerializer):
    """
    Explicit serializer for ExternalCounterparty.

    Guards against mass assignment:
    - Primary key (id), timestamps (created_at, updated_at), and
      internal actor (created_by) are strictly read-only.
    - Rejects empty or whitespace-only company_name.
    - Validates email format if provided.
    """

    company_name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Display or legal entity name of the external counterparty.",
    )
    contact_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Name of the contact person or representative.",
    )
    phone = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Phone number for operational contact.",
    )
    email = serializers.EmailField(
        max_length=254,
        required=False,
        allow_blank=True,
        default="",
        help_text="Email address for operational contact.",
    )
    geography = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Country, port, or regional jurisdiction.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Operational notes recorded by the Operator.",
    )

    class Meta:
        model = ExternalCounterparty
        fields = [
            "id",
            "company_name",
            "contact_name",
            "phone",
            "email",
            "geography",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_company_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Company name must not be blank.")
        return stripped


# -------------------------------------------------------------------------
# Safe Projections for Opportunity Consumers
# -------------------------------------------------------------------------

class OpportunityOrganizationProjectionSerializer(serializers.Serializer):
    """Safe projection of internal Organization details for Opportunity consumers."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    country = serializers.CharField(read_only=True)


class OpportunityExternalCounterpartyProjectionSerializer(serializers.Serializer):
    """Safe projection of ExternalCounterparty details for Opportunity consumers."""

    id = serializers.UUIDField(read_only=True)
    company_name = serializers.CharField(read_only=True)
    contact_name = serializers.CharField(read_only=True)
    geography = serializers.CharField(read_only=True)


class OpportunityCommodityProjectionSerializer(serializers.Serializer):
    """Safe projection of CommodityDefinition for Opportunity consumers."""

    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name_fa = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)


# -------------------------------------------------------------------------
# Opportunity Read Projection
# -------------------------------------------------------------------------

class OpportunityDetailSerializer(serializers.ModelSerializer):
    """
    Read projection for Opportunity records.
    Provides safe representations of linked counterparty and commodity entities.
    """

    counterparty_type = serializers.SerializerMethodField(
        help_text="Type of counterparty: 'organization' or 'external_counterparty'."
    )
    organization = OpportunityOrganizationProjectionSerializer(read_only=True)
    external_counterparty = OpportunityExternalCounterpartyProjectionSerializer(read_only=True)
    commodity = OpportunityCommodityProjectionSerializer(read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "direction",
            "counterparty_type",
            "organization",
            "external_counterparty",
            "commodity",
            "quantity",
            "unit",
            "indicative_price",
            "currency",
            "delivery_window_start",
            "delivery_window_end",
            "payment_terms",
            "geography",
            "notes",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_counterparty_type(self, obj) -> str:
        if obj.organization_id:
            return "organization"
        if obj.external_counterparty_id:
            return "external_counterparty"
        return "unknown"


# -------------------------------------------------------------------------
# Opportunity Write Serializers (Create & Update)
# -------------------------------------------------------------------------

class OpportunityCreateSerializer(serializers.Serializer):
    """
    Payload for capturing a new Opportunity.
    Explicit writable fields with strict mass-assignment prevention.
    """

    direction = serializers.ChoiceField(
        choices=OpportunityDirection.choices,
        required=True,
        help_text="Trade direction: Supply or Demand.",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict) and "direction" in data and isinstance(data["direction"], str):
            data = data.copy()
            data["direction"] = data["direction"].strip().capitalize()
        return super().to_internal_value(data)

    organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of internal registered organization (mutually exclusive with external_counterparty_id).",
    )
    external_counterparty_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of off-platform external counterparty (mutually exclusive with organization_id).",
    )
    commodity_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional UUID of referenced commodity definition.",
    )
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
        default=None,
        help_text="Lead quantity (must be positive).",
    )
    unit = serializers.CharField(
        max_length=20,
        required=False,
        default="MT",
        trim_whitespace=True,
        help_text="Unit of measurement.",
    )
    indicative_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional indicative price per unit.",
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
        default="USD",
        trim_whitespace=True,
        help_text="ISO 4217 currency code.",
    )
    delivery_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Earliest expected delivery date.",
    )
    delivery_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Latest expected delivery date.",
    )
    payment_terms = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Indicative payment terms.",
    )
    geography = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Origin/destination region, country, or port.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Internal operational notes.",
    )

    def validate_direction(self, value: str) -> str:
        v = value.strip().capitalize()
        if v not in [OpportunityDirection.SUPPLY, OpportunityDirection.DEMAND]:
            raise serializers.ValidationError("Direction must be either 'Supply' or 'Demand'.")
        return v

    def validate(self, attrs: dict) -> dict:
        org_id = attrs.get("organization_id")
        ext_id = attrs.get("external_counterparty_id")

        if org_id and ext_id:
            raise serializers.ValidationError(
                {"counterparty": "An opportunity cannot reference both an internal Organization and an ExternalCounterparty."}
            )
        if not org_id and not ext_id:
            raise serializers.ValidationError(
                {"counterparty": "An opportunity must reference either an internal Organization or an ExternalCounterparty."}
            )

        if org_id:
            from organizations.models import Organization

            if not Organization.objects.filter(id=org_id).exists():
                raise serializers.ValidationError({"organization_id": "Organization does not exist."})

        if ext_id:
            if not ExternalCounterparty.objects.filter(id=ext_id).exists():
                raise serializers.ValidationError({"external_counterparty_id": "External counterparty does not exist."})

        cmd_id = attrs.get("commodity_id")
        if cmd_id:
            from commodities.models import CommodityDefinition

            if not CommodityDefinition.objects.filter(id=cmd_id).exists():
                raise serializers.ValidationError({"commodity_id": "Commodity definition does not exist."})

        start = attrs.get("delivery_window_start")
        end = attrs.get("delivery_window_end")
        if start and end and end < start:
            raise serializers.ValidationError(
                {"delivery_window_end": "Delivery window end must be on or after delivery window start."}
            )

        return attrs


class OpportunityUpdateSerializer(serializers.Serializer):
    """
    Payload for updating an Opportunity.
    Permits updating editable commercial/delivery/counterparty fields while
    strictly guarding status, created_by, timestamps, etc.
    """

    direction = serializers.ChoiceField(
        choices=OpportunityDirection.choices,
        required=False,
        help_text="Trade direction: Supply or Demand.",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict) and "direction" in data and isinstance(data["direction"], str):
            data = data.copy()
            data["direction"] = data["direction"].strip().capitalize()
        return super().to_internal_value(data)

    organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of internal registered organization.",
    )
    external_counterparty_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of off-platform external counterparty.",
    )
    commodity_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of referenced commodity definition.",
    )
    quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
        help_text="Lead quantity (must be positive).",
    )
    unit = serializers.CharField(
        max_length=20,
        required=False,
        trim_whitespace=True,
        help_text="Unit of measurement.",
    )
    indicative_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        allow_null=True,
        help_text="Indicative price per unit.",
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
        trim_whitespace=True,
        help_text="ISO 4217 currency code.",
    )
    delivery_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Earliest expected delivery date.",
    )
    delivery_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Latest expected delivery date.",
    )
    payment_terms = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Indicative payment terms.",
    )
    geography = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Origin/destination region, country, or port.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Internal operational notes.",
    )

    def validate_direction(self, value: str) -> str:
        v = value.strip().capitalize()
        if v not in [OpportunityDirection.SUPPLY, OpportunityDirection.DEMAND]:
            raise serializers.ValidationError("Direction must be either 'Supply' or 'Demand'.")
        return v

    def validate(self, attrs: dict) -> dict:
        instance = getattr(self, "instance", None)

        org_id = attrs.get("organization_id", instance.organization_id if instance else None)
        ext_id = attrs.get("external_counterparty_id", instance.external_counterparty_id if instance else None)

        if "organization_id" in attrs and attrs["organization_id"] is None:
            org_id = None
        if "external_counterparty_id" in attrs and attrs["external_counterparty_id"] is None:
            ext_id = None

        if org_id and ext_id:
            raise serializers.ValidationError(
                {"counterparty": "An opportunity cannot reference both an internal Organization and an ExternalCounterparty."}
            )
        if not org_id and not ext_id:
            raise serializers.ValidationError(
                {"counterparty": "An opportunity must reference either an internal Organization or an ExternalCounterparty."}
            )

        if "organization_id" in attrs and attrs["organization_id"] is not None:
            from organizations.models import Organization

            if not Organization.objects.filter(id=attrs["organization_id"]).exists():
                raise serializers.ValidationError({"organization_id": "Organization does not exist."})

        if "external_counterparty_id" in attrs and attrs["external_counterparty_id"] is not None:
            if not ExternalCounterparty.objects.filter(id=attrs["external_counterparty_id"]).exists():
                raise serializers.ValidationError({"external_counterparty_id": "External counterparty does not exist."})

        if "commodity_id" in attrs and attrs["commodity_id"] is not None:
            from commodities.models import CommodityDefinition

            if not CommodityDefinition.objects.filter(id=attrs["commodity_id"]).exists():
                raise serializers.ValidationError({"commodity_id": "Commodity definition does not exist."})

        start = attrs.get("delivery_window_start", instance.delivery_window_start if instance else None)
        end = attrs.get("delivery_window_end", instance.delivery_window_end if instance else None)
        if start and end and end < start:
            raise serializers.ValidationError(
                {"delivery_window_end": "Delivery window end must be on or after delivery window start."}
            )

        return attrs
