from decimal import Decimal
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from geography.models import AreaType, GeographicArea
from opportunities.models import Opportunity, OpportunityDirection, OpportunityStatus
from organizations.models import Organization


class StructuredGeographyOpportunityTests(TestCase):
    """
    Tests for structured GeographicArea reference on Opportunity.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Lead Org", country="IR")
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

    def test_opportunity_structured_origin_area_and_property(self):
        """Opportunity supports structured origin_area and supply_area alias property."""
        opp = Opportunity.objects.create(
            identifier="OPP-2026-000001",
            organization=self.org,
            commodity=self.commodity,
            schema_version=self.schema,
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            quantity=Decimal("1200.000"),
            unit="MT",
            geography="Tehran Province, Free-text note",
            origin_area=self.tehran_prov,
        )
        self.assertEqual(opp.geography, "Tehran Province, Free-text note")
        self.assertEqual(opp.origin_area, self.tehran_prov)
        self.assertEqual(opp.supply_area, self.tehran_prov)
