from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import OrganizationVerification, VerificationDecision, VerificationNote

class VerificationDecisionSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source='actor.email', read_only=True)

    class Meta:
        model = VerificationDecision
        fields = ['id', 'actor_email', 'action', 'previous_status', 'new_status', 'reason', 'created_at']
        read_only_fields = fields

class VerificationNoteSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source='actor.email', read_only=True)

    class Meta:
        model = VerificationNote
        fields = ['id', 'actor_email', 'note', 'created_at']
        read_only_fields = ['id', 'actor_email', 'created_at']

class VerificationNoteCreateSerializer(serializers.Serializer):
    note = serializers.CharField(required=True, allow_blank=False)

class OrganizationVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationVerification
        fields = ['id', 'status', 'version', 'updated_at']
        read_only_fields = fields

class OrganizationVerificationDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationVerification
        fields = ['id', 'status', 'version', 'updated_at']
        read_only_fields = fields

class InternalOrganizationVerificationDetailSerializer(serializers.ModelSerializer):
    decisions = VerificationDecisionSerializer(many=True, read_only=True)
    notes = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationVerification
        fields = ['id', 'status', 'version', 'updated_at', 'decisions', 'notes']
        read_only_fields = fields

    @property
    def _notes(self):
        pass # Placeholder for drf-spectacular

    @extend_schema_field(VerificationNoteSerializer(many=True))
    def get_notes(self, obj):
        return VerificationNoteSerializer(obj.notes.all(), many=True).data

class VerificationSubmitSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=False, allow_null=True)

class VerificationActionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=True, allow_null=False)

class ChecklistReviewSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=["accepted", "rejected"])
    expected_version = serializers.IntegerField(required=True, allow_null=False)

class VerificationQueueSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source='organization.id', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = OrganizationVerification
        fields = ['id', 'organization_id', 'organization_name', 'status', 'version', 'updated_at']
        read_only_fields = fields

class VerificationRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)
    expected_version = serializers.IntegerField(required=True, allow_null=False)

class VerificationSuspendSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)
    expected_version = serializers.IntegerField(required=True, allow_null=False)

class VerificationErrorDetailSerializer(serializers.Serializer):
    detail = serializers.CharField()
