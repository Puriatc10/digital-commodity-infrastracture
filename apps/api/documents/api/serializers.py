from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers
from documents.models import VerificationDocument, DocumentType

BinaryFileField = extend_schema_field(OpenApiTypes.BINARY)(serializers.FileField)

class VerificationDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationDocument
        fields = [
            "id", "organization", "type", "file_name",
            "mime_type", "size_bytes", "uploaded_by", "verification_status",
            "verification_version", "is_current", "created_at", "updated_at"
        ]
        read_only_fields = [
            "id", "mime_type", "size_bytes", "uploaded_by",
            "verification_status", "verification_version", "is_current", "created_at", "updated_at"
        ]

class UploadDocumentSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=DocumentType.choices)
    file = BinaryFileField(help_text="Binary document file (PDF, JPEG, PNG, max 10MB)")
    organization = serializers.UUIDField()
