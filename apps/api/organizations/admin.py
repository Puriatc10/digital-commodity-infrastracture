from django.contrib import admin
from .models import Organization, OrganizationMembership, OrganizationCapability
from .verification.models import OrganizationVerification, VerificationDecision, VerificationNote

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "is_active", "created_at")
    list_filter = ("is_active", "country")
    search_fields = ("name", "registration_identifier")

@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("organization__name", "user__email")

@admin.register(OrganizationCapability)
class OrganizationCapabilityAdmin(admin.ModelAdmin):
    list_display = ("organization", "capability")
    list_filter = ("capability",)
    search_fields = ("organization__name",)

@admin.register(OrganizationVerification)
class OrganizationVerificationAdmin(admin.ModelAdmin):
    list_display = ("organization", "status", "version")
    list_filter = ("status",)
    search_fields = ("organization__name",)

@admin.register(VerificationDecision)
class VerificationDecisionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    list_display = ("verification", "actor", "previous_status", "new_status", "created_at")
    list_filter = ("new_status",)
    search_fields = ("verification__organization__name", "actor__email")

@admin.register(VerificationNote)
class VerificationNoteAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    list_display = ("verification", "actor", "created_at")
    search_fields = ("verification__organization__name", "actor__email", "note")
