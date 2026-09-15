import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment
from opportunities.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    OpportunityQualificationError,
    StaleVersionError,
)
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    create_opportunity_task,
)
from opportunities.services_lifecycle import qualify_opportunity
from opportunities.services_qualification import evaluate_qualification
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class OpportunityQualificationEvaluatorTests(TestCase):
    """
    Unit tests for the central qualification evaluator (evaluate_qualification).

    Verifies the authoritative qualification contract derived from Product Specification
    §§12, 14, 15, 17, 18, 19, 20, 21, 23, 24.
    """

    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_60_70_eval",
            name_en="Bitumen 60/70 Eval",
            name_fa="قیر ۶۰/۷۰ ارزیابی",
            is_active=True,
        )
        self.buyer_org = Organization.objects.create(name="Eval Buyer Corp")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.supplier_org = Organization.objects.create(name="Eval Supplier Corp")
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.broker_org = Organization.objects.create(name="Eval Broker Corp")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.ext_counterparty = ExternalCounterparty.objects.create(
            company_name="Eval Global Energy Ltd",
            contact_name="Ali Reza",
            geography="Dubai, UAE",
        )

    def _create_valid_demand_opportunity(self, **kwargs):
        defaults = {
            "direction": OpportunityDirection.DEMAND,
            "organization_id": self.buyer_org.id,
            "commodity_id": self.commodity.id,
            "quantity": Decimal("500.000"),
            "unit": "MT",
            "indicative_price": Decimal("380.00"),
            "currency": "USD",
            "geography": "Rotterdam, Netherlands",
            "delivery_window_start": datetime.date(2026, 11, 1),
            "delivery_window_end": datetime.date(2026, 11, 30),
            "payment_terms": "100% LC at sight",
            "source": OpportunitySource.OPERATOR_SOURCING,
        }
        defaults.update(kwargs)
        return create_opportunity(**defaults)

    def _create_valid_supply_opportunity(self, **kwargs):
        defaults = {
            "direction": OpportunityDirection.SUPPLY,
            "organization_id": self.supplier_org.id,
            "commodity_id": self.commodity.id,
            "quantity": Decimal("1000.000"),
            "unit": "MT",
            "indicative_price": Decimal("350.00"),
            "currency": "USD",
            "geography": "Bandar Abbas, Iran",
            "delivery_window_start": datetime.date(2026, 11, 1),
            "delivery_window_end": datetime.date(2026, 11, 30),
            "payment_terms": "Cash Against Documents",
            "source": OpportunitySource.OPERATOR_SOURCING,
        }
        defaults.update(kwargs)
        return create_opportunity(**defaults)

    # -------------------------------------------------------------------------
    # Happy Path Evaluations
    # -------------------------------------------------------------------------

    def test_valid_demand_opportunity_qualifiable(self):
        opp = self._create_valid_demand_opportunity()
        res = evaluate_qualification(opp)
        self.assertTrue(res.is_qualifiable)
        self.assertTrue(res.qualifiable)
        self.assertEqual(len(res.missing_requirements), 0)
        self.assertEqual(len(res.invalid_requirements), 0)

    def test_demand_opportunity_price_is_optional_per_spec_12(self):
        """Spec §12: RFQ/Demand Target Price is optional."""
        opp = self._create_valid_demand_opportunity(indicative_price=None)
        res = evaluate_qualification(opp)
        self.assertTrue(res.is_qualifiable)
        self.assertEqual(len(res.missing_requirements), 0)

    def test_valid_supply_opportunity_qualifiable(self):
        opp = self._create_valid_supply_opportunity()
        res = evaluate_qualification(opp)
        self.assertTrue(res.is_qualifiable)
        self.assertEqual(len(res.missing_requirements), 0)
        self.assertEqual(len(res.invalid_requirements), 0)

    # -------------------------------------------------------------------------
    # Supply vs Demand Direction Differences
    # -------------------------------------------------------------------------

    def test_supply_opportunity_requires_indicative_price(self):
        """Spec §14 & §24: Supply leads require indicative price."""
        opp = self._create_valid_supply_opportunity()
        opp.indicative_price = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "indicative_price"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_supply_opportunity_zero_or_negative_price_rejected(self):
        opp = self._create_valid_supply_opportunity()
        opp.indicative_price = Decimal("0.00")

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "indicative_price"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "min_value")

    def test_supply_opportunity_missing_currency_rejected(self):
        opp = self._create_valid_supply_opportunity()
        opp.currency = ""

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "currency"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    # -------------------------------------------------------------------------
    # Individual Qualification Requirements
    # -------------------------------------------------------------------------

    def test_missing_counterparty_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.organization = None
        opp.organization_id = None
        opp.external_counterparty = None
        opp.external_counterparty_id = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "counterparty"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_external_counterparty_empty_company_name_rejected(self):
        opp = self._create_valid_demand_opportunity(
            organization_id=None,
            external_counterparty_id=self.ext_counterparty.id,
        )
        opp.external_counterparty.company_name = ""

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "external_counterparty"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid")

    def test_missing_commodity_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.commodity = None
        opp.commodity_id = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "commodity"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_inactive_commodity_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.commodity.is_active = False

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "commodity"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "inactive_commodity")

    def test_missing_quantity_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.quantity = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "quantity"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_non_positive_quantity_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.quantity = Decimal("0.000")

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "quantity"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "min_value")

    def test_missing_unit_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.unit = ""

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "unit"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_missing_geography_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.geography = ""

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "geography"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_missing_delivery_window_start_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.delivery_window_start = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "delivery_window_start"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_missing_delivery_window_end_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.delivery_window_end = None

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "delivery_window_end"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_invalid_delivery_window_date_order_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.delivery_window_start = datetime.date(2026, 11, 30)
        opp.delivery_window_end = datetime.date(2026, 11, 1)

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "delivery_window_end"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid_date_order")

    def test_missing_payment_terms_rejected(self):
        opp = self._create_valid_demand_opportunity()
        opp.payment_terms = ""

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.missing_requirements if i.field == "payment_terms"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "required")

    def test_broker_referral_missing_broker_capability_rejected(self):
        non_broker_org = Organization.objects.create(name="Non Broker Corp")
        opp = self._create_valid_demand_opportunity()
        Opportunity.objects.filter(id=opp.id).update(
            source=OpportunitySource.BROKER_REFERRAL,
            broker=non_broker_org,
        )
        opp.refresh_from_db()

        res = evaluate_qualification(opp)
        self.assertFalse(res.is_qualifiable)
        issue = next((i for i in res.invalid_requirements if i.field == "broker"), None)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "invalid_broker")


class OpportunityQualificationServiceIntegrationTests(TestCase):
    """
    Integration tests for qualify_opportunity lifecycle domain service.
    """

    def setUp(self):
        self.operator = User.objects.create_user(email="operator@platform.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_vg30_service",
            name_en="Bitumen VG-30 Service",
            name_fa="قیر VG-30 سرویس",
            is_active=True,
        )
        self.supplier_org = Organization.objects.create(name="Service Supplier Ltd")
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.broker_org = Organization.objects.create(name="Service Brokerage Ltd")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.ext_supplier = ExternalCounterparty.objects.create(
            company_name="Al-Noor Petrochem FZE",
            contact_name="Tariq Mansoor",
            geography="Sharjah, UAE",
        )
        self.valid_opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1500.000"),
            unit="MT",
            indicative_price=Decimal("345.00"),
            currency="USD",
            geography="Fujairah, UAE",
            delivery_window_start=datetime.date(2026, 12, 1),
            delivery_window_end=datetime.date(2026, 12, 20),
            payment_terms="Irrevocable LC 60 days",
            source=OpportunitySource.OPERATOR_SOURCING,
        )

    def test_captured_to_qualified_direct_success(self):
        """Roadmap requires direct Captured -> Qualified."""
        self.assertEqual(self.valid_opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.valid_opp.version, 1)

        qualified = qualify_opportunity(
            self.valid_opp.id,
            expected_version=1,
            actor=self.operator,
        )

        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(qualified.version, 2)
        self.assertIsNotNone(qualified.qualified_at)

        reloaded = Opportunity.objects.get(id=self.valid_opp.id)
        self.assertEqual(reloaded.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(reloaded.version, 2)
        self.assertIsNotNone(reloaded.qualified_at)

    def test_contacted_to_qualified_success(self):
        """Spec §20 requires Contacted -> Qualified."""
        from opportunities.services_lifecycle import mark_opportunity_contacted

        contacted = mark_opportunity_contacted(self.valid_opp.id, expected_version=1)
        self.assertEqual(contacted.status, OpportunityStatus.CONTACTED)
        self.assertEqual(contacted.version, 2)

        qualified = qualify_opportunity(
            self.valid_opp.id,
            expected_version=2,
            actor=self.operator,
        )
        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(qualified.version, 3)

    def test_already_qualified_raises_invalid_transition(self):
        qualify_opportunity(self.valid_opp.id, expected_version=1, actor=self.operator)
        with self.assertRaises(InvalidTransitionError):
            qualify_opportunity(self.valid_opp.id, expected_version=2, actor=self.operator)

    def test_terminal_status_cannot_be_qualified(self):
        from opportunities.services_lifecycle import reject_opportunity

        reject_opportunity(self.valid_opp.id, expected_version=1, reason="Test rejection")
        with self.assertRaises(InvalidTransitionError):
            qualify_opportunity(self.valid_opp.id, expected_version=2, actor=self.operator)

    def test_on_hold_opportunity_cannot_be_qualified_directly(self):
        from opportunities.services_lifecycle import put_opportunity_on_hold

        put_opportunity_on_hold(self.valid_opp.id, expected_version=1, reason="Test pause")
        with self.assertRaises(InvalidTransitionError):
            qualify_opportunity(self.valid_opp.id, expected_version=2, actor=self.operator)

    def test_missing_expected_version_raises_invalid_version(self):
        with self.assertRaises(InvalidVersionError):
            qualify_opportunity(self.valid_opp.id, expected_version=None, actor=self.operator)

    def test_stale_expected_version_raises_stale_version_error(self):
        with self.assertRaises(StaleVersionError):
            qualify_opportunity(self.valid_opp.id, expected_version=99, actor=self.operator)

    def test_external_counterparty_opportunity_qualifies(self):
        """ExternalCounterparty Opportunity qualifies without onboarding external parties."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty_id=self.ext_supplier.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("2000.000"),
            unit="MT",
            indicative_price=Decimal("340.00"),
            currency="USD",
            geography="Sharjah, UAE",
            delivery_window_start=datetime.date(2026, 12, 1),
            delivery_window_end=datetime.date(2026, 12, 15),
            payment_terms="TT in advance",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        qualified = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(qualified.external_counterparty_id, self.ext_supplier.id)

    def test_broker_referral_key_scenario(self):
        """
        Key scenario from spec hero flow:
        External Supplier + Supply Opportunity + Broker Referral + Qualified.
        Broker attribution and provenance MUST remain unchanged.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty_id=self.ext_supplier.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1200.000"),
            unit="MT",
            indicative_price=Decimal("355.00"),
            currency="USD",
            geography="Dubai, UAE",
            delivery_window_start=datetime.date(2026, 12, 1),
            delivery_window_end=datetime.date(2026, 12, 31),
            payment_terms="LC 30 days",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        qualified = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(qualified.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(qualified.broker_id, self.broker_org.id)
        self.assertEqual(qualified.external_counterparty_id, self.ext_supplier.id)

    def test_contact_attempt_is_not_required_for_qualification(self):
        """Confirm that zero contact attempts does not prevent qualification."""
        self.assertEqual(self.valid_opp.contact_attempts.count(), 0)
        qualified = qualify_opportunity(self.valid_opp.id, expected_version=1, actor=self.operator)
        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)

    def test_open_follow_up_tasks_do_not_block_qualification(self):
        """Confirm that open follow-up tasks do not block qualification."""
        create_opportunity_task(
            self.valid_opp.id,
            title="Inspect quality certificate",
            due_at=timezone.now() + datetime.timedelta(days=2),
            actor=self.operator,
        )
        self.assertEqual(self.valid_opp.tasks.count(), 1)
        qualified = qualify_opportunity(self.valid_opp.id, expected_version=1, actor=self.operator)
        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)

    def test_atomic_rollback_on_qualification_failure(self):
        """Simulate an unqualifiable opportunity; verify state is completely untouched."""
        Opportunity.objects.filter(id=self.valid_opp.id).update(geography="")
        self.valid_opp.refresh_from_db()

        with self.assertRaises(OpportunityQualificationError):
            qualify_opportunity(self.valid_opp.id, expected_version=1, actor=self.operator)

        self.valid_opp.refresh_from_db()
        self.assertEqual(self.valid_opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.valid_opp.version, 1)
        self.assertIsNone(self.valid_opp.qualified_at)


class OpportunityQualificationAPITests(TestCase):
    """
    API integration tests for POST /api/opportunities/opportunities/{id}/qualify/.
    Verifies authorization, request validation, structured error contracts,
    readiness projection, and mass-assignment protection.
    """

    def setUp(self):
        self.client = APIClient()

        # Actors
        self.operator = User.objects.create_user(email="operator@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.product_admin = User.objects.create_user(email="admin@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.product_admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        self.buyer_user = User.objects.create_user(email="buyer@test.local", password="password")
        self.supplier_user = User.objects.create_user(email="supplier@test.local", password="password")
        self.broker_user = User.objects.create_user(email="broker@test.local", password="password")
        self.staff_only_user = User.objects.create_user(
            email="staff@test.local", password="password", is_staff=True
        )
        self.superuser_only_user = User.objects.create_superuser(
            email="super@test.local", password="password"
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_api_qualify",
            name_en="Bitumen API Qualify",
            name_fa="قیر تست صلاحیت",
            is_active=True,
        )

        self.buyer_org = Organization.objects.create(name="API Test Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
        )

        self.broker_org = Organization.objects.create(name="API Test Broker Org")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
        )

        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("375.00"),
            currency="USD",
            geography="Rotterdam, Netherlands",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="LC at sight",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        self.qualify_url = f"/api/opportunities/opportunities/{self.opp.id}/qualify/"
        self.detail_url = f"/api/opportunities/opportunities/{self.opp.id}/"

    # -------------------------------------------------------------------------
    # Authorization Tests
    # -------------------------------------------------------------------------

    def test_operator_authorized_to_qualify(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.QUALIFIED)
        self.assertEqual(res.data["version"], 2)

    def test_product_admin_authorized_to_qualify(self):
        self.client.force_authenticate(user=self.product_admin)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.QUALIFIED)

    def test_buyer_denied(self):
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_denied(self):
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_broker_denied(self):
        self.client.force_authenticate(user=self.broker_user)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_staff_only_without_system_role_denied(self):
        self.client.force_authenticate(user=self.staff_only_user)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_superuser_only_without_system_role_denied(self):
        self.client.force_authenticate(user=self.superuser_only_user)
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_denied(self):
        self.client.logout()
        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # -------------------------------------------------------------------------
    # Structured Error Contract Tests
    # -------------------------------------------------------------------------

    def test_missing_requirements_returns_structured_400(self):
        self.client.force_authenticate(user=self.operator)
        Opportunity.objects.filter(id=self.opp.id).update(geography="", payment_terms="")
        self.opp.refresh_from_db()

        res = self.client.post(self.qualify_url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res.data["qualifiable"])
        missing_fields = [item["field"] for item in res.data["missing_requirements"]]
        self.assertIn("geography", missing_fields)
        self.assertIn("payment_terms", missing_fields)

    def test_stale_expected_version_returns_409_conflict(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(self.qualify_url, {"expected_version": 42}, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version error", res.data["detail"])

    def test_missing_expected_version_returns_400(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(self.qualify_url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # Readiness Indicators in OpportunityDetailSerializer
    # -------------------------------------------------------------------------

    def test_readiness_indicator_when_qualifiable(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.get(self.detail_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["can_qualify"])
        self.assertEqual(res.data["qualification_issues"], [])

    def test_readiness_indicator_when_unqualifiable(self):
        self.client.force_authenticate(user=self.operator)
        Opportunity.objects.filter(id=self.opp.id).update(geography="")
        res = self.client.get(self.detail_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["can_qualify"])
        issues = res.data["qualification_issues"]
        self.assertTrue(any(i["field"] == "geography" for i in issues))

    # -------------------------------------------------------------------------
    # Mass-Assignment & Mutation Protection
    # -------------------------------------------------------------------------

    def test_generic_patch_cannot_write_status_or_qualified_at(self):
        self.client.force_authenticate(user=self.operator)
        res = self.client.patch(
            self.detail_url,
            {
                "status": OpportunityStatus.QUALIFIED,
                "qualified_at": timezone.now().isoformat(),
                "version": 99,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opp.version, 2)  # incremented by valid update
        self.assertIsNone(self.opp.qualified_at)
