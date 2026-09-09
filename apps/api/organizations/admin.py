from django.contrib import admin

from .models import Organization, OrganizationCapability, OrganizationMembership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "registration_identifier", "country", "is_active", "created_at")
    list_filter = ("is_active", "country")
    search_fields = ("name", "registration_identifier")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__email", "organization__name")


@admin.register(OrganizationCapability)
class OrganizationCapabilityAdmin(admin.ModelAdmin):
    list_display = ("organization", "capability", "created_at")
    list_filter = ("capability",)
    search_fields = ("organization__name",)
