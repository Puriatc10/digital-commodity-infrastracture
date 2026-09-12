from rest_framework import views, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from .serializers import OrganizationVerificationDetailSerializer, InternalOrganizationVerificationDetailSerializer, VerificationActionSerializer, VerificationNoteSerializer, ChecklistReviewSerializer, VerificationQueueSerializer
from .models import OrganizationVerification, VerificationStatus
from django.shortcuts import get_object_or_404
from organizations.models import Organization

from .services import VerificationService, VerificationDomainException
from .permissions import CanViewVerification, CanSubmitVerification, CanPerformVerificationReview

def get_verification_serializer_class(user):
    if user and user.is_authenticated and user.system_roles.filter(role__in=['operator', 'admin']).exists():
        return InternalOrganizationVerificationDetailSerializer
    return OrganizationVerificationDetailSerializer

class VerificationDetailView(generics.RetrieveAPIView):
    def get_serializer_class(self):
        return get_verification_serializer_class(self.request.user)

    permission_classes = [IsAuthenticated, CanViewVerification]

    def get_object(self):
        org_id = self.kwargs['org_id']
        org = get_object_or_404(Organization, id=org_id)
        self.check_object_permissions(self.request, org)
        return VerificationService.get_or_create_verification(org.id)

class BaseVerificationActionView(views.APIView):
    def get_organization(self):
        org_id = self.kwargs['org_id']
        org = get_object_or_404(Organization, id=org_id)
        self.check_object_permissions(self.request, org)
        return org

    def perform_action(self, org, actor, data):
        raise NotImplementedError

    @extend_schema(
        request=VerificationActionSerializer,
        responses={
            200: InternalOrganizationVerificationDetailSerializer,
            400: OpenApiResponse(description="Domain error (e.g. invalid transition)"),
            409: OpenApiResponse(description="Conflict (stale version)")
        }
    )
    def post(self, request, *args, **kwargs):
        org = self.get_organization()
        serializer = VerificationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            verification = self.perform_action(org, request.user, serializer.validated_data)
            SerializerClass = get_verification_serializer_class(request.user)
            response_serializer = SerializerClass(verification, context={"request": request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except VerificationDomainException as e:
            if "Stale object" in str(e):
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class VerificationSubmitView(views.APIView):
    permission_classes = [IsAuthenticated, CanSubmitVerification]
    serializer_class = VerificationActionSerializer # Needed for openapi guess

    # For submit, it could be the very first time so expected_version isn't strictly required
    @extend_schema(
        request=VerificationActionSerializer,
        responses={
            200: InternalOrganizationVerificationDetailSerializer,
            400: OpenApiResponse(description="Domain error (e.g. invalid transition)"),
            409: OpenApiResponse(description="Conflict (stale version)")
        }
    )
    def post(self, request, *args, **kwargs):
        org_id = self.kwargs['org_id']
        org = get_object_or_404(Organization, id=org_id)
        self.check_object_permissions(self.request, org)
        expected_version = request.data.get('expected_version')

        try:
            verification = VerificationService.submit(org.id, request.user, expected_version)
            SerializerClass = get_verification_serializer_class(request.user)
            response_serializer = SerializerClass(verification, context={"request": request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except VerificationDomainException as e:
            if "Stale object" in str(e):
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class VerificationStartReviewView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.start_review(org.id, actor, data.get('expected_version'))

class VerificationApproveBasicView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.basic_approval(org.id, actor, data.get('expected_version'))

class VerificationApproveFullView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.full_approval(org.id, actor, data.get('expected_version'))

class VerificationRejectView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.reject(org.id, actor, data.get('reason'), data.get('expected_version'))

class VerificationSuspendView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.suspend(org.id, actor, data.get('reason'), data.get('expected_version'))

class VerificationReopenView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    def perform_action(self, org, actor, data):
        return VerificationService.reopen(org.id, actor, data.get('expected_version'))

class VerificationNoteCreateView(views.APIView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    @extend_schema(
        request=VerificationNoteSerializer,
        responses={201: VerificationNoteSerializer}
    )
    def post(self, request, *args, **kwargs):
        org_id = self.kwargs['org_id']
        org = get_object_or_404(Organization, id=org_id)
        self.check_object_permissions(request, org)

        serializer = VerificationNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
             note = VerificationService.add_internal_note(org.id, request.user, serializer.validated_data['note'])
             return Response(VerificationNoteSerializer(note).data, status=status.HTTP_201_CREATED)
        except VerificationDomainException as e:
             return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class VerificationChecklistView(BaseVerificationActionView):
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]

    @extend_schema(
        request=ChecklistReviewSerializer,
        responses={
            200: InternalOrganizationVerificationDetailSerializer,
            400: OpenApiResponse(description="Domain error (e.g. missing document, invalid transition)"),
            409: OpenApiResponse(description="Conflict (stale version)")
        }
    )
    def post(self, request, *args, **kwargs):
        org = self.get_organization()
        serializer = ChecklistReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            verification = VerificationService.review_checklist_item(
                org.id,
                serializer.validated_data['document_id'],
                request.user,
                serializer.validated_data['outcome'],
                serializer.validated_data.get('expected_version')
            )
            SerializerClass = get_verification_serializer_class(request.user)
            response_serializer = SerializerClass(verification, context={"request": request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except VerificationDomainException as e:
            if "Stale object" in str(e):
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)



class VerificationQueueListView(generics.ListAPIView):
    serializer_class = VerificationQueueSerializer
    permission_classes = [IsAuthenticated, CanPerformVerificationReview]
    is_list_view = True

    @extend_schema(
        parameters=[
            OpenApiParameter(name="is_pending", type=OpenApiTypes.BOOL, description="Filter for pending cases (Documents Submitted, Under Review)", required=False),
            OpenApiParameter(name="status", type=OpenApiTypes.STR, description="Filter by exact status", required=False),
        ]
    )
    def get_queryset(self):
        qs = OrganizationVerification.objects.all().select_related('organization')

        is_pending = self.request.query_params.get('is_pending')
        if is_pending and is_pending.lower() == 'true':
            qs = qs.filter(status__in=[VerificationStatus.DOCUMENTS_SUBMITTED, VerificationStatus.UNDER_REVIEW])

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        return qs.order_by('updated_at')
