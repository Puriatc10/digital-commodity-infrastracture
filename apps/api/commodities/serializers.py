from rest_framework import serializers

from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


class UnitMetadataSerializer(serializers.Serializer):
    canonical_unit = serializers.CharField(required=False)
    unit_family = serializers.CharField(required=False)
    allowed_units = serializers.ListField(child=serializers.CharField(), required=False)


class EnumOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label_fa = serializers.CharField(required=False)
    label_en = serializers.CharField(required=False)
    sort_order = serializers.IntegerField(required=False, min_value=0)


class EnumMetadataSerializer(serializers.Serializer):
    options = EnumOptionSerializer(many=True, required=False)


class ValidationMetadataSerializer(serializers.Serializer):
    minimum = serializers.FloatField(required=False)
    maximum = serializers.FloatField(required=False)
    minLength = serializers.IntegerField(required=False, min_value=0)
    maxLength = serializers.IntegerField(required=False, min_value=0)


class CommodityAttributeDefinitionSerializer(serializers.ModelSerializer):
    unit_metadata = UnitMetadataSerializer(read_only=True)
    enum_metadata = EnumMetadataSerializer(read_only=True)
    validation_metadata = ValidationMetadataSerializer(read_only=True)

    class Meta:
        model = CommodityAttributeDefinition
        fields = [
            "id",
            "key",
            "label_fa",
            "label_en",
            "data_type",
            "is_required",
            "unit_metadata",
            "enum_metadata",
            "validation_metadata",
            "display_group",
            "sort_order",
        ]


class CommoditySchemaVersionSerializer(serializers.ModelSerializer):
    attributes = CommodityAttributeDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model = CommoditySchemaVersion
        fields = [
            "id",
            "commodity_id",
            "version",
            "status",
            "attributes",
        ]


class CommodityDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommodityDefinition
        fields = [
            "id",
            "code",
            "name_fa",
            "name_en",
            "is_active",
        ]
