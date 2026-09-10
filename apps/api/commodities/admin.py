from django.contrib import admin
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


@admin.register(CommodityDefinition)
class CommodityDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name_en", "name_fa", "is_active", "active_schema_version", "created_at")
    search_fields = ("code", "name_en", "name_fa")
    list_filter = ("is_active",)


@admin.register(CommoditySchemaVersion)
class CommoditySchemaVersionAdmin(admin.ModelAdmin):
    list_display = ("commodity", "version", "status", "created_at")
    list_filter = ("status", "commodity")
    search_fields = ("commodity__code", "commodity__name_en")


@admin.register(CommodityAttributeDefinition)
class CommodityAttributeDefinitionAdmin(admin.ModelAdmin):
    list_display = ("key", "schema_version", "data_type", "is_required", "display_group", "sort_order")
    list_filter = ("data_type", "is_required", "schema_version__commodity")
    search_fields = ("key", "label_en", "label_fa")
    ordering = ("schema_version", "sort_order", "key")
