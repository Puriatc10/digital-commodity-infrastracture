from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

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


class ExecutionErrorResponseSerializer(serializers.Serializer):
    """Standard error response."""

    detail = serializers.CharField(help_text="Detailed error explanation.")

