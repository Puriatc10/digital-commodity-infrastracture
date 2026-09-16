import datetime
from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    Opportunity,
    OpportunityContactAttempt,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
    OpportunityTask,
)
from trade_hub.api.serializers_rfq import RFQBuilderResponseSerializer
from trade_hub.api.serializers_supply import SupplyListingSupplierResponseSerializer



def normalize_opportunity_source(value: str) -> str:
    """Normalizes input source string to canonical OpportunitySource enum value."""
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "broker_referral": OpportunitySource.BROKER_REFERRAL,
        "operator_sourcing": OpportunitySource.OPERATOR_SOURCING,
        "buyer_referral": OpportunitySource.BUYER_REFERRAL,
        "supplier_referral": OpportunitySource.SUPPLIER_REFERRAL,
        "existing_relationship": OpportunitySource.EXISTING_RELATIONSHIP,
        "inbound_lead": OpportunitySource.INBOUND_LEAD,
    }
    return mapping.get(cleaned, value.strip())


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


class QualificationIssueSerializer(serializers.Serializer):
    """Machine-readable qualification issue for readiness inspection and error responses."""

    field = serializers.CharField(read_only=True, help_text="Field name associated with the qualification issue.")
    code = serializers.CharField(read_only=True, help_text="Machine-readable issue code (e.g. required, min_value, invalid_broker).")
    message = serializers.CharField(read_only=True, help_text="Human-readable explanation of the qualification issue.")


class OpportunityQualificationErrorResponseSerializer(serializers.Serializer):
    """Structured machine-readable error payload returned on qualification failure."""

    detail = serializers.CharField(read_only=True, help_text="Summary explanation of the qualification failure.")
    qualifiable = serializers.BooleanField(read_only=True, help_text="Always false for failed qualification evaluations.")
    missing_requirements = QualificationIssueSerializer(many=True, read_only=True, help_text="List of mandatory fields missing from the Opportunity.")
    invalid_requirements = QualificationIssueSerializer(many=True, read_only=True, help_text="List of fields present with invalid values.")


# -------------------------------------------------------------------------
# Opportunity Read Projection
# -------------------------------------------------------------------------

class OpportunityDetailSerializer(serializers.ModelSerializer):
    """
    Read projection for Opportunity records.
    Provides safe representations of linked counterparty and commodity entities,
    lifecycle state, and qualification readiness indicators.
    """

    counterparty_type = serializers.SerializerMethodField(
        help_text="Type of counterparty: 'organization' or 'external_counterparty'."
    )
    can_qualify = serializers.SerializerMethodField(
        help_text="Readiness flag indicating if this Opportunity can be qualified in its current state."
    )
    qualification_issues = serializers.SerializerMethodField(
        help_text="List of qualification issues blocking qualification (empty if ready or qualifiable)."
    )
    organization = OpportunityOrganizationProjectionSerializer(read_only=True)
    external_counterparty = OpportunityExternalCounterpartyProjectionSerializer(read_only=True)
    commodity = OpportunityCommodityProjectionSerializer(read_only=True)
    source = serializers.ChoiceField(
        choices=OpportunitySource.choices,
        read_only=True,
        help_text="Authoritative origin source of the opportunity lead.",
    )
    broker = OpportunityOrganizationProjectionSerializer(
        read_only=True,
        allow_null=True,
        help_text="Safe projection of attributed broker organization (present for Broker Referral).",
    )
    converted_rfq_id = serializers.UUIDField(
        source="converted_rfq.id",
        read_only=True,
        allow_null=True,
        help_text="UUID of the converted RFQ if converted.",
    )
    converted_supply_listing_id = serializers.UUIDField(
        source="converted_supply_listing.id",
        read_only=True,
        allow_null=True,
        help_text="UUID of the converted Supply Listing if converted.",
    )
    schema_version_id = serializers.UUIDField(
        source="schema_version.id",
        read_only=True,
        allow_null=True,
        help_text="UUID of the referenced commodity schema version if bound.",
    )
    specifications = serializers.JSONField(
        read_only=True,
        help_text="Dynamic specifications JSON payload if recorded.",
    )

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "identifier",
            "direction",
            "counterparty_type",
            "can_qualify",
            "qualification_issues",
            "organization",
            "external_counterparty",
            "commodity",
            "schema_version_id",
            "specifications",
            "source",
            "broker",
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
            "version",
            "converted_rfq_id",
            "converted_supply_listing_id",
            "contacted_at",
            "qualified_at",
            "converted_at",
            "held_at",
            "hold_reason",
            "status_before_hold",
            "rejected_at",
            "rejection_reason",
            "lost_at",
            "lost_reason",
            "expired_at",
            "expiration_reason",
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

    @extend_schema_field(serializers.BooleanField())
    def get_can_qualify(self, obj) -> bool:
        if obj.status not in (OpportunityStatus.CAPTURED, OpportunityStatus.CONTACTED):
            return False
        from opportunities.services_qualification import evaluate_qualification

        return evaluate_qualification(obj).is_qualifiable

    @extend_schema_field(QualificationIssueSerializer(many=True))
    def get_qualification_issues(self, obj) -> list[dict[str, str]]:
        if obj.status not in (OpportunityStatus.CAPTURED, OpportunityStatus.CONTACTED):
            return [
                {
                    "field": "status",
                    "code": "invalid_status",
                    "message": f"Opportunities in status '{obj.status}' cannot be qualified.",
                }
            ]
        from opportunities.services_qualification import evaluate_qualification

        eval_result = evaluate_qualification(obj)
        return [i.to_dict() for i in eval_result.all_issues]


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
    source = serializers.ChoiceField(
        choices=OpportunitySource.choices,
        required=False,
        default=OpportunitySource.OPERATOR_SOURCING,
        help_text="Authoritative origin source of the opportunity lead.",
    )
    broker_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of attributed broker organization (required if source is Broker Referral).",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "direction" in data and isinstance(data["direction"], str):
                data["direction"] = data["direction"].strip().capitalize()
            if "source" in data and isinstance(data["source"], str):
                normalized = normalize_opportunity_source(data["source"])
                if normalized:
                    data["source"] = normalized
            if "broker" in data and "broker_id" not in data:
                broker_val = data["broker"]
                if isinstance(broker_val, dict) and "id" in broker_val:
                    data["broker_id"] = broker_val["id"]
                elif isinstance(broker_val, str):
                    data["broker_id"] = broker_val
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

        source = attrs.get("source", OpportunitySource.OPERATOR_SOURCING)
        broker_id = attrs.get("broker_id")

        if source == OpportunitySource.BROKER_REFERRAL:
            if not broker_id:
                raise serializers.ValidationError(
                    {"broker_id": "Broker organization is required when source is Broker Referral."}
                )
            from organizations.models import Organization, OrganizationCapability

            if not Organization.objects.filter(id=broker_id).exists():
                raise serializers.ValidationError({"broker_id": "Attributed broker organization does not exist."})
            if not OrganizationCapability.objects.filter(
                organization_id=broker_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists():
                raise serializers.ValidationError(
                    {"broker_id": "Attributed organization must possess Broker capability."}
                )
        else:
            if broker_id:
                raise serializers.ValidationError(
                    {"broker_id": "Broker organization must not be set when source is not Broker Referral."}
                )

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
    Permits updating editable commercial/delivery/counterparty/source fields while
    strictly guarding status, created_by, timestamps, etc.
    """

    expected_version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Expected aggregate version for optimistic concurrency control.",
    )
    direction = serializers.ChoiceField(
        choices=OpportunityDirection.choices,
        required=False,
        help_text="Trade direction: Supply or Demand.",
    )
    source = serializers.ChoiceField(
        choices=OpportunitySource.choices,
        required=False,
        help_text="Authoritative origin source of the opportunity lead.",
    )
    broker_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of attributed broker organization.",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "direction" in data and isinstance(data["direction"], str):
                data["direction"] = data["direction"].strip().capitalize()
            if "source" in data and isinstance(data["source"], str):
                normalized = normalize_opportunity_source(data["source"])
                if normalized:
                    data["source"] = normalized
            if "broker" in data and "broker_id" not in data:
                broker_val = data["broker"]
                if isinstance(broker_val, dict) and "id" in broker_val:
                    data["broker_id"] = broker_val["id"]
                elif isinstance(broker_val, str):
                    data["broker_id"] = broker_val
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

        # Source and broker consistency
        new_source = attrs.get("source", instance.source if instance else OpportunitySource.OPERATOR_SOURCING)

        if "broker_id" in attrs:
            new_broker_id = attrs["broker_id"]
        else:
            new_broker_id = instance.broker_id if instance else None

        if new_source == OpportunitySource.BROKER_REFERRAL:
            if not new_broker_id:
                raise serializers.ValidationError(
                    {"broker_id": "Broker organization is required when source is Broker Referral."}
                )
            from organizations.models import Organization, OrganizationCapability

            if not Organization.objects.filter(id=new_broker_id).exists():
                raise serializers.ValidationError({"broker_id": "Attributed broker organization does not exist."})
            if not OrganizationCapability.objects.filter(
                organization_id=new_broker_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists():
                raise serializers.ValidationError(
                    {"broker_id": "Attributed organization must possess Broker capability."}
                )
        else:
            if new_broker_id:
                raise serializers.ValidationError(
                    {"broker_id": "Broker organization must not be set when source is not Broker Referral."}
                )

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


# -------------------------------------------------------------------------
# Lifecycle Action Serializers (T0603)
# -------------------------------------------------------------------------

class OpportunityLifecycleBaseActionSerializer(serializers.Serializer):
    """Base action payload requiring expected_version for optimistic concurrency control."""

    expected_version = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text="Current expected aggregate version for optimistic concurrency control.",
    )


class OpportunityLifecycleReasonActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Action payload requiring expected_version and a mandatory non-empty reason."""

    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Mandatory operational reason for this lifecycle action.",
    )

    def validate_reason(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Reason must not be blank.")
        return cleaned


class OpportunityLifecycleOptionalReasonActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Action payload with expected_version and an optional reason."""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Optional operational reason or notes.",
    )


class OpportunityContactActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Payload to transition Opportunity from Captured to Contacted."""

    pass


class OpportunityQualifyActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Payload to qualify an Opportunity."""

    pass


class OpportunityMatchActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Payload to transition a qualified Opportunity into Matching."""

    pass


class OpportunityHoldActionSerializer(OpportunityLifecycleReasonActionSerializer):
    """Payload to put an active Opportunity on hold."""

    pass


class OpportunityResumeActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """Payload to resume an Opportunity from hold back to its pre-hold status."""

    pass


class OpportunityRejectActionSerializer(OpportunityLifecycleReasonActionSerializer):
    """Payload to reject an Opportunity."""

    pass


class OpportunityLostActionSerializer(OpportunityLifecycleReasonActionSerializer):
    """Payload to mark an Opportunity as lost."""

    pass


class OpportunityExpireActionSerializer(OpportunityLifecycleOptionalReasonActionSerializer):
    """Payload to expire an Opportunity."""

    pass


class OpportunityConvertToRFQActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """
    Action payload to authoritatively convert an eligible Demand Opportunity into a Draft RFQ.
    Guards strictly against mass-assignment of status, version, timestamps, or unverified ownership.
    """

    schema_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the referenced commodity schema version (required if not stored on Opportunity).",
    )
    specifications = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Dynamic technical specifications JSON payload validated against schema version.",
    )
    buyer_organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the internal Buyer Organization (required if Opportunity references an External Counterparty).",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested destination country or port (defaults to Opportunity geography).",
    )
    origin = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested origin country or port.",
    )
    incoterm = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        default="",
        help_text="Incoterm code (e.g. FOB, CIF, CFR).",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Additional procurement notes to append to RFQ notes.",
    )
    visibility = serializers.ChoiceField(
        choices=[("private", "Private"), ("network", "Network"), ("public", "Public")],
        required=False,
        default="private",
        help_text="Participation visibility tier for the new RFQ.",
    )


class OpportunityConvertToRFQResponseSerializer(serializers.Serializer):
    """Structured response payload returned upon successful conversion to RFQ."""

    opportunity = OpportunityDetailSerializer(
        read_only=True,
        help_text="The updated Opportunity aggregate in Converted status.",
    )
    rfq = RFQBuilderResponseSerializer(
        read_only=True,
        help_text="The newly created Draft RFQ aggregate.",
    )


class OpportunityConvertToSupplyListingActionSerializer(OpportunityLifecycleBaseActionSerializer):
    """
    Action payload to authoritatively convert an eligible Supply Opportunity into a Draft Supply Listing.
    Guards strictly against mass-assignment of status, version, timestamps, or unverified ownership.
    """

    schema_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the referenced commodity schema version (required if not stored on Opportunity).",
    )
    specifications = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Dynamic technical specifications JSON payload validated against schema version.",
    )
    supplier_organization_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the internal Supplier Organization (required if Opportunity references an External Counterparty).",
    )
    origin = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested origin country, facility, or port (defaults to Opportunity geography).",
    )
    destination = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Requested destination country or port if restricted.",
    )
    incoterm = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        default="",
        help_text="Incoterm code (e.g. FOB, CIF, CFR).",
    )
    availability_window_start = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Earliest availability date (defaults to Opportunity delivery window start).",
    )
    availability_window_end = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Latest availability date (defaults to Opportunity delivery window end).",
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
        help_text="Additional commercial notes to append to Supply Listing notes.",
    )
    visibility = serializers.ChoiceField(
        choices=[("private", "Private"), ("network", "Network"), ("public", "Public")],
        required=False,
        default="public",
        help_text="Participation visibility tier for the new Supply Listing.",
    )


class OpportunityConvertToSupplyListingResponseSerializer(serializers.Serializer):
    """Structured response payload returned upon successful conversion to Supply Listing."""

    opportunity = OpportunityDetailSerializer(
        read_only=True,
        help_text="The updated Opportunity aggregate in Converted status.",
    )
    supply_listing = SupplyListingSupplierResponseSerializer(
        read_only=True,
        help_text="The newly created Draft Supply Listing aggregate.",
    )


# -------------------------------------------------------------------------
# Contact Attempt Serializers (T0606)
# -------------------------------------------------------------------------

class OpportunityContactAttemptCreateSerializer(serializers.Serializer):
    """
    Payload for recording a new Opportunity contact attempt.
    Strictly guards server-derived fields: recorded_by, opportunity_id, id, created_at.
    """

    type = serializers.ChoiceField(
        choices=ContactAttemptType.choices,
        required=True,
        help_text="Type of contact attempt: CALL, MESSAGE, EMAIL, MEETING, NOTE.",
    )
    occurred_at = serializers.DateTimeField(
        required=False,
        default=timezone.now,
        help_text="Timestamp when the interaction took place (defaults to now).",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Operational notes or details of the interaction.",
    )
    details = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="Optional write-only alias for notes.",
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = data.copy()
            if "type" in data and isinstance(data["type"], str):
                data["type"] = data["type"].strip().upper()
        return super().to_internal_value(data)

    def validate_occurred_at(self, value):
        if value and value > timezone.now() + datetime.timedelta(minutes=5):
            raise serializers.ValidationError("occurred_at cannot be in the future.")
        return value

    def validate(self, attrs):
        if "details" in attrs:
            details_val = attrs.pop("details")
            if not attrs.get("notes"):
                attrs["notes"] = details_val
        return attrs


class OpportunityContactAttemptDetailSerializer(serializers.ModelSerializer):
    """
    Read representation for an Opportunity contact attempt.
    All fields are strictly read-only.
    """

    opportunity_id = serializers.UUIDField(source="opportunity.id", read_only=True)
    recorded_by = serializers.IntegerField(source="recorded_by.id", read_only=True, allow_null=True)
    recorded_by_email = serializers.EmailField(source="recorded_by.email", read_only=True, allow_null=True)

    class Meta:
        model = OpportunityContactAttempt
        fields = [
            "id",
            "opportunity_id",
            "type",
            "occurred_at",
            "recorded_by",
            "recorded_by_email",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


# -------------------------------------------------------------------------
# Opportunity Task Serializers (T0607)
# -------------------------------------------------------------------------

class OpportunityTaskCreateSerializer(serializers.Serializer):
    """
    Payload for creating an Opportunity follow-up task.
    Strictly prevents mass-assignment of system/lifecycle fields:
    created_by, status, completed_at, id, opportunity_id, timestamps.
    """

    title = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Brief summary or action required for the follow-up task.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Detailed instructions or operational context for the follow-up task.",
    )
    due_at = serializers.DateTimeField(
        required=True,
        help_text="Due date and time for the follow-up task.",
    )
    assigned_to = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="User ID of the assigned Operator or Admin.",
    )

    def validate_title(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Title is required.")
        return cleaned

    def validate_assigned_to(self, value: int | None) -> int | None:
        if value is not None:
            from identity.models import SystemRoleAssignment, User

            if not User.objects.filter(id=value, is_active=True).exists():
                raise serializers.ValidationError("Assigned user does not exist or is inactive.")

            is_eligible = SystemRoleAssignment.objects.filter(
                user_id=value,
                role__in=[
                    SystemRoleAssignment.SystemRole.OPERATOR,
                    SystemRoleAssignment.SystemRole.ADMIN,
                ],
            ).exists()
            if not is_eligible:
                raise serializers.ValidationError("Assigned user must be an active internal Operator or Admin.")
        return value


class OpportunityTaskUpdateSerializer(serializers.Serializer):
    """
    Payload for updating mutable attributes of an OPEN Opportunity follow-up task.
    Protects status, completed_at, created_by, opportunity, id, timestamps against modification.
    """

    title = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Updated task title.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Updated task description.",
    )
    due_at = serializers.DateTimeField(
        required=False,
        help_text="Updated due date and time.",
    )
    assigned_to = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="User ID of the assigned Operator or Admin (or null to unassign).",
    )

    def validate_title(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Title is required.")
        return cleaned

    def validate_assigned_to(self, value: int | None) -> int | None:
        if value is not None:
            from identity.models import SystemRoleAssignment, User

            if not User.objects.filter(id=value, is_active=True).exists():
                raise serializers.ValidationError("Assigned user does not exist or is inactive.")

            is_eligible = SystemRoleAssignment.objects.filter(
                user_id=value,
                role__in=[
                    SystemRoleAssignment.SystemRole.OPERATOR,
                    SystemRoleAssignment.SystemRole.ADMIN,
                ],
            ).exists()
            if not is_eligible:
                raise serializers.ValidationError("Assigned user must be an active internal Operator or Admin.")
        return value


class OpportunityTaskDetailSerializer(serializers.ModelSerializer):
    """
    Read representation for an Opportunity follow-up task.
    All fields are strictly read-only.
    """

    opportunity_id = serializers.UUIDField(source="opportunity.id", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    assigned_to = serializers.IntegerField(source="assigned_to.id", read_only=True, allow_null=True)
    assigned_to_email = serializers.EmailField(source="assigned_to.email", read_only=True, allow_null=True)
    created_by = serializers.IntegerField(source="created_by.id", read_only=True, allow_null=True)
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True, allow_null=True)

    class Meta:
        model = OpportunityTask
        fields = [
            "id",
            "opportunity_id",
            "title",
            "description",
            "due_at",
            "status",
            "is_overdue",
            "assigned_to",
            "assigned_to_email",
            "created_by",
            "created_by_email",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
