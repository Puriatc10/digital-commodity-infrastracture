from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from execution.api.serializers import (
    ExecutionWorkflowTemplateDetailSerializer,
    ExecutionWorkflowTemplateSummarySerializer,
    ExecutionWorkflowTemplateVersionSerializer,
)
from execution.exceptions import (
    NoActiveWorkflowVersionError,
    WorkflowTemplateInactiveError,
    WorkflowTemplateNotFoundError,
    WorkflowVersionNotFoundError,
)
from execution.models import (
    ExecutionWorkflowTemplate,
)
from execution.permissions import IsOperatorOrAdmin
from execution.services import (
    get_active_workflow_template_version,
    get_workflow_template,
    get_workflow_version,
)


class ExecutionWorkflowTemplateListView(APIView):
    """List execution workflow templates (Internal Operator/Admin only)."""

    permission_classes = [IsOperatorOrAdmin]

    @extend_schema(
        summary="List execution workflow templates",
        description="List all workflow templates configured on the platform. Restricted to Operator and Admin.",
        responses={200: ExecutionWorkflowTemplateSummarySerializer(many=True)},
    )
    def get(self, request):
        templates = ExecutionWorkflowTemplate.objects.all().order_by("code")
        serializer = ExecutionWorkflowTemplateSummarySerializer(templates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionWorkflowTemplateDetailView(APIView):
    """Retrieve execution workflow template details (Internal Operator/Admin only)."""

    permission_classes = [IsOperatorOrAdmin]

    @extend_schema(
        summary="Retrieve execution workflow template detail",
        description="Retrieve details of a workflow template by code or UUID. Restricted to Operator and Admin.",
        responses={
            200: ExecutionWorkflowTemplateDetailSerializer,
            404: OpenApiResponse(description="Workflow template not found"),
        },
    )
    def get(self, request, code_or_id: str):
        try:
            template = get_workflow_template(code_or_id)
        except WorkflowTemplateNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionWorkflowTemplateDetailSerializer(template)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionWorkflowTemplateVersionDetailView(APIView):
    """Retrieve full execution workflow template version including milestone graph."""

    permission_classes = [IsOperatorOrAdmin]

    @extend_schema(
        summary="Retrieve workflow template version detail",
        description="Retrieve full version details with milestone graph and prerequisite dependencies.",
        responses={
            200: ExecutionWorkflowTemplateVersionSerializer,
            404: OpenApiResponse(description="Workflow version not found"),
        },
    )
    def get(self, request, version_id):
        try:
            version = get_workflow_version(version_id)
        except WorkflowVersionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionWorkflowTemplateVersionSerializer(version)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionWorkflowTemplateActiveVersionView(APIView):
    """Retrieve active published workflow template version by template code."""

    permission_classes = [IsOperatorOrAdmin]

    @extend_schema(
        summary="Retrieve active published workflow template version",
        description="Deterministically retrieves the active published version for a template code.",
        responses={
            200: ExecutionWorkflowTemplateVersionSerializer,
            404: OpenApiResponse(description="Active version or template not found"),
        },
    )
    def get(self, request, code: str):
        try:
            active_version = get_active_workflow_template_version(code)
        except (WorkflowTemplateNotFoundError, WorkflowTemplateInactiveError, NoActiveWorkflowVersionError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionWorkflowTemplateVersionSerializer(active_version)
        return Response(serializer.data, status=status.HTTP_200_OK)
