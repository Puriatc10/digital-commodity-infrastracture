from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from execution.api.serializers import (
    ExecutionCreateRequestSerializer,
    ExecutionDetailSerializer,
    ExecutionErrorResponseSerializer,
    ExecutionMilestoneSerializer,
    ExecutionWorkflowTemplateDetailSerializer,
    ExecutionWorkflowTemplateSummarySerializer,
    ExecutionWorkflowTemplateVersionSerializer,
    MilestoneBlockRequestSerializer,
    MilestoneCompleteRequestSerializer,
    MilestoneSkipRequestSerializer,
    MilestoneStartRequestSerializer,
    TimelineEventSerializer,
)
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionNotFoundError,
    ExecutionPermissionDeniedError,
    ExecutionValidationError,
    InvalidMilestoneTransitionError,
    MilestoneAlreadyCompletedError,
    MilestoneNotFoundError,
    MilestonePrerequisiteUnmetError,
    NoActiveWorkflowVersionError,
    StaleVersionError,
    WorkflowTemplateInactiveError,
    WorkflowTemplateNotFoundError,
    WorkflowVersionNotFoundError,
)
from execution.models import (
    ExecutionWorkflowTemplate,
)
from execution.permissions import IsOperatorOrAdmin
from execution.services import (
    block_milestone,
    complete_milestone,
    create_or_get_execution_for_deal,
    get_active_workflow_template_version,
    get_execution_by_id,
    get_execution_for_deal,
    get_workflow_template,
    get_workflow_version,
    project_execution_timeline,
    skip_milestone,
    start_milestone,
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


# =============================================================================
# Execution Runtime Views (T1003)
# =============================================================================


class DealExecutionCreateOrGetView(APIView):
    """
    Idempotent Deal Execution creation and retrieval endpoint (Epic 10 Contract §7, T1003).

    POST /api/deals/{deal_id}/execution/
    GET  /api/deals/{deal_id}/execution/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_create_or_get",
        tags=["Execution"],
        summary="Create or Retrieve Deal Execution Aggregate",
        description=(
            "Idempotently creates or retrieves the single Execution aggregate for an immutable Deal. "
            "Binds to the currently active PUBLISHED workflow template version or an explicitly specified "
            "published version. Materializes milestone instances and auto-completes the initial AWARDED milestone "
            "using the authoritative Award source timestamp. "
            "Subsequent calls return the existing Execution instance without duplicating rows or re-materializing. "
            "Concurrency is protected with PostgreSQL database locks."
        ),
        request=ExecutionCreateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ExecutionDetailSerializer,
                description="Execution aggregate created or retrieved successfully.",
            ),
            201: OpenApiResponse(
                response=ExecutionDetailSerializer,
                description="Execution aggregate newly materialized.",
            ),
            400: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Validation failure or inactive workflow template.",
            ),
            403: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Actor lacks authorization for this Deal's execution.",
            ),
            404: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Referenced Deal or workflow version not found.",
            ),
        },
    )
    def post(self, request, deal_id):
        serializer = ExecutionCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            execution = create_or_get_execution_for_deal(
                deal_id=deal_id,
                workflow_template_code=data.get("workflow_template_code"),
                workflow_template_id=data.get("workflow_template_id"),
                workflow_template_version_id=data.get("workflow_template_version_id"),
                actor=request.user,
            )
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionValidationError, WorkflowTemplateInactiveError, NoActiveWorkflowVersionError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        except (WorkflowTemplateNotFoundError, WorkflowVersionNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        out_serializer = ExecutionDetailSerializer(execution)
        return Response(out_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="execution_get_by_deal",
        tags=["Execution"],
        summary="Retrieve Deal Execution Aggregate",
        description="Retrieves the Execution aggregate and materialized milestone graph for a Deal.",
        responses={
            200: ExecutionDetailSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, deal_id):
        try:
            execution = get_execution_for_deal(deal_id, actor=request.user)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionDetailSerializer(execution)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionDetailView(APIView):
    """Retrieve Execution aggregate by execution UUID."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_detail",
        tags=["Execution"],
        summary="Retrieve Execution Aggregate by ID",
        description="Retrieves Execution aggregate and materialized milestone graph by Execution UUID.",
        responses={
            200: ExecutionDetailSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, execution_id):
        try:
            execution = get_execution_by_id(execution_id, actor=request.user)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionDetailSerializer(execution)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionTimelineView(APIView):
    """Retrieve deterministic Execution Timeline projection."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_timeline",
        tags=["Execution"],
        summary="Retrieve Deterministic Execution Timeline",
        description=(
            "Projects the deterministic domain timeline for an Execution instance. "
            "Combines execution creation, milestone status facts, and execution closure. "
            "Sorted strictly by (event_at ASC, stable_type_priority, stable_id ASC). "
            "Rendered historically using the bound workflow template version's definition metadata."
        ),
        responses={
            200: OpenApiResponse(
                response=TimelineEventSerializer(many=True),
                description="Deterministic timeline event list.",
            ),
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, execution_id):
        try:
            timeline = project_execution_timeline(execution_id, actor=request.user)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = TimelineEventSerializer(timeline, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MilestoneStartActionView(APIView):
    """Transition milestone from PENDING to IN_PROGRESS."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_milestone_start",
        tags=["Execution"],
        summary="Start Milestone Execution",
        description=(
            "Transitions a milestone from PENDING to IN_PROGRESS. "
            "Requires current expected_version for optimistic concurrency control."
        ),
        request=MilestoneStartRequestSerializer,
        responses={
            200: ExecutionMilestoneSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def post(self, request, execution_id, milestone_id):
        serializer = MilestoneStartRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            milestone = start_milestone(
                execution_id=execution_id,
                milestone_id=milestone_id,
                expected_version=data["expected_version"],
                actor=request.user,
                notes=data.get("notes"),
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except MilestoneAlreadyCompletedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, MilestoneNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            MilestonePrerequisiteUnmetError,
            InvalidMilestoneTransitionError,
            CrossObjectIntegrityError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionMilestoneSerializer(milestone)
        return Response(out.data, status=status.HTTP_200_OK)


class MilestoneCompleteActionView(APIView):
    """Complete an execution milestone."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_milestone_complete",
        tags=["Execution"],
        summary="Complete Execution Milestone",
        description=(
            "Authoritatively marks an execution milestone COMPLETED. "
            "Requires current expected_version for optimistic concurrency control. "
            "If the milestone definition has terminal=True, the execution status is atomically set to CLOSED. "
            "Completed milestones are strictly immutable and cannot be reopened."
        ),
        request=MilestoneCompleteRequestSerializer,
        responses={
            200: ExecutionMilestoneSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version) or already completed.",
            ),
        },
    )
    def post(self, request, execution_id, milestone_id):
        serializer = MilestoneCompleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            milestone = complete_milestone(
                execution_id=execution_id,
                milestone_id=milestone_id,
                expected_version=data["expected_version"],
                actor=request.user,
                actual_at=data.get("actual_at"),
                notes=data.get("notes"),
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except MilestoneAlreadyCompletedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, MilestoneNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            MilestonePrerequisiteUnmetError,
            InvalidMilestoneTransitionError,
            CrossObjectIntegrityError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionMilestoneSerializer(milestone)
        return Response(out.data, status=status.HTTP_200_OK)


class MilestoneBlockActionView(APIView):
    """Mark milestone BLOCKED."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_milestone_block",
        tags=["Execution"],
        summary="Mark Milestone Blocked",
        description="Marks an execution milestone BLOCKED with a mandatory non-empty reason.",
        request=MilestoneBlockRequestSerializer,
        responses={
            200: ExecutionMilestoneSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id, milestone_id):
        serializer = MilestoneBlockRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            milestone = block_milestone(
                execution_id=execution_id,
                milestone_id=milestone_id,
                expected_version=data["expected_version"],
                actor=request.user,
                reason=data["reason"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except MilestoneAlreadyCompletedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, MilestoneNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionMilestoneSerializer(milestone)
        return Response(out.data, status=status.HTTP_200_OK)


class MilestoneSkipActionView(APIView):
    """Mark milestone SKIPPED."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_milestone_skip",
        tags=["Execution"],
        summary="Mark Milestone Skipped",
        description="Marks an execution milestone SKIPPED with a mandatory reason.",
        request=MilestoneSkipRequestSerializer,
        responses={
            200: ExecutionMilestoneSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id, milestone_id):
        serializer = MilestoneSkipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            milestone = skip_milestone(
                execution_id=execution_id,
                milestone_id=milestone_id,
                expected_version=data["expected_version"],
                actor=request.user,
                reason=data["reason"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except MilestoneAlreadyCompletedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, MilestoneNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionMilestoneSerializer(milestone)
        return Response(out.data, status=status.HTTP_200_OK)


class DealMilestoneCompleteActionView(APIView):
    """Deal-scoped milestone completion action view (guards against cross-object manipulation)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deal_execution_milestone_complete",
        tags=["Execution"],
        summary="Complete Milestone via Deal Scope",
        description="Completes an execution milestone scoped to a specific Deal ID.",
        request=MilestoneCompleteRequestSerializer,
        responses={
            200: ExecutionMilestoneSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, deal_id, milestone_id):
        try:
            execution = get_execution_for_deal(deal_id, actor=request.user)
        except ExecutionNotFoundError:
            return Response({"detail": f"Execution for deal '{deal_id}' not found."}, status=status.HTTP_404_NOT_FOUND)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)

        serializer = MilestoneCompleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            milestone = complete_milestone(
                execution_id=execution.id,
                milestone_id=milestone_id,
                expected_version=data["expected_version"],
                actor=request.user,
                actual_at=data.get("actual_at"),
                notes=data.get("notes"),
                deal_id=deal_id,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except MilestoneAlreadyCompletedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, MilestoneNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            MilestonePrerequisiteUnmetError,
            InvalidMilestoneTransitionError,
            CrossObjectIntegrityError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionMilestoneSerializer(milestone)
        return Response(out.data, status=status.HTTP_200_OK)

