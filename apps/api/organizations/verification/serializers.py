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

class OrganizationVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationVerification
        fields = ['id', 'status', 'version', 'updated_at']
        read_only_fields = fields

class OrganizationVerificationDetailSerializer(serializers.ModelSerializer):
    decisions = VerificationDecisionSerializer(many=True, read_only=True)
    notes = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationVerification
        fields = ['id', 'status', 'version', 'updated_at', 'decisions', 'notes']
        read_only_fields = fields

    def get_notes(self, obj) -> list[dict]:
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Only operator or admin can see notes
            if request.user.system_roles.filter(role__in=['operator', 'admin']).exists():
                return VerificationNoteSerializer(obj.notes.all(), many=True).data
        return None

class VerificationActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
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
