import uuid
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from organizations.models import Organization, OrganizationMembership
from identity.models import SystemRoleAssignment
from documents.models import VerificationDocument
from documents.api.serializers import VerificationDocumentSerializer, UploadDocumentSerializer
from documents.storage import upload_document, get_document_bytes
from organizations.verification.models import OrganizationVerification, VerificationStatus, VerificationDecision

def has_operator_or_admin_role(user):
    return SystemRoleAssignment.objects.filter(
        user=user, role__in=[SystemRoleAssignment.SystemRole.OPERATOR, SystemRoleAssignment.SystemRole.ADMIN]
    ).exists()

def is_owner_or_manager(user, organization):
    return OrganizationMembership.objects.filter(
        user=user,
        organization=organization,
        role__in=[OrganizationMembership.OrganizationRole.OWNER, OrganizationMembership.OrganizationRole.MANAGER],
        is_active=True,
    ).exists()

class DocumentUploadView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(request=UploadDocumentSerializer, responses={201: VerificationDocumentSerializer})
    def post(self, request):
        serializer = UploadDocumentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        org_id = serializer.validated_data["organization"]
        organization = get_object_or_404(Organization, id=org_id)

        # Authorization: Must be Owner or Manager of active organization
        if not organization.is_active:
            return Response({"detail": "Organization is inactive."}, status=status.HTTP_403_FORBIDDEN)
        if not is_owner_or_manager(request.user, organization):
            return Response({"detail": "Not authorized to upload documents for this organization."}, status=status.HTTP_403_FORBIDDEN)

        file_obj = serializer.validated_data["file"]

        # Validation: PDF/JPEG/PNG only
        allowed_types = ["application/pdf", "image/jpeg", "image/png"]
        if file_obj.content_type not in allowed_types:
            return Response({"detail": "Unsupported file type. Only PDF, JPEG, and PNG are allowed."}, status=status.HTTP_400_BAD_REQUEST)

        # Validation: 10 MB limit
        if file_obj.size > 10 * 1024 * 1024:
            return Response({"detail": "File size exceeds the 10 MB limit."}, status=status.HTTP_400_BAD_REQUEST)

        object_key = f"{organization.id}/{uuid.uuid4()}-{file_obj.name}"

        # Upload to MinIO
        try:
            upload_document(file_obj, object_key, file_obj.content_type, file_obj.size)
        except Exception:
            return Response({"detail": "Storage failure."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        from django.db import IntegrityError
        from documents.models import DocumentType
        try:
            with transaction.atomic():
                doc_type = serializer.validated_data["type"]

                # Check if replacing an existing current document
                replaced_count = VerificationDocument.objects.filter(
                    organization=organization,
                    type=doc_type,
                    is_current=True
                ).update(
                    is_current=False,
                    verification_status="replaced" # Legacy sync
                )

                doc = VerificationDocument.objects.create(
                    organization=organization,
                    type=doc_type,
                    file_name=file_obj.name,
                    object_key=object_key,
                    mime_type=file_obj.content_type,
                    size_bytes=file_obj.size,
                    uploaded_by=request.user,
                    is_current=True,
                    verification_status="pending"
                )

                # M6: Precise invalidation policy on replacement of currently required trust evidence
                try:
                    # Lock verification to avoid trust/evidence race condition
                    verification = OrganizationVerification.objects.select_for_update().get(organization_id=organization.id)
                    should_downgrade = False

                    # Only replacement of *required* evidence downgrades trust.
                    # First uploads of optional/missing categories do not downgrade trust.
                    if replaced_count > 0:
                        if verification.status == VerificationStatus.BASIC_VERIFIED:
                            if doc_type in [DocumentType.COMPANY_REGISTRATION, DocumentType.TAX_ID, DocumentType.AUTHORIZED_REPRESENTATIVE]:
                                should_downgrade = True
                        elif verification.status == VerificationStatus.VERIFIED:
                            if doc_type in [DocumentType.COMPANY_REGISTRATION, DocumentType.TAX_ID, DocumentType.AUTHORIZED_REPRESENTATIVE, DocumentType.TRADE_LICENSE, DocumentType.BANK_DETAILS]:
                                should_downgrade = True

                    if should_downgrade:
                        old_status = verification.status
                        verification.status = VerificationStatus.DOCUMENTS_SUBMITTED
                        verification.version += 1
                        verification.save()

                        VerificationDecision.objects.create(
                            verification=verification,
                            actor=request.user,
                            action="evidence_replacement_invalidation",
                            previous_status=old_status,
                            new_status=VerificationStatus.DOCUMENTS_SUBMITTED,
                            reason="System triggered: Required evidence replaced."
                        )
                except OrganizationVerification.DoesNotExist:
                    pass

        except IntegrityError:
            # Re-upload race condition on UniqueConstraint(organization, type, is_current=True)
            return Response({"detail": "Concurrent upload detected for this document category."}, status=status.HTTP_409_CONFLICT)
        except Exception:
            # If DB fails, object is orphaned in MinIO.
            # Realistically we should delete it or have a cleanup cron,
            # but we prioritize returning 500 without corrupting DB state.
            return Response({"detail": "Database failure."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(VerificationDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

class DocumentDownloadView(APIView):
    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk):
        doc = get_object_or_404(VerificationDocument, id=pk)

        # Authorization:
        # Operator/Admin can inspect any
        # Owner/Manager can inspect their own active org's docs
        is_op_admin = has_operator_or_admin_role(request.user)
        is_own_manager = is_owner_or_manager(request.user, doc.organization)

        if not (is_op_admin or (is_own_manager and doc.organization.is_active)):
            return Response({"detail": "Not authorized to download this document."}, status=status.HTTP_403_FORBIDDEN)

        data = get_document_bytes(doc.object_key)
        if data is None:
            return Response({"detail": "File not found in storage."}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(data, content_type=doc.mime_type)
        response['Content-Disposition'] = f'attachment; filename="{doc.file_name}"'
        return response

class DocumentListView(generics.ListAPIView):
    serializer_class = VerificationDocumentSerializer

    def get_queryset(self):
        org_id = self.request.query_params.get("organization")
        if not org_id:
            return VerificationDocument.objects.none()

        organization = get_object_or_404(Organization, id=org_id)

        is_op_admin = has_operator_or_admin_role(self.request.user)
        is_own_manager = is_owner_or_manager(self.request.user, organization)

        if not (is_op_admin or (is_own_manager and organization.is_active)):
            return VerificationDocument.objects.none()

        return VerificationDocument.objects.filter(organization=organization).order_by("-created_at")

    @extend_schema(parameters=[
        OpenApiParameter(name="organization", type=OpenApiTypes.UUID, required=True)
    ])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
