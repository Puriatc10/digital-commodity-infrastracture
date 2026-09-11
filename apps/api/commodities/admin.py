from django.contrib import admin
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


@admin.register(CommodityDefinition)
class CommodityDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name_en", "name_fa", "is_active", "active_schema_version", "created_at")
    search_fields = ("code", "name_en", "name_fa")
    list_filter = ("is_active",)


class CommodityAttributeDefinitionInline(admin.TabularInline):
    model = CommodityAttributeDefinition
    extra = 0

    def has_add_permission(self, request, obj=None):
        if obj and obj.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(CommoditySchemaVersion)
class CommoditySchemaVersionAdmin(admin.ModelAdmin):
    list_display = ("commodity", "version", "status", "created_at")
    list_filter = ("status", "commodity")
    search_fields = ("commodity__code", "commodity__name_en")
    inlines = [CommodityAttributeDefinitionInline]
    # Lifecycle uses the transactional domain functions, after draft inline edits.
    readonly_fields = ("status",)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return [f.name for f in self.model._meta.fields]
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(CommodityAttributeDefinition)
class CommodityAttributeDefinitionAdmin(admin.ModelAdmin):
    list_display = ("key", "schema_version", "data_type", "is_required", "display_group", "sort_order")
    list_filter = ("data_type", "is_required", "schema_version__commodity")
    search_fields = ("key", "label_en", "label_fa")
    ordering = ("schema_version", "sort_order", "key")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.schema_version.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return [f.name for f in self.model._meta.fields]
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        if obj and obj.schema_version.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.schema_version.status in [CommoditySchemaVersion.SchemaStatus.PUBLISHED, CommoditySchemaVersion.SchemaStatus.RETIRED]:
            return False
        return super().has_change_permission(request, obj)
