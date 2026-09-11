from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from organizations.models import Organization

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "registration_identifier",
            "website",
            "country",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]



class DirectoryOrganizationSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()
    commodities = serializers.SerializerMethodField()
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "country",
            "capabilities",
            "commodities",
            "verification_status",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_capabilities(self, obj):
        return list(obj.capabilities.values_list("capability", flat=True))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_commodities(self, obj):
        return list(obj.commodities.values_list("commodity__code", flat=True))

    @extend_schema_field(serializers.CharField())
    def get_verification_status(self, obj):
        if hasattr(obj, "verification"):
            return obj.verification.status
        return "unverified"
