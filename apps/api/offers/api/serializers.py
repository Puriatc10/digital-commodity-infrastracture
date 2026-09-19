from decimal import Decimal
from typing import Optional

from rest_framework import serializers

from offers.enums import (
    CostComponentKind,
    FORBIDDEN_REVISION_FIELDS,
    LogisticsCostStatus,
    RevisionRequestedField,
)
from commodities.serializers import CommoditySchemaVersionSerializer
from offers.models import (
    Award,
    AwardAllocation,
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
    revision_request = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional RevisionRequest UUID if this submission is resolving an open revision request.",
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
    aggregate_version = serializers.IntegerField(
        help_text="Current optimistic concurrency aggregate_version of the parent Offer.",
    )


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


class RevisionRequestDraftCreateSerializer(serializers.Serializer):
    """
    Payload for creating a Draft OfferVersion from an OPEN RevisionRequest (T0811).
    """

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected Offer aggregate_version for optimistic concurrency control.",
    )


class RevisionRequestSubmitSerializer(serializers.Serializer):
    """
    Payload for submitting a revised Draft OfferVersion and resolving the RevisionRequest (T0811).
    """

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected Offer aggregate_version for optimistic concurrency control.",
    )
    draft_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional Draft OfferVersion UUID. If omitted, the offer's active draft is submitted.",
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


class OfferVersionHistorySerializer(serializers.ModelSerializer):
    """
    Structured representation of an OfferVersion in negotiation history (T0812).
    """

    cost_components = OfferCostComponentResponseSerializer(many=True, read_only=True)
    aggregate_version = serializers.SerializerMethodField(
        help_text="Current optimistic concurrency aggregate_version of the parent Offer."
    )
    submitted_by_name = serializers.SerializerMethodField(
        help_text="Display name or role of the user who submitted this version."
    )
    created_by_name = serializers.SerializerMethodField(
        help_text="Display name or role of the user who created this version draft."
    )
    entered_by_operator = serializers.SerializerMethodField(
        help_text="Whether this version was entered by an Operator on behalf of an external party."
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
            "submitted_by_name",
            "submitted_at",
            "created_by_id",
            "created_by_name",
            "created_at",
            "updated_at",
            "aggregate_version",
            "entered_by_operator",
        ]
        read_only_fields = fields

    def get_aggregate_version(self, obj: OfferVersion) -> int:
        return obj.offer.aggregate_version

    def get_submitted_by_name(self, obj: OfferVersion) -> Optional[str]:
        if not obj.submitted_by:
            return None
        from identity.models import SystemRoleAssignment

        is_operator = SystemRoleAssignment.objects.filter(
            user=obj.submitted_by,
            role__in=[
                SystemRoleAssignment.SystemRole.OPERATOR,
                SystemRoleAssignment.SystemRole.ADMIN,
            ],
        ).exists()
        if is_operator:
            return "اپراتور سامانه"
        return getattr(obj.submitted_by, "email", "")

    def get_created_by_name(self, obj: OfferVersion) -> Optional[str]:
        if not obj.created_by:
            return None
        from identity.models import SystemRoleAssignment

        is_operator = SystemRoleAssignment.objects.filter(
            user=obj.created_by,
            role__in=[
                SystemRoleAssignment.SystemRole.OPERATOR,
                SystemRoleAssignment.SystemRole.ADMIN,
            ],
        ).exists()
        if is_operator:
            return "اپراتور سامانه"
        return getattr(obj.created_by, "email", "")

    def get_entered_by_operator(self, obj: OfferVersion) -> bool:
        if obj.offer.entered_by_operator:
            return True
        from identity.models import SystemRoleAssignment

        actor = obj.submitted_by or obj.created_by
        if actor:
            return SystemRoleAssignment.objects.filter(
                user=actor,
                role__in=[
                    SystemRoleAssignment.SystemRole.OPERATOR,
                    SystemRoleAssignment.SystemRole.ADMIN,
                ],
            ).exists()
        return False


class RevisionRequestHistorySerializer(serializers.ModelSerializer):
    """
    Authoritative representation of a RevisionRequest in negotiation history (T0812).
    """

    offer_id = serializers.UUIDField(help_text="Parent Offer UUID.")
    base_offer_version_id = serializers.UUIDField(help_text="Base OfferVersion UUID.")
    base_version_number = serializers.IntegerField(
        source="base_offer_version.version_number",
        read_only=True,
        help_text="Version number of the base OfferVersion.",
    )
    requested_by_id = serializers.UUIDField(help_text="User UUID who created the request.")
    requested_by_name = serializers.SerializerMethodField(
        help_text="Display name or role label of the requester."
    )
    requested_by_role = serializers.SerializerMethodField(
        help_text="Role of the requester: BUYER or OPERATOR."
    )
    resolved_by_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of resolving OfferVersion.",
    )
    resolved_version_number = serializers.SerializerMethodField(
        help_text="Version number of resolving OfferVersion."
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
            "requested_by_name",
            "requested_by_role",
            "requested_at",
            "status",
            "resolved_by_version_id",
            "resolved_version_number",
            "resolved_at",
            "offer_aggregate_version",
            "updated_at",
        ]
        read_only_fields = fields

    def get_resolved_version_number(self, obj: RevisionRequest) -> Optional[int]:
        if obj.resolved_by_version_id and obj.resolved_by_version:
            return obj.resolved_by_version.version_number
        return None

    def get_requested_by_role(self, obj: RevisionRequest) -> str:
        from identity.models import SystemRoleAssignment

        if obj.requested_by and SystemRoleAssignment.objects.filter(
            user=obj.requested_by,
            role__in=[
                SystemRoleAssignment.SystemRole.OPERATOR,
                SystemRoleAssignment.SystemRole.ADMIN,
            ],
        ).exists():
            return "OPERATOR"
        return "BUYER"

    def get_requested_by_name(self, obj: RevisionRequest) -> str:
        if self.get_requested_by_role(obj) == "OPERATOR":
            return "اپراتور سامانه"
        return "خریدار"


class OfferNegotiationHistoryResponseSerializer(serializers.Serializer):
    """
    Authoritative read projection for an Offer's negotiation history (T0812, Contract §56).
    """

    offer_id = serializers.UUIDField(help_text="Offer UUID.")
    rfq_id = serializers.UUIDField(help_text="RFQ UUID.")
    offeror_role = serializers.CharField(help_text="Role: SUPPLIER or BROKER.")
    counterparty_name = serializers.CharField(help_text="Safe display name of the offering party.")
    is_external = serializers.BooleanField(help_text="Whether offer is an external counterparty quote.")
    entered_by_operator = serializers.BooleanField(
        help_text="Whether offer was entered by a platform Operator."
    )
    aggregate_version = serializers.IntegerField(help_text="Current optimistic concurrency version.")
    current_submitted_version_id = serializers.UUIDField(
        allow_null=True, help_text="Current submitted OfferVersion UUID."
    )
    schema = CommoditySchemaVersionSerializer(
        help_text="Historical CommoditySchemaVersion bound to the RFQ."
    )
    versions = OfferVersionHistorySerializer(
        many=True, help_text="Chronological submitted OfferVersions."
    )
    revision_requests = RevisionRequestHistorySerializer(
        many=True, help_text="Chronological formal RevisionRequests."
    )


class AwardAllocationResponseSerializer(serializers.ModelSerializer):
    """
    Authoritative read projection for an AwardAllocation (Contract §64, T0813).
    """

    id = serializers.UUIDField(help_text="Allocation UUID.")
    award_id = serializers.UUIDField(help_text="Parent Award UUID.")
    offer_id = serializers.UUIDField(help_text="Parent Offer UUID.")
    offer_version_id = serializers.UUIDField(help_text="Selected OfferVersion UUID.")
    offer_version_number = serializers.SerializerMethodField(
        help_text="Sequential version number of the selected OfferVersion."
    )
    unit_price = serializers.DecimalField(
        source="offer_version.unit_price",
        max_digits=14,
        decimal_places=2,
        read_only=True,
        help_text="Offered unit price.",
    )
    currency = serializers.CharField(
        source="offer_version.currency",
        read_only=True,
        help_text="Currency code.",
    )
    offered_quantity = serializers.DecimalField(
        source="offer_version.offered_quantity",
        max_digits=15,
        decimal_places=3,
        read_only=True,
        help_text="Total offered quantity in snapshot.",
    )
    awarded_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        read_only=True,
        help_text="Awarded commercial quantity.",
    )
    quantity_unit = serializers.CharField(
        read_only=True,
        help_text="Commercial unit of measurement.",
    )
    counterparty_name = serializers.SerializerMethodField(
        help_text="Safe counterparty display name."
    )
    is_external = serializers.SerializerMethodField(
        help_text="Whether this allocation belongs to an external counterparty offer."
    )
    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="Allocation creation timestamp.",
    )

    class Meta:
        model = AwardAllocation
        fields = [
            "id",
            "award_id",
            "offer_id",
            "offer_version_id",
            "offer_version_number",
            "unit_price",
            "currency",
            "offered_quantity",
            "awarded_quantity",
            "quantity_unit",
            "counterparty_name",
            "is_external",
            "created_at",
        ]
        read_only_fields = fields

    def get_offer_version_number(self, obj: AwardAllocation) -> Optional[int]:
        if obj.offer_version_id and hasattr(obj, "offer_version") and obj.offer_version:
            return obj.offer_version.version_number
        return None

    def get_counterparty_name(self, obj: AwardAllocation) -> str:
        offer = obj.offer
        if offer.external_counterparty_id and offer.external_counterparty:
            return offer.external_counterparty.company_name
        if offer.offering_organization_id and offer.offering_organization:
            return offer.offering_organization.name
        return "طرف تجاری"

    def get_is_external(self, obj: AwardAllocation) -> bool:
        return bool(obj.offer.external_counterparty_id)


class AwardDetailResponseSerializer(serializers.ModelSerializer):
    """
    Authoritative read projection for an Award aggregate (Contract §63, T0813).
    """

    id = serializers.UUIDField(help_text="Award UUID.")
    rfq_id = serializers.UUIDField(help_text="Target RFQ UUID.")
    rfq_quantity = serializers.DecimalField(
        source="rfq.quantity",
        max_digits=15,
        decimal_places=3,
        read_only=True,
        help_text="RFQ requested procurement quantity.",
    )
    rfq_unit = serializers.CharField(
        source="rfq.unit",
        read_only=True,
        help_text="RFQ procurement unit of measurement.",
    )
    status = serializers.CharField(
        help_text="Lifecycle status of the award: DRAFT or FINALIZED."
    )
    version = serializers.IntegerField(
        help_text="Optimistic concurrency aggregate version counter."
    )
    created_by_id = serializers.UUIDField(
        help_text="UUID of the platform user who created the draft award."
    )
    created_at = serializers.DateTimeField(
        help_text="Timestamp when the draft award was created."
    )
    finalized_by_id = serializers.UUIDField(
        allow_null=True,
        help_text="UUID of the platform user who finalized the award.",
    )
    finalized_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Authoritative server timestamp when the award was finalized.",
    )
    allocations = AwardAllocationResponseSerializer(
        many=True,
        read_only=True,
        help_text="Commercial allocations contained within this award.",
    )
    total_awarded_quantity = serializers.SerializerMethodField(
        help_text="Sum of all awarded quantities across allocations."
    )
    remaining_quantity = serializers.SerializerMethodField(
        help_text="RFQ requested quantity minus total awarded quantity."
    )
    is_fully_allocated = serializers.SerializerMethodField(
        help_text="True if total awarded quantity exactly equals RFQ requested quantity."
    )

    class Meta:
        model = Award
        fields = [
            "id",
            "rfq_id",
            "rfq_quantity",
            "rfq_unit",
            "status",
            "version",
            "created_by_id",
            "created_at",
            "finalized_by_id",
            "finalized_at",
            "allocations",
            "total_awarded_quantity",
            "remaining_quantity",
            "is_fully_allocated",
        ]
        read_only_fields = fields

    def get_total_awarded_quantity(self, obj: Award) -> Decimal:
        allocs = obj.allocations.all() if hasattr(obj, "allocations") else []
        return sum((a.awarded_quantity for a in allocs), Decimal("0"))

    def get_remaining_quantity(self, obj: Award) -> Decimal:
        total = self.get_total_awarded_quantity(obj)
        rfq_qty = obj.rfq.quantity if obj.rfq else Decimal("0")
        return max(rfq_qty - total, Decimal("0"))

    def get_is_fully_allocated(self, obj: Award) -> bool:
        total = self.get_total_awarded_quantity(obj)
        rfq_qty = obj.rfq.quantity if obj.rfq else Decimal("0")
        return total == rfq_qty


class AwardCreateRequestSerializer(serializers.Serializer):
    """Payload for creating a Draft Award aggregate on an RFQ."""

    rfq_id = serializers.UUIDField(
        required=False,
        help_text="Target RFQ UUID (optional if provided in route path).",
    )


class AwardAllocationCreateRequestSerializer(serializers.Serializer):
    """Payload for adding an allocation to a Draft Award."""

    offer_version_id = serializers.UUIDField(
        required=True,
        help_text="UUID of the exact current submitted OfferVersion to allocate.",
    )
    awarded_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=True,
        help_text="Commercial quantity to award (must be > 0 and <= offered quantity).",
    )
    quantity_unit = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        help_text="Unit of measurement (optional, defaults to OfferVersion unit).",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected aggregate version of the Award for optimistic locking.",
    )


class AwardAllocationUpdateRequestSerializer(serializers.Serializer):
    """Payload for updating quantity of an existing AwardAllocation."""

    awarded_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=True,
        help_text="Updated awarded commercial quantity.",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected aggregate version of the Award for optimistic locking.",
    )


class AwardAllocationDeleteRequestSerializer(serializers.Serializer):
    """Payload for deleting an AwardAllocation from a Draft Award."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected aggregate version of the Award for optimistic locking.",
    )


class AwardFinalizeRequestSerializer(serializers.Serializer):
    """Payload for authoritatively finalizing an Award."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Expected aggregate version of the Award for optimistic locking.",
    )



