from decimal import Decimal

from rest_framework import serializers

from offers.enums import CostComponentKind, LogisticsCostStatus
from offers.models import Offer, OfferCostComponent, OfferVersion


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


class OfferCostComponentInputSerializer(serializers.Serializer):
    """Input payload for a child cost component."""

    kind = serializers.ChoiceField(choices=CostComponentKind.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OperatorExternalOfferSubmissionSerializer(serializers.Serializer):
    """
    Authoritative payload for Operator submission of an external quote on behalf.
    """

    rfq_id = serializers.UUIDField(
        required=True,
        help_text="Target RFQ ID to which the offer will be submitted.",
    )
    opportunity_id = serializers.CharField(
        required=True,
        help_text="UUID or human-readable identifier (OPP-...) of the Qualified Supply Opportunity.",
    )
    offered_quantity = serializers.DecimalField(
        required=True,
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        help_text="Proposed commercial quantity (must be strictly positive).",
    )
    quantity_unit = serializers.CharField(
        required=True,
        max_length=20,
        help_text="Unit of measurement (must be compatible with RFQ unit).",
    )
    unit_price = serializers.DecimalField(
        required=True,
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Proposed unit price (must be strictly positive).",
    )
    currency = serializers.CharField(
        required=False,
        max_length=3,
        default="USD",
        help_text="ISO 4217 3-letter currency code.",
    )
    payment_terms = serializers.CharField(
        required=False,
        max_length=255,
        allow_blank=True,
        default="",
        help_text="Proposed payment terms.",
    )
    delivery_terms = serializers.CharField(
        required=False,
        max_length=255,
        allow_blank=True,
        default="",
        help_text="Proposed delivery terms.",
    )
    incoterm = serializers.CharField(
        required=False,
        max_length=10,
        allow_blank=True,
        default="",
        help_text="Incoterm code.",
    )
    delivery_start = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Earliest proposed delivery date.",
    )
    delivery_end = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Latest proposed delivery date.",
    )
    valid_until = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Offer validity timestamp.",
    )
    logistics_cost_status = serializers.ChoiceField(
        choices=LogisticsCostStatus.choices,
        required=False,
        default=LogisticsCostStatus.UNKNOWN,
        help_text="Status of logistics cost knowledge.",
    )
    logistics_cost_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
        help_text="Separate logistics cost amount (required if KNOWN_SEPARATE).",
    )
    specifications = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Dynamic commodity specifications validated against RFQ schema.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Commercial notes.",
    )
    cost_components = OfferCostComponentInputSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Optional cost component breakdown items.",
    )
    external_counterparty_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional external counterparty ID (must match Opportunity external counterparty).",
    )
    expected_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        help_text="Optional optimistic concurrency aggregate_version if an Offer parent already exists.",
    )


class BuyerOfferProjectionResponseSerializer(serializers.ModelSerializer):
    """
    Safe commercial Offer projection for authorized RFQ Buyer actors.

    Invariants:
    - Never exposes phone, email, contact attempts, operator notes,
      qualification notes, or private sourcing/broker notes.
    """

    counterparty_name = serializers.SerializerMethodField(
        help_text="Display name of the offering party (Company name or Organization name)."
    )
    is_external = serializers.BooleanField(
        read_only=True,
        help_text="Whether this offer represents an external off-platform supplier.",
    )
    current_submitted_version = OfferVersionResponseSerializer(
        read_only=True,
        help_text="Active submitted commercial version proposal.",
    )

    class Meta:
        model = Offer
        fields = [
            "id",
            "rfq_id",
            "offeror_role",
            "counterparty_name",
            "is_external",
            "current_submitted_version",
            "aggregate_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_counterparty_name(self, obj: Offer) -> str:
        if obj.external_counterparty_id and obj.external_counterparty:
            return obj.external_counterparty.company_name
        if obj.offering_organization_id and obj.offering_organization:
            return obj.offering_organization.name
        return "Unknown"


class OperatorOfferDetailResponseSerializer(serializers.ModelSerializer):
    """
    Complete operational projection for Operators and Product Admins.

    Includes internal provenance context (source Opportunity, ExternalCounterparty,
    created_by actor, entered_by_operator marker).
    """

    counterparty_name = serializers.SerializerMethodField()
    source_opportunity_identifier = serializers.SerializerMethodField()
    is_external = serializers.BooleanField(read_only=True)
    entered_by_operator = serializers.BooleanField(read_only=True)
    current_submitted_version = OfferVersionResponseSerializer(read_only=True)

    class Meta:
        model = Offer
        fields = [
            "id",
            "rfq_id",
            "offeror_role",
            "offering_organization_id",
            "external_counterparty_id",
            "counterparty_name",
            "is_external",
            "entered_by_operator",
            "source_opportunity_id",
            "source_opportunity_identifier",
            "current_submitted_version",
            "aggregate_version",
            "created_by_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_counterparty_name(self, obj: Offer) -> str:
        if obj.external_counterparty_id and obj.external_counterparty:
            return obj.external_counterparty.company_name
        if obj.offering_organization_id and obj.offering_organization:
            return obj.offering_organization.name
        return "Unknown"

    def get_source_opportunity_identifier(self, obj: Offer) -> str | None:
        if obj.source_opportunity_id and obj.source_opportunity:
            return obj.source_opportunity.identifier
        return None


class OfferErrorResponseSerializer(serializers.Serializer):
    """Standardized error response payload."""

    detail = serializers.CharField(help_text="High-level error description.")
    errors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional list of error messages or validation details.",
    )
