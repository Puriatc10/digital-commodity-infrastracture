from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from drf_spectacular.utils import extend_schema, OpenApiTypes

from .models import CommodityDefinition, CommoditySchemaVersion
from .serializers import (
    CommodityDefinitionSerializer,
    CommoditySchemaVersionSerializer,
)


class CommodityListView(generics.ListAPIView):
    """
    Return active usable Commodities in deterministic order.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommodityDefinitionSerializer

    def get_queryset(self):
        return CommodityDefinition.objects.filter(is_active=True).order_by("code")

    @extend_schema(operation_id="commodities_list", responses={200: CommodityDefinitionSerializer(many=True), 403: OpenApiTypes.OBJECT})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ActiveCommoditySchemaView(generics.RetrieveAPIView):
    """
    Return the Commodity's explicitly selected active Published schema.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommoditySchemaVersionSerializer
    lookup_field = "code"

    def get_object(self):
        code = self.kwargs.get(self.lookup_field)
        commodity = get_object_or_404(CommodityDefinition, code=code)

        active_schema = commodity.active_schema_version

        # Never guess newest version. Only explicitly selected active published.
        if not active_schema or active_schema.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED or active_schema.commodity_id != commodity.pk:
            from django.http import Http404
            raise Http404("No active published schema for this commodity.")

        # Prefetch attributes to avoid N+1 queries
        return CommoditySchemaVersion.objects.prefetch_related("attributes").get(id=active_schema.id)

    @extend_schema(operation_id="commodities_active_schema_retrieve", responses={200: CommoditySchemaVersionSerializer, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CommoditySchemaDetailView(generics.RetrieveAPIView):
    """
    Historical schema retrieval.
    Published and Retired schemas remain retrievable by stable ID.
    Draft definitions are internal and must not be exposed.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CommoditySchemaVersionSerializer
    queryset = CommoditySchemaVersion.objects.exclude(status="draft").prefetch_related("attributes")

    @extend_schema(operation_id="commodity_schemas_retrieve", responses={200: CommoditySchemaVersionSerializer, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
