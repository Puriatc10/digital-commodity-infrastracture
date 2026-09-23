from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from execution.api.serializers import (
    ExecutionCreateRequestSerializer,
    ExecutionDetailSerializer,
    ExecutionErrorResponseSerializer,
    ExecutionInspectionSerializer,
    ExecutionLogisticsSerializer,
    ExecutionMilestoneSerializer,
    ExecutionWorkflowTemplateDetailSerializer,
    ExecutionWorkflowTemplateSummarySerializer,
    ExecutionWorkflowTemplateVersionSerializer,
    InspectionCancelSerializer,
    InspectionCompleteSerializer,
    InspectionMarkNotRequiredSerializer,
    InspectionScheduleSerializer,
    LogisticsMutateRequestSerializer,
    LogisticsRecordDeliverySerializer,
    LogisticsRecordLoadingSerializer,
    LogisticsScheduleLoadingSerializer,
    LogisticsUpdateCostSerializer,
    LogisticsUpdateETASerializer,
    LogisticsUpdateTransportSerializer,
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
    InspectionNotFoundError,
    InvalidInspectionTransitionError,
    InvalidMilestoneTransitionError,
    LogisticsNotFoundError,
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
    cancel_inspection,
    complete_inspection,
    complete_milestone,
    create_or_get_execution_for_deal,
    get_active_workflow_template_version,
    get_execution_by_id,
    get_execution_for_deal,
    get_or_create_execution_inspection,
    get_or_create_execution_logistics,
    get_workflow_template,
    get_workflow_version,
    mark_inspection_not_required,
    mutate_logistics,
    project_execution_timeline,
    record_delivery,
    record_loading,
    schedule_inspection,
    schedule_loading,

    skip_milestone,
    start_milestone,
    update_eta,
    update_logistics_cost,
    update_transport,
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


# =============================================================================
# Execution Logistics Operational Views (T1004)
# =============================================================================


class ExecutionLogisticsDetailView(APIView):
    """
    Operational logistics detail and constrained mutation endpoint (Epic 10 Contract §35, §42, T1004).

    GET   /api/execution/{execution_id}/logistics/
    PATCH /api/execution/{execution_id}/logistics/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_detail",
        tags=["Logistics"],
        summary="Retrieve Execution Logistics Operational Record",
        description=(
            "Idempotently retrieves or initializes the operational ExecutionLogistics aggregate for an Execution. "
            "Unknown fields remain null/empty without fabricated defaults."
        ),
        responses={
            200: ExecutionLogisticsSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, execution_id):
        try:
            logistics = get_or_create_execution_logistics(execution_id, actor=request.user)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionLogisticsSerializer(logistics)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="execution_logistics_patch",
        tags=["Logistics"],
        summary="Constrained Mutation of Execution Logistics",
        description=(
            "Mutates operational logistics facts under optimistic concurrency control (expected_version). "
            "Mass-assignment of server-owned fields (id, execution, version, created_at, updated_at) is strictly rejected. "
            "Side-specific authority is verified field-by-field."
        ),
        request=LogisticsMutateRequestSerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def patch(self, request, execution_id):
        serializer = LogisticsMutateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        expected_version = data.pop("expected_version")

        try:
            logistics = mutate_logistics(
                execution_id=execution_id,
                expected_version=expected_version,
                data=data,
                actor=request.user,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, LogisticsNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, CrossObjectIntegrityError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsScheduleLoadingActionView(APIView):
    """Schedule loading date/time and locations (Seller/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_schedule_loading",
        tags=["Logistics"],
        summary="Schedule Operational Loading",
        description=(
            "Records scheduled operational loading timestamp and optional pickup/destination locations. "
            "Requires Seller or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsScheduleLoadingSerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsScheduleLoadingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            logistics = schedule_loading(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                scheduled_loading_at=data["scheduled_loading_at"],
                pickup_area_id=data.get("pickup_area_id"),
                destination_area_id=data.get("destination_area_id"),
                pickup_location=data.get("pickup_location"),
                destination_location=data.get("destination_location"),
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsRecordLoadingActionView(APIView):
    """Record actual loading occurrence (Seller/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_record_loading",
        tags=["Logistics"],
        summary="Record Actual Operational Loading",
        description=(
            "Records actual operational loading timestamp. "
            "Guards chronology: actual_delivery_at cannot precede actual_loading_at. "
            "Requires Seller or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsRecordLoadingSerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsRecordLoadingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            logistics = record_loading(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                actual_loading_at=data["actual_loading_at"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsUpdateTransportActionView(APIView):
    """Update carrier, transport mode, and tracking reference (Seller/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_update_transport",
        tags=["Logistics"],
        summary="Update Transport Carrier, Mode, and Reference",
        description=(
            "Updates transport details. Transport mode must be one of canonical TransportMode enum. "
            "Requires Seller or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsUpdateTransportSerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsUpdateTransportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        carrier_val = data.get("carrier_name") or data.get("carrier")

        try:
            logistics = update_transport(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                carrier_name=carrier_val,
                transport_mode=data.get("transport_mode"),
                transport_reference=data.get("transport_reference"),
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsUpdateETAActionView(APIView):
    """Update Estimated Time of Arrival (ETA) (Seller/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_update_eta",
        tags=["Logistics"],
        summary="Update Estimated Time of Arrival (ETA)",
        description=(
            "Updates ETA for operational shipment arrival. "
            "Rejected if actual delivery has already been recorded. "
            "Requires Seller or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsUpdateETASerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsUpdateETASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            logistics = update_eta(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                eta=data["eta"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsRecordDeliveryActionView(APIView):
    """Record actual delivery receipt (Buyer/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_record_delivery",
        tags=["Logistics"],
        summary="Record Actual Operational Delivery",
        description=(
            "Records actual delivery arrival timestamp. "
            "Chronology validated: actual_delivery_at cannot precede actual_loading_at. "
            "Does NOT imply goods acceptance (milestone ACCEPTED remains separate). "
            "Requires Buyer or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsRecordDeliverySerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsRecordDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            logistics = record_delivery(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                actual_delivery_at=data["actual_delivery_at"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionLogisticsUpdateCostActionView(APIView):
    """Update operational logistics cost and currency (Seller/Operator)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_logistics_update_cost",
        tags=["Logistics"],
        summary="Update Operational Logistics Cost",
        description=(
            "Updates actual or reported operational logistics cost in Decimal. "
            "Currency code is mandatory. No FX conversion. "
            "Does not mutate commercial Deal cost snapshot. "
            "Requires Seller or Operator authority and optimistic concurrency expected_version."
        ),
        request=LogisticsUpdateCostSerializer,
        responses={
            200: ExecutionLogisticsSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: ExecutionErrorResponseSerializer,
        },
    )
    def post(self, request, execution_id):
        serializer = LogisticsUpdateCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            logistics = update_logistics_cost(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                logistics_cost=data["logistics_cost"],
                currency=data["currency"],
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (ExecutionClosedError, ExecutionValidationError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionLogisticsSerializer(logistics)
        return Response(out.data, status=status.HTTP_200_OK)


class DealExecutionLogisticsView(APIView):
    """Retrieve operational logistics record by Deal UUID."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deal_execution_logistics",
        tags=["Logistics"],
        summary="Retrieve Operational Logistics for Deal",
        description="Retrieves operational logistics record for a Deal's execution instance.",
        responses={
            200: ExecutionLogisticsSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, deal_id):
        try:
            execution = get_execution_for_deal(deal_id, actor=request.user)
        except ExecutionNotFoundError:
            return Response({"detail": f"Execution for deal '{deal_id}' not found."}, status=status.HTTP_404_NOT_FOUND)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)

        try:
            logistics = get_or_create_execution_logistics(execution.id, actor=request.user, deal_id=deal_id)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)

        serializer = ExecutionLogisticsSerializer(logistics)
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# Execution Quality & Inspection Operational Views (T1005)
# =============================================================================


class ExecutionInspectionDetailView(APIView):
    """
    Operational inspection detail endpoint (Epic 10 Contract §43–§49, T1005).

    GET /api/execution/{execution_id}/inspection/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_inspection_detail",
        tags=["Inspection"],
        summary="Retrieve Execution Quality & Inspection Record",
        description=(
            "Idempotently retrieves or initializes the operational ExecutionInspection aggregate for an Execution. "
            "The required flag is derived strictly from persisted commercial context (RFQ.inspection_required). "
            "Status, result, timestamps, and agency are returned without heuristics or active-schema guessing."
        ),
        responses={
            200: ExecutionInspectionSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, execution_id):
        try:
            inspection = get_or_create_execution_inspection(execution_id, actor=request.user)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except ExecutionNotFoundError as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExecutionInspectionSerializer(inspection)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExecutionInspectionScheduleActionView(APIView):
    """
    Operational action to schedule quality inspection (Epic 10 Contract §44, §80, T1005).

    POST /api/execution/{execution_id}/inspection/schedule/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_inspection_schedule",
        tags=["Inspection"],
        summary="Schedule Quality Inspection",
        description=(
            "Seller/Operator operational action: schedules inspection appointment date and agency. "
            "Transitions status to SCHEDULED, marks required = True, and preserves result as UNKNOWN. "
            "Guarded by optimistic concurrency (expected_version) and select_for_update row locking."
        ),
        request=InspectionScheduleSerializer,
        responses={
            200: ExecutionInspectionSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def post(self, request, execution_id):
        serializer = InspectionScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        deal_id = request.data.get("deal_id")

        try:
            inspection = schedule_inspection(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                scheduled_at=data["scheduled_at"],
                agency=data.get("agency"),
                notes=data.get("notes"),
                deal_id=deal_id,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, InspectionNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            InvalidInspectionTransitionError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionInspectionSerializer(inspection)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionInspectionCompleteActionView(APIView):
    """
    Operational action to record quality inspection completion (Epic 10 Contract §44, §45, §49, T1005).

    POST /api/execution/{execution_id}/inspection/complete/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_inspection_complete",
        tags=["Inspection"],
        summary="Record Quality Inspection Completion",
        description=(
            "Seller/Operator operational action: records authoritative quality inspection completion facts. "
            "Requires mandatory inspection_at timestamp and valid result (PASS, FAIL, CONDITIONAL, UNKNOWN). "
            "Result is never inferred from free-text notes. COMPLETED + FAIL represents a completed inspection "
            "whose quality outcome failed; it allows the INSPECTION_COMPLETED milestone to complete. "
            "Completed facts are historically immutable (no casual reopen or rewrite)."
        ),
        request=InspectionCompleteSerializer,
        responses={
            200: ExecutionInspectionSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def post(self, request, execution_id):
        serializer = InspectionCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        deal_id = request.data.get("deal_id")

        try:
            inspection = complete_inspection(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                inspection_at=data["inspection_at"],
                result=data["result"],
                agency=data.get("agency"),
                notes=data.get("notes"),
                deal_id=deal_id,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, InspectionNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            InvalidInspectionTransitionError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionInspectionSerializer(inspection)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionInspectionCancelActionView(APIView):
    """
    Operational action to cancel scheduled or pending inspection (Epic 10 Contract §44, T1005).

    POST /api/execution/{execution_id}/inspection/cancel/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_inspection_cancel",
        tags=["Inspection"],
        summary="Cancel Quality Inspection",
        description=(
            "Seller/Operator operational action: cancels scheduled or pending quality inspection. "
            "Transitions status to CANCELLED and resets result to UNKNOWN. "
            "Completed inspections cannot be cancelled. "
            "Guarded by optimistic concurrency (expected_version) and select_for_update row locking."
        ),
        request=InspectionCancelSerializer,
        responses={
            200: ExecutionInspectionSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def post(self, request, execution_id):
        serializer = InspectionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        deal_id = request.data.get("deal_id")

        try:
            inspection = cancel_inspection(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                notes=data.get("notes"),
                deal_id=deal_id,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, InspectionNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            InvalidInspectionTransitionError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionInspectionSerializer(inspection)
        return Response(out.data, status=status.HTTP_200_OK)


class ExecutionInspectionMarkNotRequiredActionView(APIView):
    """
    Operational action to mark inspection not required / waived (Epic 10 Contract §44, §80, T1005).

    POST /api/execution/{execution_id}/inspection/mark-not-required/
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="execution_inspection_mark_not_required",
        tags=["Inspection"],
        summary="Mark Quality Inspection Not Required",
        description=(
            "Buyer/Operator operational action: waives inspection requirement. "
            "Seller is strictly denied from unilaterally waiving inspection required by Buyer. "
            "Transitions status to NOT_REQUIRED, sets required = False, and preserves result as UNKNOWN. "
            "NOT_REQUIRED must never become a fake PASS. "
            "Guarded by optimistic concurrency (expected_version) and select_for_update row locking."
        ),
        request=InspectionMarkNotRequiredSerializer,
        responses={
            200: ExecutionInspectionSerializer,
            400: ExecutionErrorResponseSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
            409: OpenApiResponse(
                response=ExecutionErrorResponseSerializer,
                description="Optimistic concurrency conflict (stale expected_version).",
            ),
        },
    )
    def post(self, request, execution_id):
        serializer = InspectionMarkNotRequiredSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        deal_id = request.data.get("deal_id")

        try:
            inspection = mark_inspection_not_required(
                execution_id=execution_id,
                expected_version=data["expected_version"],
                actor=request.user,
                notes=data.get("notes"),
                deal_id=deal_id,
            )
        except StaleVersionError as err:
            return Response({"detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)
        except (ExecutionNotFoundError, InspectionNotFoundError) as err:
            return Response({"detail": str(err)}, status=status.HTTP_404_NOT_FOUND)
        except (
            ExecutionClosedError,
            CrossObjectIntegrityError,
            InvalidInspectionTransitionError,
            ExecutionValidationError,
        ) as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        out = ExecutionInspectionSerializer(inspection)
        return Response(out.data, status=status.HTTP_200_OK)


class DealExecutionInspectionView(APIView):
    """Retrieve operational inspection record by Deal UUID."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="deal_execution_inspection",
        tags=["Inspection"],
        summary="Retrieve Operational Inspection for Deal",
        description="Retrieves operational inspection record for a Deal's execution instance.",
        responses={
            200: ExecutionInspectionSerializer,
            403: ExecutionErrorResponseSerializer,
            404: ExecutionErrorResponseSerializer,
        },
    )
    def get(self, request, deal_id):
        try:
            execution = get_execution_for_deal(deal_id, actor=request.user)
        except ExecutionNotFoundError:
            return Response({"detail": f"Execution for deal '{deal_id}' not found."}, status=status.HTTP_404_NOT_FOUND)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)

        try:
            inspection = get_or_create_execution_inspection(execution.id, actor=request.user, deal_id=deal_id)
        except ExecutionPermissionDeniedError as err:
            return Response({"detail": str(err)}, status=status.HTTP_403_FORBIDDEN)

        serializer = ExecutionInspectionSerializer(inspection)
        return Response(serializer.data, status=status.HTTP_200_OK)


