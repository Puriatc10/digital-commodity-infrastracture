from rest_framework import serializers

from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


class CommodityAttributeDefinitionSerializer(serializers.ModelSerializer):
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
