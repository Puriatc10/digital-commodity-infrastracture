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
