from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions

from geography.api.serializers import GeographicAreaSerializer
from geography.models import GeographicArea


class GeographicAreaListView(generics.ListAPIView):
    """
    Read-only list of geographic areas.

    Optimized with select_related('parent') to prevent N+1 queries during serialization.
    Supports filtering by country, parent, area type, and search term.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GeographicAreaSerializer

    def get_queryset(self):
        queryset = (
            GeographicArea.objects.filter(is_active=True)
            .select_related("parent")
            .order_by("country_code", "area_type", "code")
        )

        country = self.request.query_params.get("country")
        if country:
            queryset = queryset.filter(country_code=country.strip().upper())

        area_type = self.request.query_params.get("type")
        if area_type:
            queryset = queryset.filter(area_type=area_type.strip().upper())

        parent = self.request.query_params.get("parent")
        if parent is not None:
            if parent.lower() in ("null", "none", ""):
                queryset = queryset.filter(parent__isnull=True)
            else:
                queryset = queryset.filter(
                    Q(parent__id__iexact=parent) | Q(parent__code__iexact=parent)
                )

        search = self.request.query_params.get("search")
        if search:
            search = search.strip()
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name_en__icontains=search)
                | Q(name_fa__icontains=search)
            )

        return queryset

    @extend_schema(
        operation_id="geography_areas_list",
        summary="List active geographic areas",
        parameters=[
            OpenApiParameter(
                name="country",
                description="Filter by ISO 3166-1 alpha-2 country code (e.g. 'IR').",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="type",
                description="Filter by area type (COUNTRY, ADMINISTRATIVE_AREA, CITY).",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="parent",
                description="Filter by parent ID, parent code, or 'null' for root countries.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="search",
                description="Case-insensitive substring search in code, name_en, or name_fa.",
                required=False,
                type=str,
            ),
        ],
        responses={200: GeographicAreaSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class GeographicAreaDetailView(generics.RetrieveAPIView):
    """
    Read-only retrieval of a single geographic area by ID.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GeographicAreaSerializer
    queryset = GeographicArea.objects.all().select_related("parent")

    @extend_schema(
        operation_id="geography_areas_read",
        summary="Retrieve geographic area by ID",
        responses={200: GeographicAreaSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
