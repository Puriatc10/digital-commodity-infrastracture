from django.contrib import admin

from .models import (
    ExecutionMilestoneDefinition,
    ExecutionMilestoneDependency,
    ExecutionWorkflowTemplate,
    ExecutionWorkflowTemplateVersion,
)


class ExecutionMilestoneDefinitionInline(admin.TabularInline):
    model = ExecutionMilestoneDefinition
    extra = 0
    fields = ("code", "name_fa", "name_en", "sort_order", "required", "blocking", "terminal")


@admin.register(ExecutionWorkflowTemplate)
class ExecutionWorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "name_en", "name_fa", "is_active", "active_version", "created_at")
    search_fields = ("code", "name_en", "name_fa")
    list_filter = ("is_active",)


@admin.register(ExecutionWorkflowTemplateVersion)
class ExecutionWorkflowTemplateVersionAdmin(admin.ModelAdmin):
    list_display = ("template", "version_number", "status", "published_at", "retired_at")
    list_filter = ("status", "template")
    inlines = [ExecutionMilestoneDefinitionInline]


@admin.register(ExecutionMilestoneDefinition)
class ExecutionMilestoneDefinitionAdmin(admin.ModelAdmin):
    list_display = ("workflow_template_version", "code", "sort_order", "required", "blocking", "terminal")
    list_filter = ("workflow_template_version__template", "workflow_template_version__status")
    search_fields = ("code", "name_en", "name_fa")


@admin.register(ExecutionMilestoneDependency)
class ExecutionMilestoneDependencyAdmin(admin.ModelAdmin):
    list_display = ("milestone", "prerequisite", "created_at")
