from django.contrib import admin

from .models import (
    Execution,
    ExecutionInspection,
    ExecutionLogistics,
    ExecutionMilestone,
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


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "deal", "workflow_template_version", "status", "version", "started_at", "closed_at")
    list_filter = ("status",)
    search_fields = ("id", "deal__id")


@admin.register(ExecutionMilestone)
class ExecutionMilestoneAdmin(admin.ModelAdmin):
    list_display = ("id", "execution", "definition", "status", "expected_at", "actual_at", "version")
    list_filter = ("status",)
    search_fields = ("execution__id", "definition__code")


@admin.register(ExecutionLogistics)
class ExecutionLogisticsAdmin(admin.ModelAdmin):
    list_display = ("id", "execution", "carrier_name", "transport_mode", "scheduled_loading_at", "actual_loading_at", "eta", "actual_delivery_at", "version")
    list_filter = ("transport_mode",)
    search_fields = ("execution__id", "carrier_name", "transport_reference")


@admin.register(ExecutionInspection)
class ExecutionInspectionAdmin(admin.ModelAdmin):
    list_display = ("id", "execution", "agency", "status", "result", "required", "scheduled_at", "inspection_at", "version")
    list_filter = ("status", "result", "required")
    search_fields = ("execution__id", "agency", "notes")

