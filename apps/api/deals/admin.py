from django.contrib import admin

from deals.models import (
    Deal,
    DealAttribution,
    DealCostSnapshot,
    DealPartySnapshot,
    DealTermsSnapshot,
)


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("id", "award_id", "buyer_organization", "seller_display_name", "created_at")
    search_fields = ("id", "award__id", "buyer_organization__name")
    readonly_fields = [f.name for f in Deal._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DealTermsSnapshot)
class DealTermsSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "deal_id", "commodity", "quantity", "quantity_unit", "unit_price", "currency", "created_at")
    search_fields = ("id", "deal__id")
    readonly_fields = [f.name for f in DealTermsSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DealPartySnapshot)
class DealPartySnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "deal_id", "role", "party_type", "name_snapshot", "country_snapshot", "created_at")
    list_filter = ("role", "party_type")
    search_fields = ("id", "deal__id", "name_snapshot")
    readonly_fields = [f.name for f in DealPartySnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DealCostSnapshot)
class DealCostSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "deal_terms_snapshot_id", "kind", "amount", "currency", "created_at")
    list_filter = ("kind",)
    search_fields = ("id", "deal_terms_snapshot__id")
    readonly_fields = [f.name for f in DealCostSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DealAttribution)
class DealAttributionAdmin(admin.ModelAdmin):
    list_display = ("id", "deal_id", "status", "primary_channel", "resolution_method", "resolved_at", "created_at")
    list_filter = ("status", "primary_channel", "resolution_method")
    search_fields = ("id", "deal__id", "resolution_reason")
    readonly_fields = [f.name for f in DealAttribution._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

