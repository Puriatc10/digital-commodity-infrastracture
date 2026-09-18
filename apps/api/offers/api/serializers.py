from decimal import Decimal
from typing import Optional

from rest_framework import serializers

from offers.enums import (
    CostComponentKind,
    FORBIDDEN_REVISION_FIELDS,
    LogisticsCostStatus,
    RevisionRequestedField,
)
from offers.models import (
    DecisionCandidate,
    DecisionRun,
    DecisionSignal,
    Offer,
    OfferCostComponent,
    OfferVersion,
    RevisionRequest,
)



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


class NormalizedOfferVersionResponseSerializer(serializers.Serializer):
    """
    Structured serialized representation of an immutable NormalizedOfferVersion domain result.
    (Epic 8 Contract §33, T0805).
    """

    product_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Product cost derived from unit_price * offered_quantity.",
    )
    known_cost_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Sum of genuinely known cost components (product + known logistics + known other).",
    )
    landed_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        allow_null=True,
        help_text="Landed cost if required logistics evidence is known; None if UNKNOWN.",
    )
    landed_unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        allow_null=True,
        help_text="Landed cost divided by offered_quantity; None if landed_cost is None.",
    )
    normalization_complete = serializers.BooleanField(
        help_text="Whether all required v1 cost evidence is sufficiently known.",
    )
    missing_components = serializers.ListField(
        child=serializers.CharField(),
        help_text="Machine-readable list of missing required cost components.",
    )
    currency = serializers.CharField(
        max_length=3,
        help_text="ISO 4217 3-letter currency code (retains original OfferVersion currency).",
    )
    policy_version = serializers.CharField(
        max_length=20,
        help_text="Semantic policy version applied during normalisation.",
    )


class ComparisonRowSerializer(serializers.Serializer):
    """
    Typed, safe commercial comparison row for Buyer and Operator procurement intelligence (T0806).

    Invariants:
    - Never exposes private external contact details (phone, email, contact_name, notes).
    - Uses exact Decimal arithmetic/representations; never binary float.
    - Zero decision scoring or recommendation bias.
    """

    offer_id = serializers.UUIDField(help_text="Stable Offer thread UUID.")
    offer_version_id = serializers.UUIDField(help_text="Exact current submitted OfferVersion UUID.")
    version_number = serializers.IntegerField(help_text="Submitted version number.")
    safe_offeror_identity = serializers.CharField(help_text="Safe commercial identity of the offering party.")
    offeror_name = serializers.CharField(help_text="Safe display name of the offering party.")
    is_external = serializers.BooleanField(help_text="Whether offer is from an off-platform external supplier.")
    offeror_role = serializers.CharField(help_text="Commercial role (SUPPLIER or BROKER).")

    offered_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Proposed commercial quantity.",
    )
    quantity_unit = serializers.CharField(max_length=20, help_text="Unit of measurement.")
    quantity_coverage = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
        help_text="Quantity coverage ratio min(offered / requested, 1.0).",
    )
    surplus_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="Surplus quantity max(offered - requested, 0.0).",
    )

    unit_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Proposed unit price.",
    )
    currency = serializers.CharField(max_length=3, help_text="ISO 4217 3-letter currency code.")

    product_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Product cost derived from unit_price * offered_quantity.",
    )
    known_cost_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Sum of known cost components.",
    )
    landed_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        allow_null=True,
        help_text="Landed cost if logistics is known; null if UNKNOWN.",
    )
    landed_unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        allow_null=True,
        help_text="Landed unit cost if logistics is known; null if UNKNOWN.",
    )
    normalization_complete = serializers.BooleanField(
        help_text="Whether normalisation has complete cost evidence.",
    )
    missing_components = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of missing required cost components.",
    )
    cost_comparability = serializers.ChoiceField(
        choices=["COMPARABLE", "CROSS_CURRENCY_UNKNOWN", "INCOMPLETE_COST"],
        help_text="Structured cost comparability status.",
    )

    payment_terms = serializers.CharField(allow_blank=True, help_text="Proposed payment terms.")
    delivery_terms = serializers.CharField(allow_blank=True, help_text="Proposed delivery terms.")
    incoterm = serializers.CharField(allow_blank=True, help_text="Incoterm code.")
    delivery_start = serializers.DateField(allow_null=True, help_text="Earliest delivery date.")
    delivery_end = serializers.DateField(allow_null=True, help_text="Latest delivery date.")
    valid_until = serializers.DateTimeField(allow_null=True, help_text="Proposal validity timestamp.")
    is_expired = serializers.BooleanField(help_text="Whether proposal validity has expired.")

    technical_compliance = serializers.ChoiceField(
        choices=["PASS", "FAIL", "UNKNOWN"],
        help_text="Dynamic commodity specification compliance outcome.",
    )
    trust_status = serializers.CharField(help_text="Authoritative verification status or UNKNOWN.")


class OperatorComparisonRowSerializer(ComparisonRowSerializer):
    """
    Comparison row for Platform Operators, including safe provenance context.
    """

    source_opportunity_id = serializers.UUIDField(
        allow_null=True,
        required=False,
        help_text="Originating lead/opportunity UUID.",
    )
    source_opportunity_identifier = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Human-readable Opportunity identifier.",
    )
    entered_by_operator = serializers.BooleanField(
        allow_null=True,
        required=False,
        help_text="Whether offer was entered on behalf by an Operator.",
    )


class RFQComparisonResponseSerializer(serializers.Serializer):
    """
    Authoritative response envelope for RFQ commercial comparison (T0806).
    """

    rfq_id = serializers.UUIDField(help_text="Target RFQ UUID.")
    rfq_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="RFQ requested procurement quantity.",
    )
    rfq_unit = serializers.CharField(max_length=20, help_text="RFQ unit of measurement.")
    rfq_currency = serializers.CharField(max_length=3, help_text="RFQ currency.")
    total_offers = serializers.IntegerField(help_text="Total number of active submitted offers compared.")
    items = ComparisonRowSerializer(many=True, help_text="List of compared offers.")
    offers = ComparisonRowSerializer(many=True, source="items", help_text="List of compared offers (alias of items).")


class OperatorRFQComparisonResponseSerializer(serializers.Serializer):
    """
    Authoritative response envelope for RFQ commercial comparison with Operator provenance (T0806).
    """

    rfq_id = serializers.UUIDField(help_text="Target RFQ UUID.")
    rfq_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        help_text="RFQ requested procurement quantity.",
    )
    rfq_unit = serializers.CharField(max_length=20, help_text="RFQ unit of measurement.")
    rfq_currency = serializers.CharField(max_length=3, help_text="RFQ currency.")
    total_offers = serializers.IntegerField(help_text="Total number of active submitted offers compared.")
    items = OperatorComparisonRowSerializer(many=True, help_text="List of compared offers with provenance.")
    offers = OperatorComparisonRowSerializer(many=True, source="items", help_text="List of compared offers with provenance (alias of items).")


class DecisionSignalResponseSerializer(serializers.ModelSerializer):
    """
    Representation of an evaluated signal within a DecisionCandidate (T0809).
    """

    class Meta:
        model = DecisionSignal
        fields = [
            "id",
            "dimension",
            "code",
            "status",
            "weight",
            "raw_score",
            "contribution",
            "expected_value",
            "actual_value",
            "reason_code",
            "snapshot_data",
            "created_at",
        ]
        read_only_fields = fields


class DecisionCandidateResponseSerializer(serializers.ModelSerializer):
    """
    Representation of an evaluated candidate within a DecisionRun (T0808, T0809).
    """

    offer_id = serializers.UUIDField(help_text="Parent offer negotiation thread UUID.")
    offer_version_id = serializers.UUIDField(help_text="Exact evaluated OfferVersion snapshot UUID.")
    version_number = serializers.IntegerField(
        source="offer_version.version_number",
        read_only=True,
        help_text="Version number of evaluated OfferVersion.",
    )
    signals = DecisionSignalResponseSerializer(many=True, read_only=True)

    class Meta:
        model = DecisionCandidate
        fields = [
            "id",
            "offer_id",
            "offer_version_id",
            "version_number",
            "decision_score",
            "evidence_coverage",
            "effective_score",
            "award_eligible",
            "eligibility_reasons",
            "rank",
            "is_recommended",
            "signals",
            "created_at",
        ]
        read_only_fields = fields


class DecisionRunDetailResponseSerializer(serializers.ModelSerializer):
    """
    Authoritative response envelope for a DecisionRun audit and execution record (T0808, T0809).
    """

    rfq_id = serializers.UUIDField(help_text="Target RFQ UUID.")
    profile_version_id = serializers.UUIDField(
        source="decision_profile_version_id",
        help_text="Evaluated DecisionProfileVersion UUID.",
    )
    profile_code = serializers.CharField(
        source="decision_profile_version.profile.code",
        read_only=True,
        help_text="Evaluated policy profile code.",
    )
    profile_version_number = serializers.IntegerField(
        source="decision_profile_version.version",
        read_only=True,
        help_text="Evaluated policy version number.",
    )
    candidates = DecisionCandidateResponseSerializer(many=True, read_only=True)
    total_candidates = serializers.SerializerMethodField(help_text="Total number of evaluated candidates.")
    is_stale = serializers.SerializerMethodField(
        help_text="Whether evaluated candidate universe differs from current RFQ submitted offers (Contract §80).",
    )
    recommended_candidate_id = serializers.SerializerMethodField(
        help_text="UUID of the recommended DecisionCandidate, or null if none met recommendation threshold.",
    )

    class Meta:
        model = DecisionRun
        fields = [
            "id",
            "rfq_id",
            "profile_version_id",
            "profile_code",
            "profile_version_number",
            "engine_version",
            "created_by_id",
            "created_at",
            "input_fingerprint",
            "result_fingerprint",
            "total_candidates",
            "is_stale",
            "recommended_candidate_id",
            "candidates",
        ]
        read_only_fields = fields

    def get_total_candidates(self, obj: DecisionRun) -> int:
        return obj.candidates.count()

    def get_is_stale(self, obj: DecisionRun) -> bool:
        return obj.is_stale

    def get_recommended_candidate_id(self, obj: DecisionRun) -> Optional[str]:
        recommended = obj.candidates.filter(is_recommended=True).first()
        return str(recommended.id) if recommended else None


class DecisionRunCreateRequestSerializer(serializers.Serializer):
    """
    Optional payload for initiating a DecisionRun foundation (T0808).
    """

    profile_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional exact Published DecisionProfileVersion UUID. Defaults to current default Published v1.",
    )


class RevisionRequestCreateSerializer(serializers.Serializer):
    """
    Request payload for opening a RevisionRequest against an Offer (T0810, Contract §56).
    """

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected Offer aggregate_version for optimistic concurrency control.",
    )
    base_offer_version = serializers.UUIDField(
        required=True,
        help_text="UUID of the submitted OfferVersion serving as the revision base.",
    )
    requested_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=RevisionRequestedField.choices),
        allow_empty=False,
        required=True,
        help_text="Canonical list of field names requested for revision.",
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional human-readable explanation or negotiation guidance.",
    )

    def validate_requested_fields(self, value):
        if not value:
            raise serializers.ValidationError("At least one field must be requested for revision.")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("requested_fields cannot contain duplicate entries.")
        for f in value:
            if f in FORBIDDEN_REVISION_FIELDS:
                raise serializers.ValidationError(
                    f"Field '{f}' is a server-owned attribute and cannot be requested for revision."
                )
        return value


class RevisionRequestActionSerializer(serializers.Serializer):
    """
    Payload for declining or cancelling an open RevisionRequest (T0810).
    """

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected Offer aggregate_version for optimistic concurrency control.",
    )


class RevisionRequestResponseSerializer(serializers.ModelSerializer):
    """
    Authoritative representation of a RevisionRequest record (T0810, Contract §56).
    """

    offer_id = serializers.UUIDField(help_text="Parent Offer UUID.")
    base_offer_version_id = serializers.UUIDField(help_text="Base OfferVersion UUID.")
    base_version_number = serializers.IntegerField(
        source="base_offer_version.version_number",
        read_only=True,
        help_text="Version number of the base OfferVersion.",
    )
    requested_by_id = serializers.UUIDField(help_text="User UUID who created the request.")
    resolved_by_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of resolving OfferVersion (populated upon resolution in T0811).",
    )
    offer_aggregate_version = serializers.IntegerField(
        source="offer.aggregate_version",
        read_only=True,
        help_text="Current aggregate_version of the parent Offer.",
    )

    class Meta:
        model = RevisionRequest
        fields = [
            "id",
            "offer_id",
            "base_offer_version_id",
            "base_version_number",
            "requested_fields",
            "message",
            "requested_by_id",
            "requested_at",
            "status",
            "resolved_by_version_id",
            "resolved_at",
            "offer_aggregate_version",
            "updated_at",
        ]
        read_only_fields = fields


