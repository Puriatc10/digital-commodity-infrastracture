from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from deals.models import DealTermsSnapshot
from execution.enums import TransportMode
from execution.models.logistics import ExecutionLogistics
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    get_or_create_execution_logistics,
    record_delivery,
    record_loading,
    update_logistics_cost,
    update_transport,
)
from execution.tests.base import BaseExecutionTestCase
from geography.models import AreaType, GeographicArea


class LogisticsModelAndIntegrityTests(BaseExecutionTestCase):
    """
    Tests for ExecutionLogistics model, cardinality, transport enums, geography,
    money integrity, chronology, and deal immutability (Epic 10 Contract §35–§42, T1004).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        # Geographic test areas
        self.iran = GeographicArea.objects.create(
            code="IR",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_fa="ایران",
            name_en="Iran",
        )
        self.tehran_prov = GeographicArea.objects.create(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            parent=self.iran,
            country_code="IR",
            name_fa="تهران",
            name_en="Tehran Province",
        )
        self.tehran_city = GeographicArea.objects.create(
            code="IR-07-THR",
            area_type=AreaType.CITY,
            parent=self.tehran_prov,
            country_code="IR",
            name_fa="تهران",
            name_en="Tehran",
        )
        self.hormozgan = GeographicArea.objects.create(
            code="IR-23",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            parent=self.iran,
            country_code="IR",
            name_fa="هرمزگان",
            name_en="Hormozgan",
        )
        self.bandar_abbas = GeographicArea.objects.create(
            code="IR-23-BND",
            area_type=AreaType.CITY,
            parent=self.hormozgan,
            country_code="IR",
            name_fa="بندرعباس",
            name_en="Bandar Abbas",
        )

    def test_one_logistics_per_execution_db_enforced(self):
        """
        Database uniqueness enforces at most one ExecutionLogistics per Execution.
        Attempting to create a second logistics record raises IntegrityError.
        """
        # First logistics record exists from execution creation
        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertIsNotNone(logistics.id)

        # Attempting to manually create a second one must raise IntegrityError
        with self.assertRaises(IntegrityError):
            ExecutionLogistics.objects.create(
                execution=self.execution,
                version=1,
            )

    def test_idempotent_initialization(self):
        """get_or_create_execution_logistics is strictly idempotent."""
        log1 = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)
        log2 = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)
        self.assertEqual(log1.id, log2.id)
        self.assertEqual(ExecutionLogistics.objects.filter(execution=self.execution).count(), 1)

    def test_unknown_semantics_preservation(self):
        """
        Upon initialization, operational values remain null/empty.
        Never fabricate values like now(), 'unknown', or 0.
        """
        logistics = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)
        self.assertEqual(logistics.carrier_name, "")
        self.assertEqual(logistics.carrier, "")
        self.assertIsNone(logistics.transport_mode)
        self.assertIsNone(logistics.pickup_area)
        self.assertIsNone(logistics.destination_area)
        self.assertEqual(logistics.pickup_location, "")
        self.assertEqual(logistics.destination_location, "")
        self.assertIsNone(logistics.scheduled_loading_at)
        self.assertIsNone(logistics.actual_loading_at)
        self.assertIsNone(logistics.eta)
        self.assertIsNone(logistics.actual_delivery_at)
        self.assertEqual(logistics.transport_reference, "")
        self.assertIsNone(logistics.logistics_cost)
        self.assertEqual(logistics.currency, "")
        self.assertEqual(logistics.version, 1)

    def test_transport_mode_canonical_enum(self):
        """Transport mode must use canonical values; invalid modes are rejected."""
        logistics = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)

        # All canonical values must be valid
        for mode in [
            TransportMode.ROAD,
            TransportMode.SEA,
            TransportMode.RAIL,
            TransportMode.AIR,
            TransportMode.MULTIMODAL,
            TransportMode.OTHER,
        ]:
            logistics.transport_mode = mode
            logistics.clean()

        # Invalid mode is rejected by clean()
        logistics.transport_mode = "SPACESHIP"
        with self.assertRaises(ValidationError) as ctx:
            logistics.clean()
        self.assertIn("transport_mode", ctx.exception.message_dict)

    def test_geography_structured_references(self):
        """ExecutionLogistics reuses GeographicArea references without degrading to text-only."""
        logistics = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)
        logistics.pickup_area = self.tehran_city
        logistics.destination_area = self.bandar_abbas
        logistics.pickup_location = "Refinery Loading Bay 4"
        logistics.destination_location = "Shahid Rajaee Port Jetty 2"
        logistics.save()

        logistics.refresh_from_db()
        self.assertEqual(logistics.pickup_area.code, "IR-07-THR")
        self.assertEqual(logistics.destination_area.code, "IR-23-BND")
        self.assertEqual(logistics.pickup_location, "Refinery Loading Bay 4")
        self.assertEqual(logistics.destination_location, "Shahid Rajaee Port Jetty 2")

    def test_no_gps_fields(self):
        """Logistics model does not introduce GPS or telematics coordinates."""
        field_names = [f.name for f in ExecutionLogistics._meta.get_fields()]
        self.assertNotIn("latitude", field_names)
        self.assertNotIn("longitude", field_names)
        self.assertNotIn("gps_coordinates", field_names)

    def test_money_decimal_and_mandatory_currency(self):
        """
        Logistics cost must be Decimal, non-negative, and requires explicit 3-letter currency.
        No float, no ambiguous currency, no FX conversion.
        """
        logistics = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)

        # Cost without currency is rejected
        logistics.logistics_cost = Decimal("1500.50")
        logistics.currency = ""
        with self.assertRaises(ValidationError) as ctx:
            logistics.clean()
        self.assertIn("currency", ctx.exception.message_dict)

        # Invalid currency length is rejected
        logistics.currency = "US"
        with self.assertRaises(ValidationError) as ctx:
            logistics.clean()
        self.assertIn("currency", ctx.exception.message_dict)

        # Negative cost is rejected
        logistics.logistics_cost = Decimal("-10.00")
        logistics.currency = "USD"
        with self.assertRaises(ValidationError) as ctx:
            logistics.clean()
        self.assertIn("logistics_cost", ctx.exception.message_dict)

        # Valid Decimal cost and ISO currency succeed
        logistics.logistics_cost = Decimal("2450.75")
        logistics.currency = "USD"
        logistics.clean()
        logistics.save()

        logistics.refresh_from_db()
        self.assertEqual(logistics.logistics_cost, Decimal("2450.75"))
        self.assertEqual(logistics.currency, "USD")

    def test_chronology_validation(self):
        """actual_delivery_at cannot precede actual_loading_at."""
        logistics = get_or_create_execution_logistics(self.execution.id, actor=self.operator_user)
        now = timezone.now()

        # Loading at now, delivery 1 hour earlier -> REJECTED
        logistics.actual_loading_at = now
        logistics.actual_delivery_at = now - timezone.timedelta(hours=1)
        with self.assertRaises(ValidationError) as ctx:
            logistics.clean()
        self.assertIn("actual_delivery_at", ctx.exception.message_dict)

        # Delivery after loading -> VALID
        logistics.actual_delivery_at = now + timezone.timedelta(days=2)
        logistics.clean()

    def test_deal_immutability_and_commercial_divergence(self):
        """
        Actual logistics operational changes must NEVER mutate DealTermsSnapshot or Deal.
        Agreed commercial terms and operational actuals can diverge and both remain historically valid.
        """
        terms = DealTermsSnapshot.objects.get(deal=self.deal)
        orig_incoterm = terms.incoterm
        orig_delivery_terms = terms.delivery_terms
        orig_quantity = terms.quantity
        orig_unit_price = terms.unit_price
        orig_product_cost = terms.product_cost_snapshot

        # Mutate operational logistics via service
        update_transport(
            self.execution.id,
            expected_version=1,
            actor=self.operator_user,
            carrier_name="Persian Gulf Logistics Co",
            transport_mode=TransportMode.ROAD,
            transport_reference="CMR-998877",
        )
        update_logistics_cost(
            self.execution.id,
            expected_version=2,
            actor=self.operator_user,
            logistics_cost=Decimal("7800.00"),
            currency="EUR",
        )

        now = timezone.now()
        record_loading(
            self.execution.id,
            expected_version=3,
            actor=self.operator_user,
            actual_loading_at=now,
        )
        record_delivery(
            self.execution.id,
            expected_version=4,
            actor=self.operator_user,
            actual_delivery_at=now + timezone.timedelta(days=3),
        )

        # Verify operational logistics is updated
        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 5)
        self.assertEqual(logistics.carrier_name, "Persian Gulf Logistics Co")
        self.assertEqual(logistics.transport_mode, TransportMode.ROAD)
        self.assertEqual(logistics.logistics_cost, Decimal("7800.00"))
        self.assertEqual(logistics.currency, "EUR")

        # Verify Deal and DealTermsSnapshot remain strictly untouched
        terms.refresh_from_db()
        self.assertEqual(terms.incoterm, orig_incoterm)
        self.assertEqual(terms.delivery_terms, orig_delivery_terms)
        self.assertEqual(terms.quantity, orig_quantity)
        self.assertEqual(terms.unit_price, orig_unit_price)
        self.assertEqual(terms.product_cost_snapshot, orig_product_cost)
