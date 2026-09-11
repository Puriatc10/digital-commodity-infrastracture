from rest_framework import serializers
from documents.models import VerificationDocument, DocumentType

class VerificationDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationDocument
        fields = [
            "id", "organization", "type", "file_name", "object_key",
            "mime_type", "size_bytes", "uploaded_by", "verification_status",
            "verification_version", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "object_key", "mime_type", "size_bytes", "uploaded_by",
            "verification_status", "verification_version", "created_at", "updated_at"
        ]

class UploadDocumentSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=DocumentType.choices)
    file = serializers.FileField()
    organization = serializers.UUIDField()
