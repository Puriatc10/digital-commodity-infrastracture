from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.utils.translation import gettext_lazy as _

from drf_spectacular.utils import extend_schema_field
from organizations.models import OrganizationMembership
from organizations.api.serializers import OrganizationSerializer


User = get_user_model()


class OrganizationContextSerializer(serializers.Serializer):
    organization = OrganizationSerializer()
    role = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())

class UserSerializer(serializers.ModelSerializer):
    system_roles = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "is_active", "system_roles", "organizations")
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_system_roles(self, obj):
        if hasattr(obj, "system_roles"):
            return list(obj.system_roles.values_list("role", flat=True))
        return []

    @extend_schema_field(OrganizationContextSerializer(many=True))
    def get_organizations(self, obj):
        memberships = OrganizationMembership.objects.filter(
            user=obj,
            is_active=True,
            organization__is_active=True
        ).select_related("organization").prefetch_related("organization__capabilities")

        result = []
        for membership in memberships:
            org = membership.organization
            capabilities = [item.capability for item in org.capabilities.all()]
            result.append({
                "organization": org,
                "role": membership.role,
                "capabilities": capabilities
            })

        return OrganizationContextSerializer(result, many=True).data


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"}, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if email and password:
            user = authenticate(request=self.context.get("request"), email=email, password=password)

            if not user:
                msg = _("Unable to log in with provided credentials.")
                raise serializers.ValidationError(msg, code="authorization")
        else:
            msg = _("Must include 'email' and 'password'.")
            raise serializers.ValidationError(msg, code="authorization")

        attrs["user"] = user
        return attrs
