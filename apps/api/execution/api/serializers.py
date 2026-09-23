from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from execution.enums import InspectionResult, TransportMode
from execution.models import (
    ExecutionMilestoneDefinition,
    ExecutionWorkflowTemplate,
    ExecutionWorkflowTemplateVersion,
)


class MilestonePrerequisiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionMilestoneDefinition
        fields = ["id", "code", "name_en", "name_fa", "sort_order"]


class ExecutionMilestoneDefinitionSerializer(serializers.ModelSerializer):
    prerequisite_codes = serializers.SerializerMethodField()

    class Meta:
        model = ExecutionMilestoneDefinition
        fields = [
            "id",
            "code",
            "name_fa",
            "name_en",
            "sort_order",
            "required",
            "blocking",
            "terminal",
            "expected_offset_days",
            "category",
            "prerequisite_codes",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_prerequisite_codes(self, obj: ExecutionMilestoneDefinition):
        return list(obj.prerequisites.values_list("code", flat=True))


class ExecutionWorkflowTemplateVersionSerializer(serializers.ModelSerializer):
    milestones = ExecutionMilestoneDefinitionSerializer(many=True, read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExecutionWorkflowTemplateVersion
        fields = [
            "id",
            "template_id",
            "version_number",
            "status",
            "change_summary",
            "is_active",
            "published_at",
            "retired_at",
            "milestones",
            "created_at",
        ]


class ExecutionWorkflowTemplateVersionSummarySerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExecutionWorkflowTemplateVersion
        fields = [
            "id",
            "version_number",
            "status",
            "is_active",
        ]


class ExecutionWorkflowTemplateSummarySerializer(serializers.ModelSerializer):
    active_version_number = serializers.SerializerMethodField()

    class Meta:
        model = ExecutionWorkflowTemplate
        fields = [
            "id",
            "code",
            "name_fa",
            "name_en",
            "description",
            "is_active",
            "active_version_id",
            "active_version_number",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_active_version_number(self, obj: ExecutionWorkflowTemplate):
        if obj.active_version_id:
            return obj.active_version.version_number
        return None


class ExecutionWorkflowTemplateDetailSerializer(serializers.ModelSerializer):
    active_version = ExecutionWorkflowTemplateVersionSerializer(read_only=True)
    versions = ExecutionWorkflowTemplateVersionSummarySerializer(many=True, read_only=True)

    class Meta:
        model = ExecutionWorkflowTemplate
        fields = [
            "id",
            "code",
            "name_fa",
            "name_en",
            "description",
            "is_active",
            "active_version",
            "versions",
            "created_at",
            "updated_at",
        ]


# =============================================================================
# Execution Runtime Serializers (T1003)
# =============================================================================

class ExecutionMilestoneSerializer(serializers.ModelSerializer):
    """Execution milestone instance presentation serializer."""

    code = serializers.CharField(source="definition.code", read_only=True)
    name_fa = serializers.CharField(source="definition.name_fa", read_only=True)
    name_en = serializers.CharField(source="definition.name_en", read_only=True)
    sort_order = serializers.IntegerField(source="definition.sort_order", read_only=True)
    required = serializers.BooleanField(source="definition.required", read_only=True)
    blocking = serializers.BooleanField(source="definition.blocking", read_only=True)
    terminal = serializers.BooleanField(source="definition.terminal", read_only=True)
    completed_by_email = serializers.SerializerMethodField()

    class Meta:
        from execution.models.milestone import ExecutionMilestone
        model = ExecutionMilestone
        fields = [
            "id",
            "execution_id",
            "definition_id",
            "code",
            "name_fa",
            "name_en",
            "sort_order",
            "required",
            "blocking",
            "terminal",
            "status",
            "expected_at",
            "actual_at",
            "recorded_at",
            "completed_by_id",
            "completed_by_email",
            "notes",
            "version",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_completed_by_email(self, obj) -> str | None:
        if obj.completed_by:
            return getattr(obj.completed_by, "email", None)
        return None


class ExecutionLogisticsSerializer(serializers.ModelSerializer):
    """Operational execution logistics detail serializer (Epic 10 Contract §35, T1004)."""

    carrier = serializers.CharField(source="carrier_name", read_only=True)
    pickup_area_code = serializers.CharField(source="pickup_area.code", read_only=True, allow_null=True)
    pickup_area_name_fa = serializers.CharField(source="pickup_area.name_fa", read_only=True, allow_null=True)
    pickup_area_name_en = serializers.CharField(source="pickup_area.name_en", read_only=True, allow_null=True)
    destination_area_code = serializers.CharField(source="destination_area.code", read_only=True, allow_null=True)
    destination_area_name_fa = serializers.CharField(source="destination_area.name_fa", read_only=True, allow_null=True)
    destination_area_name_en = serializers.CharField(source="destination_area.name_en", read_only=True, allow_null=True)

    class Meta:
        from execution.models.logistics import ExecutionLogistics

        model = ExecutionLogistics
        fields = [
            "id",
            "execution_id",
            "carrier_name",
            "carrier",
            "transport_mode",
            "pickup_area_id",
            "pickup_area_code",
            "pickup_area_name_fa",
            "pickup_area_name_en",
            "destination_area_id",
            "destination_area_code",
            "destination_area_name_fa",
            "destination_area_name_en",
            "pickup_location",
            "destination_location",
            "scheduled_loading_at",
            "actual_loading_at",
            "eta",
            "actual_delivery_at",
            "transport_reference",
            "logistics_cost",
            "currency",
            "version",
            "created_at",
            "updated_at",
        ]


class ExecutionInspectionSerializer(serializers.ModelSerializer):
    """Operational execution inspection detail serializer (Epic 10 Contract §43–§49, T1005)."""

    class Meta:
        from execution.models.inspection import ExecutionInspection

        model = ExecutionInspection
        fields = [
            "id",
            "execution_id",
            "required",
            "agency",
            "scheduled_at",
            "inspection_at",
            "status",
            "result",
            "notes",
            "version",
            "created_at",
            "updated_at",
        ]


class ExecutionDetailSerializer(serializers.ModelSerializer):
    """Full execution aggregate detail serializer."""

    workflow_template_code = serializers.CharField(
        source="workflow_template_version.template.code", read_only=True
    )
    workflow_template_name_fa = serializers.CharField(
        source="workflow_template_version.template.name_fa", read_only=True
    )
    workflow_template_name_en = serializers.CharField(
        source="workflow_template_version.template.name_en", read_only=True
    )
    workflow_version_number = serializers.IntegerField(
        source="workflow_template_version.version_number", read_only=True
    )
    milestones = ExecutionMilestoneSerializer(many=True, read_only=True)
    logistics = ExecutionLogisticsSerializer(read_only=True)
    inspection = ExecutionInspectionSerializer(read_only=True)

    class Meta:
        from execution.models.execution import Execution
        model = Execution
        fields = [
            "id",
            "deal_id",
            "workflow_template_version_id",
            "workflow_template_code",
            "workflow_template_name_fa",
            "workflow_template_name_en",
            "workflow_version_number",
            "status",
            "version",
            "started_at",
            "closed_at",
            "milestones",
            "logistics",
            "inspection",
            "created_at",
            "updated_at",
        ]



class ExecutionCreateRequestSerializer(serializers.Serializer):
    """Request payload for explicit idempotent execution creation."""

    workflow_template_code = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="Canonical workflow template code (e.g. bitumen_standard).",
    )
    workflow_template_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Explicit workflow template UUID.",
    )
    workflow_template_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Explicit workflow template version UUID (must be PUBLISHED).",
    )


class MilestoneStartRequestSerializer(serializers.Serializer):
    """Request payload to transition milestone to IN_PROGRESS."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected milestone version for optimistic concurrency control.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional operational notes.",
    )


class MilestoneCompleteRequestSerializer(serializers.Serializer):
    """Request payload to complete an execution milestone."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected milestone version for optimistic concurrency control.",
    )
    actual_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Reported historical occurrence timestamp. Defaults to server now if omitted.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional completion notes or evidence summary.",
    )


class MilestoneBlockRequestSerializer(serializers.Serializer):
    """Request payload to mark milestone BLOCKED."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected milestone version for optimistic concurrency control.",
    )
    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="Mandatory reason describing the blocking issue.",
    )


class MilestoneSkipRequestSerializer(serializers.Serializer):
    """Request payload to mark milestone SKIPPED."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected milestone version for optimistic concurrency control.",
    )
    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="Mandatory reason explaining why the milestone was skipped.",
    )


class TimelineEventSerializer(serializers.Serializer):
    """Single deterministic event in the derived Execution Timeline."""

    event_id = serializers.CharField(help_text="Deterministic event identifier.")
    event_type = serializers.CharField(help_text="Canonical domain event type.")
    type_priority = serializers.IntegerField(help_text="Tie-breaking type priority.")
    event_at = serializers.DateTimeField(help_text="Actual domain occurrence timestamp.")
    recorded_at = serializers.DateTimeField(help_text="Server record timestamp.")
    actor_id = serializers.CharField(allow_null=True, help_text="Actor UUID if available.")
    actor_email = serializers.CharField(allow_null=True, help_text="Actor email if available.")
    milestone_code = serializers.CharField(allow_null=True, help_text="Milestone code if applicable.")
    milestone_name_fa = serializers.CharField(allow_null=True, help_text="Persian milestone name.")
    milestone_name_en = serializers.CharField(allow_null=True, help_text="English milestone name.")
    notes = serializers.CharField(allow_blank=True, help_text="Associated event notes or reasons.")
    metadata = serializers.DictField(help_text="Additional structured event metadata.")


class LogisticsScheduleLoadingSerializer(serializers.Serializer):
    """Request payload to schedule operational loading."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    scheduled_loading_at = serializers.DateTimeField(
        required=True,
        help_text="Scheduled operational loading timestamp.",
    )
    pickup_area_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional structured pickup geographic area UUID.",
    )
    destination_area_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional structured destination geographic area UUID.",
    )
    pickup_location = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional pickup facility or address description.",
    )
    destination_location = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional destination facility or address description.",
    )


class LogisticsRecordLoadingSerializer(serializers.Serializer):
    """Request payload to record actual loading occurrence."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    actual_loading_at = serializers.DateTimeField(
        required=True,
        help_text="Reported actual operational loading timestamp.",
    )


class LogisticsUpdateTransportSerializer(serializers.Serializer):
    """Request payload to update carrier, transport mode, and reference."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    carrier_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Carrier name or freight operator.",
    )
    carrier = serializers.CharField(
        required=False,
        allow_blank=True,
        default=None,
        help_text="Roadmap alias for carrier_name.",
    )
    transport_mode = serializers.ChoiceField(
        choices=TransportMode.choices,
        required=False,
        allow_null=True,
        default=None,
        help_text="Canonical transport mode (ROAD, SEA, RAIL, AIR, MULTIMODAL, OTHER).",
    )
    transport_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Operational transport tracking reference (B/L, CMR, etc.).",
    )


class LogisticsUpdateETASerializer(serializers.Serializer):
    """Request payload to update ETA."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    eta = serializers.DateTimeField(
        required=True,
        help_text="Estimated time of arrival (ETA) at destination.",
    )


class LogisticsRecordDeliverySerializer(serializers.Serializer):
    """Request payload to record actual delivery receipt."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    actual_delivery_at = serializers.DateTimeField(
        required=True,
        help_text="Reported actual operational delivery timestamp.",
    )


class LogisticsUpdateCostSerializer(serializers.Serializer):
    """Request payload to update logistics cost and currency."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    logistics_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0,
        required=True,
        help_text="Actual or reported operational logistics cost in Decimal.",
    )
    currency = serializers.CharField(
        max_length=3,
        min_length=3,
        required=True,
        help_text="ISO 4217 3-letter currency code.",
    )


class LogisticsMutateRequestSerializer(serializers.Serializer):
    """Constrained request payload for PATCH on execution logistics."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected logistics version for optimistic concurrency control.",
    )
    carrier_name = serializers.CharField(required=False, allow_blank=True)
    carrier = serializers.CharField(required=False, allow_blank=True)
    transport_mode = serializers.ChoiceField(choices=TransportMode.choices, required=False, allow_null=True)
    pickup_area_id = serializers.UUIDField(required=False, allow_null=True)
    destination_area_id = serializers.UUIDField(required=False, allow_null=True)
    pickup_location = serializers.CharField(required=False, allow_blank=True)
    destination_location = serializers.CharField(required=False, allow_blank=True)
    scheduled_loading_at = serializers.DateTimeField(required=False, allow_null=True)
    actual_loading_at = serializers.DateTimeField(required=False, allow_null=True)
    eta = serializers.DateTimeField(required=False, allow_null=True)
    actual_delivery_at = serializers.DateTimeField(required=False, allow_null=True)
    transport_reference = serializers.CharField(required=False, allow_blank=True)
    logistics_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)


class InspectionScheduleSerializer(serializers.Serializer):
    """Request payload to schedule inspection."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected inspection version for optimistic concurrency control.",
    )
    scheduled_at = serializers.DateTimeField(
        required=True,
        help_text="Scheduled inspection timestamp.",
    )
    agency = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Inspection agency or organization name (e.g. SGS, Bureau Veritas).",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Operational notes or instructions.",
    )


class InspectionCompleteSerializer(serializers.Serializer):
    """Request payload to complete quality inspection."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected inspection version for optimistic concurrency control.",
    )
    inspection_at = serializers.DateTimeField(
        required=True,
        help_text="Authoritative historical inspection occurrence timestamp.",
    )
    result = serializers.ChoiceField(
        choices=InspectionResult.choices,
        required=True,
        help_text="Authoritative quality inspection result (PASS, FAIL, CONDITIONAL, UNKNOWN).",
    )
    agency = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Inspection agency or organization name.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Operational notes or observations.",
    )


class InspectionCancelSerializer(serializers.Serializer):
    """Request payload to cancel scheduled or pending inspection."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected inspection version for optimistic concurrency control.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Cancellation reason or notes.",
    )


class InspectionMarkNotRequiredSerializer(serializers.Serializer):
    """Request payload to mark inspection as not required / waived."""

    expected_version = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Current expected inspection version for optimistic concurrency control.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Waiver reason or notes.",
    )


class ExecutionErrorResponseSerializer(serializers.Serializer):

    """Standard error response."""

    detail = serializers.CharField(help_text="Detailed error explanation.")

