from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from organizations.models import Organization
from trade_hub.models import (
    GeographyConstraintMode,
    RFQ,
    RFQGeographyConstraint,
    RFQStatus,
    RFQVisibility,
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


class StructuredGeographyTradeHubTests(TestCase):
    """
    Tests for structured GeographicArea references on RFQ and SupplyListing.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Buyer Org", country="IR")
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_en="Bitumen",
            name_fa="قیر",
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )
        self.iran = GeographicArea.objects.create(
            code="IR",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
        )
        self.tehran_prov = GeographicArea.objects.create(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Tehran",
            name_fa="تهران",
            parent=self.iran,
        )
        self.bandar_abbas = GeographicArea.objects.create(
            code="IR-23-BND",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Bandar Abbas",
            name_fa="بندرعباس",
            parent=GeographicArea.objects.create(
                code="IR-23",
                area_type=AreaType.ADMINISTRATIVE_AREA,
                country_code="IR",
                name_en="Hormozgan",
                name_fa="هرمزگان",
                parent=self.iran,
            ),
        )

    def test_rfq_structured_areas_and_legacy_fields(self):
        """RFQ supports structured origin_area and destination_area alongside legacy string fields."""
        rfq = RFQ.objects.create(
            organization=self.org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
            # Legacy string fields
            origin="Bandar Abbas Terminal",
            destination="Tehran Central Depot",
            # Structured GeographicArea references
            origin_area=self.bandar_abbas,
            destination_area=self.tehran_prov,
        )
        self.assertEqual(rfq.origin, "Bandar Abbas Terminal")
        self.assertEqual(rfq.destination, "Tehran Central Depot")
        self.assertEqual(rfq.origin_area, self.bandar_abbas)
        self.assertEqual(rfq.destination_area, self.tehran_prov)

    def test_rfq_geography_constraints_and_uniqueness(self):
        """RFQ supports multiple geography constraints with modes and uniqueness enforcement."""
        rfq = RFQ.objects.create(
            organization=self.org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
        )
        c1 = RFQGeographyConstraint.objects.create(
            rfq=rfq,
            mode=GeographyConstraintMode.REQUIRED,
            area=self.tehran_prov,
        )
        self.assertEqual(rfq.geography_constraints.count(), 1)
        self.assertEqual(rfq.geography_constraints.first(), c1)

        # Duplicate [rfq, mode, area] constraint rejected
        dup = RFQGeographyConstraint(
            rfq=rfq,
            mode=GeographyConstraintMode.REQUIRED,
            area=self.tehran_prov,
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                dup.save()

    def test_supply_listing_structured_area_and_property(self):
        """SupplyListing supports structured origin_area and supply_area alias property."""
        listing = SupplyListing.objects.create(
            organization=self.org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("1000.000"),
            unit="MT",
            origin="Bandar Abbas Refinery",
            origin_area=self.bandar_abbas,
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )
        self.assertEqual(listing.origin, "Bandar Abbas Refinery")
        self.assertEqual(listing.origin_area, self.bandar_abbas)
        self.assertEqual(listing.supply_area, self.bandar_abbas)
