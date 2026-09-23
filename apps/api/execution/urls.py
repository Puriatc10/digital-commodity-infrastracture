from django.urls import path

from execution.api.views import (
    ExecutionWorkflowTemplateActiveVersionView,
    ExecutionWorkflowTemplateDetailView,
    ExecutionWorkflowTemplateListView,
    ExecutionWorkflowTemplateVersionDetailView,
)

urlpatterns = [
    path("templates/", ExecutionWorkflowTemplateListView.as_view(), name="execution-workflow-template-list"),
    path("templates/<str:code_or_id>/", ExecutionWorkflowTemplateDetailView.as_view(), name="execution-workflow-template-detail"),
    path("templates/<str:code>/active-version/", ExecutionWorkflowTemplateActiveVersionView.as_view(), name="execution-workflow-template-active-version"),
    path("versions/<uuid:version_id>/", ExecutionWorkflowTemplateVersionDetailView.as_view(), name="execution-workflow-version-detail"),
]
