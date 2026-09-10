from django.contrib import admin

from .models import SystemRoleAssignment


@admin.register(SystemRoleAssignment)
class SystemRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email",)
