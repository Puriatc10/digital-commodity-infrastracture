from rest_framework import serializers

from geography.models import GeographicArea


class GeographicAreaSummarySerializer(serializers.ModelSerializer):
    """Concise representation of a geographic area (e.g. for parent linkage)."""

    class Meta:
        model = GeographicArea
        fields = [
            "id",
            "code",
            "area_type",
            "country_code",
            "name_en",
            "name_fa",
        ]
        read_only_fields = fields


class GeographicAreaSerializer(serializers.ModelSerializer):
    """Full representation of a geographic area including its parent summary."""

    parent = GeographicAreaSummarySerializer(read_only=True)

    class Meta:
        model = GeographicArea
        fields = [
            "id",
            "code",
            "area_type",
            "country_code",
            "name_en",
            "name_fa",
            "is_active",
            "parent",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
