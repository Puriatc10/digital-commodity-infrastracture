from decimal import Decimal
import threading
import time

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment, User
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQInvitation, RFQInvitationStatus, RFQStatus


def _setup_test_data():
    """Create test users, organizations, capabilities, memberships, and commodities."""
    # Commodity 1: Bitumen
    bitumen = CommodityDefinition.objects.create(
        code="bitumen",
        name_fa="قیر",
        name_en="Bitumen",
        is_active=True,
    )
    bitumen_v1 = CommoditySchemaVersion.objects.create(
        commodity=bitumen,
        version=1,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=bitumen_v1,
        key="penetration_grade",
        label_fa="درجه نفوذ",
        label_en="Penetration Grade",
        data_type=CommodityAttributeDefinition.DataType.STRING,
        is_required=True,
        sort_order=1,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=bitumen_v1,
        key="softening_point",
        label_fa="نقطه نرمی",
        label_en="Softening Point",
        data_type=CommodityAttributeDefinition.DataType.NUMBER,
        is_required=False,
        sort_order=2,
    )
    publish_schema(bitumen_v1, activate=True)

    # Commodity 2: Base Oil
    base_oil = CommodityDefinition.objects.create(
        code="base_oil",
        name_fa="روغن پایه",
        name_en="Base Oil",
        is_active=True,
    )
    base_oil_v1 = CommoditySchemaVersion.objects.create(
        commodity=base_oil,
        version=1,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=base_oil_v1,
        key="viscosity_index",
        label_fa="شاخص گرانروی",
        label_en="Viscosity Index",
        data_type=CommodityAttributeDefinition.DataType.INTEGER,
        is_required=True,
        sort_order=1,
    )
    publish_schema(base_oil_v1, activate=True)

    # Buyer Organization A
    buyer_org_a = Organization.objects.create(
        name="Gulf Petrochem Trading",
        registration_identifier="REG-GULF-01",
        country="AE",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=buyer_org_a,
        capability=OrganizationCapability.CapabilityType.BUYER,
    )

    # Buyer Organization B
    buyer_org_b = Organization.objects.create(
        name="Oman Refineries",
        registration_identifier="REG-OMAN-02",
        country="OM",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=buyer_org_b,
        capability=OrganizationCapability.CapabilityType.BUYER,
    )

    # Supplier-only Organization
    supplier_org = Organization.objects.create(
        name="Iran Bitumen Refineries",
        registration_identifier="REG-IRAN-03",
        country="IR",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=supplier_org,
        capability=OrganizationCapability.CapabilityType.SUPPLIER,
    )

    # Users for Buyer Org A
    owner_a = User.objects.create_user(
        email="owner_a@petrochem.ae",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=owner_a,
        organization=buyer_org_a,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    manager_a = User.objects.create_user(
        email="manager_a@petrochem.ae",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=manager_a,
        organization=buyer_org_a,
        role=OrganizationMembership.OrganizationRole.MANAGER,
        is_active=True,
    )

    member_a = User.objects.create_user(
        email="member_a@petrochem.ae",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=member_a,
        organization=buyer_org_a,
        role=OrganizationMembership.OrganizationRole.MEMBER,
        is_active=True,
    )

    viewer_a = User.objects.create_user(
        email="viewer_a@petrochem.ae",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=viewer_a,
        organization=buyer_org_a,
        role=OrganizationMembership.OrganizationRole.VIEWER,
        is_active=True,
    )

    # User for Buyer Org B
    owner_b = User.objects.create_user(
        email="owner_b@omanref.om",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=owner_b,
        organization=buyer_org_b,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    # User for Supplier Org
    supplier_user = User.objects.create_user(
        email="supplier@iranbitumen.ir",
        password="TestPassword123!",
    )
    OrganizationMembership.objects.create(
        user=supplier_user,
        organization=supplier_org,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    # Platform Operator
    operator_user = User.objects.create_user(
        email="operator@platform.com",
        password="TestPassword123!",
    )
    SystemRoleAssignment.objects.create(
        user=operator_user,
        role=SystemRoleAssignment.SystemRole.OPERATOR,
    )

    # Product Admin
    admin_user = User.objects.create_user(
        email="admin@platform.com",
        password="TestPassword123!",
    )
    SystemRoleAssignment.objects.create(
        user=admin_user,
        role=SystemRoleAssignment.SystemRole.ADMIN,
    )

    # Django Staff User without system role
    staff_user = User.objects.create_user(
        email="staff@platform.com",
        password="TestPassword123!",
        is_staff=True,
    )

    return {
        "bitumen": bitumen,
        "bitumen_v1": bitumen_v1,
        "base_oil": base_oil,
        "base_oil_v1": base_oil_v1,
        "buyer_org_a": buyer_org_a,
        "buyer_org_b": buyer_org_b,
        "supplier_org": supplier_org,
        "owner_a": owner_a,
        "manager_a": manager_a,
        "member_a": member_a,
        "viewer_a": viewer_a,
        "owner_b": owner_b,
        "supplier_user": supplier_user,
        "operator_user": operator_user,
        "admin_user": admin_user,
        "staff_user": staff_user,
    }


class RFQBuilderAuthorizationTests(TestCase):
    """Verify authorization matrix across business roles, system roles, and capabilities."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

    def test_buyer_owner_can_create_draft(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "unit": "MT",
                "specifications": {"penetration_grade": "60/70", "softening_point": 49.0},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(response.data["organization"]["id"], str(self.data["buyer_org_a"].id))
        self.assertFalse(response.data["created_by_operator"])

    def test_buyer_manager_can_create_draft(self):
        self.client.force_authenticate(user=self.data["manager_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_buyer_member_denied_create_draft(self):
        self.client.force_authenticate(user=self.data["member_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_buyer_viewer_denied_create_draft(self):
        self.client.force_authenticate(user=self.data["viewer_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_buyer_org_denied_create_draft(self):
        """Supplier-only organization lacks Buyer capability and is denied."""
        self.client.force_authenticate(user=self.data["supplier_user"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Buyer capability", response.data["detail"])

    def test_django_staff_alone_denied(self):
        """Django staff user without SystemRoleAssignment has no Product authority."""
        self.client.force_authenticate(user=self.data["staff_user"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_can_create_on_behalf_of_buyer(self):
        self.client.force_authenticate(user=self.data["operator_user"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "organization_id": str(self.data["buyer_org_a"].id),
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1200.000",
                "unit": "MT",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created_by_operator"])
        self.assertEqual(response.data["organization"]["id"], str(self.data["buyer_org_a"].id))

    def test_admin_can_create_on_behalf_of_buyer(self):
        self.client.force_authenticate(user=self.data["admin_user"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "organization_id": str(self.data["buyer_org_b"].id),
                "commodity_id": str(self.data["base_oil"].id),
                "schema_version_id": str(self.data["base_oil_v1"].id),
                "quantity": "800.000",
                "unit": "MT",
                "specifications": {"viscosity_index": 105},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created_by_operator"])
        self.assertEqual(response.data["organization"]["id"], str(self.data["buyer_org_b"].id))


class RFQBuilderCreationAndMassAssignmentTests(TestCase):
    """Verify Draft creation, field persistence, and immunity to mass-assignment attacks."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

    def test_create_valid_draft_all_fields(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1500.000",
            "unit": "MT",
            "specifications": {"penetration_grade": "60/70", "softening_point": 49.5},
            "target_price": "385.50",
            "currency": "USD",
            "payment_terms": "LC at sight",
            "incoterm": "FOB",
            "origin": "Bandar Abbas",
            "destination": "Jebel Ali",
            "delivery_window_start": "2026-10-01",
            "delivery_window_end": "2026-10-20",
            "submission_deadline": "2026-09-25T12:00:00Z",
            "inspection_required": True,
            "quality_notes": "SGS certificate required.",
            "notes": "Fast turnaround preferred.",
            "visibility": "network",
        }
        response = self.client.post("/api/trade-hub/rfqs/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["quantity"], "1500.000")
        self.assertEqual(response.data["unit"], "MT")
        self.assertEqual(response.data["target_price"], "385.50")
        self.assertEqual(response.data["currency"], "USD")
        self.assertEqual(response.data["payment_terms"], "LC at sight")
        self.assertEqual(response.data["incoterm"], "FOB")
        self.assertEqual(response.data["origin"], "Bandar Abbas")
        self.assertEqual(response.data["destination"], "Jebel Ali")
        self.assertEqual(response.data["delivery_window_start"], "2026-10-01")
        self.assertEqual(response.data["delivery_window_end"], "2026-10-20")
        self.assertTrue(response.data["inspection_required"])
        self.assertEqual(response.data["quality_notes"], "SGS certificate required.")
        self.assertEqual(response.data["notes"], "Fast turnaround preferred.")
        self.assertEqual(response.data["visibility"], "network")
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["version"], 1)

    def test_mass_assignment_status_ignored(self):
        """Passing status='published' during creation does not bypass Draft status."""
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
                "status": "published",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")
        self.assertIsNone(response.data["published_at"])

    def test_mass_assignment_version_ignored(self):
        """Passing version=99 during creation does not alter initial version 1."""
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
                "version": 99,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["version"], 1)

    def test_mass_assignment_buyer_organization_denied(self):
        """Non-operator cannot specify a different buyer organization."""
        self.client.force_authenticate(user=self.data["owner_a"])
        # Attempt to create on behalf of Org B
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "organization_id": str(self.data["buyer_org_b"].id),
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "500.000",
                "unit": "MT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        # Authoritative context forces Org A
        self.assertEqual(response.data["organization"]["id"], str(self.data["buyer_org_a"].id))


class RFQBuilderSpecificationsTests(TestCase):
    """Verify dynamic commodity specification validation across multiple commodities."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

    def test_valid_bitumen_specifications(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70", "softening_point": 48.5},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["specifications"]["penetration_grade"], "60/70")
        self.assertEqual(response.data["specifications"]["softening_point"], 48.5)

    def test_valid_base_oil_specifications(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["base_oil"].id),
                "schema_version_id": str(self.data["base_oil_v1"].id),
                "quantity": "750.000",
                "specifications": {"viscosity_index": 98},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["specifications"]["viscosity_index"], 98)

    def test_invalid_type_specification_returns_structured_errors(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {
                    "penetration_grade": "60/70",
                    "softening_point": "not_a_float",  # should be number
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.data)
        self.assertTrue(
            any(
                e["field"] == "softening_point" and e["code"] == "invalid_type"
                for e in response.data["errors"]
            )
        )

    def test_unknown_specification_attribute_rejected(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {
                    "penetration_grade": "60/70",
                    "non_existent_field": 42,
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.data)
        self.assertTrue(
            any(
                e["field"] == "non_existent_field" and e["code"] == "unknown_field"
                for e in response.data["errors"]
            )
        )

    def test_commodity_schema_version_mismatch_rejected(self):
        """Attempting to pair Bitumen commodity with Base Oil schema version returns 400."""
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["base_oil_v1"].id),
                "quantity": "1000.000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("schema_version_id", str(response.data))


class RFQBuilderHistoricalSchemaTests(TestCase):
    """Verify stored schema version permanence: published v2 does not reinterpret v1 Drafts."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

        # Create draft RFQ with Bitumen v1
        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.rfq_id = resp.data["id"]

        # Now publish Bitumen v2 with an extra required attribute
        self.bitumen_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.data["bitumen"],
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v2,
            key="flash_point",
            label_fa="نقطه اشتعال",
            label_en="Flash Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=2,
        )
        publish_schema(self.bitumen_v2, activate=True)

    def test_v1_draft_remains_authoritative_after_v2_published(self):
        """Updating v1 draft still validates against v1 schema without requiring v2 fields."""
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {
                "expected_version": 1,
                "specifications": {"penetration_grade": "85/100"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["schema_version_number"], 1)

    def test_v1_draft_publishes_using_stored_schema_version(self):
        """Publishing v1 draft succeeds under v1 rules without requiring v2 flash_point."""
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "published")
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["schema_version_number"], 1)


class RFQBuilderDraftUpdateTests(TestCase):
    """Verify Draft updates, optimistic concurrency, and safe commodity switching."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "unit": "MT",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.rfq_id = resp.data["id"]

    def test_successful_update_increments_version(self):
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {
                "expected_version": 1,
                "quantity": "2000.000",
                "payment_terms": "100% LC at sight",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["quantity"], "2000.000")
        self.assertEqual(response.data["payment_terms"], "100% LC at sight")
        self.assertEqual(response.data["version"], 2)

    def test_missing_expected_version_rejected(self):
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"quantity": "2000.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("expected_version", str(response.data))

    def test_null_expected_version_rejected(self):
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"expected_version": None, "quantity": "2000.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_stale_expected_version_rejected_with_409(self):
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"expected_version": 99, "quantity": "2000.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Stale version", response.data["detail"])

    def test_rollback_on_specification_validation_failure(self):
        """Failed specification update rolls back changes and does not increment version."""
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {
                "expected_version": 1,
                "quantity": "3000.000",
                "specifications": {
                    "penetration_grade": "60/70",
                    "softening_point": "invalid_type",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        # Confirm persisted record unmodified
        reloaded = RFQ.objects.get(pk=self.rfq_id)
        self.assertEqual(reloaded.version, 1)
        self.assertEqual(reloaded.quantity, Decimal("1000.000"))

    def test_safe_commodity_switching(self):
        """Switching commodity from Bitumen to Base Oil re-validates complete specifications."""
        # Attempt switch without valid Base Oil specifications -> fails
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {
                "expected_version": 1,
                "commodity_id": str(self.data["base_oil"].id),
                "schema_version_id": str(self.data["base_oil_v1"].id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        # Switch with valid Base Oil specifications -> succeeds
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {
                "expected_version": 1,
                "commodity_id": str(self.data["base_oil"].id),
                "schema_version_id": str(self.data["base_oil_v1"].id),
                "specifications": {"viscosity_index": 100},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["commodity_code"], "base_oil")
        self.assertEqual(response.data["specifications"], {"viscosity_index": 100})
        self.assertEqual(response.data["version"], 2)


class RFQBuilderPublishTests(TestCase):
    """Verify publish endpoint delegation to T0502, prerequisites, and idempotency."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

    def test_valid_publish(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        rfq_id = resp.data["id"]

        publish_resp = self.client.post(
            f"/api/trade-hub/rfqs/{rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(publish_resp.status_code, 200)
        self.assertEqual(publish_resp.data["status"], "published")
        self.assertEqual(publish_resp.data["version"], 2)
        self.assertIsNotNone(publish_resp.data["published_at"])

    def test_incomplete_rfq_publish_fails_without_mutation(self):
        """Incomplete RFQ missing required specification attribute fails publish."""
        # Create draft directly without required penetration_grade
        rfq = RFQ.objects.create(
            organization=self.data["buyer_org_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            quantity=Decimal("500.000"),
            specifications={},
        )
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.post(
            f"/api/trade-hub/rfqs/{rfq.id}/publish/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.data)

        # Confirm persisted state unmodified
        rfq.refresh_from_db()
        self.assertEqual(rfq.status, "draft")
        self.assertEqual(rfq.version, 1)
        self.assertIsNone(rfq.published_at)

    def test_repeat_publish_rejected(self):
        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        rfq_id = resp.data["id"]

        self.client.post(
            f"/api/trade-hub/rfqs/{rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )

        repeat_resp = self.client.post(
            f"/api/trade-hub/rfqs/{rfq_id}/publish/",
            {"expected_version": 2},
            format="json",
        )
        self.assertEqual(repeat_resp.status_code, 400)
        self.assertIn("Only draft RFQs can be published", repeat_resp.data["detail"])


class RFQBuilderPostPublishMutationTests(TestCase):
    """Verify post-publication frozen state cannot be mutated."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.rfq_id = resp.data["id"]
        self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )

    def test_mutation_on_published_rfq_denied(self):
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"expected_version": 2, "quantity": "9999.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only draft RFQs can be modified", response.data["detail"])


class RFQBuilderCrossOrganizationTests(TestCase):
    """Verify strict cross-organization IDOR isolation."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

        # Create Draft owned by Buyer Org A
        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
            },
            format="json",
        )
        self.rfq_id = resp.data["id"]

    def test_foreign_org_cannot_view_draft(self):
        """Owner of Org B receives 404 when querying Org A's Draft."""
        self.client.force_authenticate(user=self.data["owner_b"])
        response = self.client.get(f"/api/trade-hub/rfqs/{self.rfq_id}/")
        self.assertEqual(response.status_code, 404)

    def test_foreign_org_cannot_update_draft(self):
        """Owner of Org B receives 404/403 when attempting to update Org A's Draft."""
        self.client.force_authenticate(user=self.data["owner_b"])
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"expected_version": 1, "quantity": "5000.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_foreign_org_cannot_publish_draft(self):
        """Owner of Org B receives 403 when attempting to publish Org A's Draft."""
        self.client.force_authenticate(user=self.data["owner_b"])
        response = self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class RFQBuilderPrivateParticipationTests(TestCase):
    """Verify external visible counterparties cannot mutate RFQs and T0506 boundary is preserved."""

    def setUp(self):
        self.data = _setup_test_data()
        self.client = APIClient()

        # Create and publish a Private RFQ by Buyer Org A
        self.client.force_authenticate(user=self.data["owner_a"])
        resp = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.data["bitumen"].id),
                "schema_version_id": str(self.data["bitumen_v1"].id),
                "quantity": "1000.000",
                "specifications": {"penetration_grade": "60/70"},
                "notes": "Internal buyer secret note",
                "visibility": "private",
            },
            format="json",
        )
        self.rfq_id = resp.data["id"]
        self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
        )

        # Invite Supplier Org via T0506
        self.rfq = RFQ.objects.get(pk=self.rfq_id)
        RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.data["supplier_org"],
            status=RFQInvitationStatus.INVITED,
        )

    def test_invited_supplier_sees_public_projection_without_internal_notes(self):
        self.client.force_authenticate(user=self.data["supplier_user"])
        response = self.client.get(f"/api/trade-hub/rfqs/{self.rfq_id}/")
        self.assertEqual(response.status_code, 200)
        # Verify internal buyer notes are masked
        self.assertNotIn("notes", response.data)
        self.assertNotIn("created_by_operator", response.data)

    def test_invited_supplier_cannot_edit_rfq(self):
        self.client.force_authenticate(user=self.data["supplier_user"])
        response = self.client.patch(
            f"/api/trade-hub/rfqs/{self.rfq_id}/",
            {"expected_version": 2, "quantity": "999.000"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)  # Published + not authorized


class RFQBuilderPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded concurrency tests verifying exclusive row locks:
    1. update vs update race -> exactly one winner with same version.
    2. update vs publish race -> update cannot overwrite state once published.
    """

    def setUp(self):
        self.data = _setup_test_data()
        self.rfq = RFQ.objects.create(
            organization=self.data["buyer_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            quantity=Decimal("1000.000"),
            specifications={"penetration_grade": "60/70"},
            status=RFQStatus.DRAFT,
            version=1,
        )

    def test_update_vs_update_race(self):
        """
        Two concurrent API clients attempt to update the same Draft RFQ with expected_version=1.
        Exactly one succeeds (advances version to 2).
        The losing thread receives HTTP 409 Conflict.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_update_1():
            client = APIClient()
            client.force_authenticate(user=self.data["owner_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.patch(
                    f"/api/trade-hub/rfqs/{self.rfq.id}/",
                    {"expected_version": 1, "quantity": "2000.000"},
                    format="json",
                )
                results["t1"] = resp.status_code
            except Exception as exc:
                results["t1"] = exc
            finally:
                connection.close()

        def thread_update_2():
            client = APIClient()
            client.force_authenticate(user=self.data["manager_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.patch(
                    f"/api/trade-hub/rfqs/{self.rfq.id}/",
                    {"expected_version": 1, "quantity": "3000.000"},
                    format="json",
                )
                results["t2"] = resp.status_code
            except Exception as exc:
                results["t2"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_update_1)
        t2 = threading.Thread(target=thread_update_2)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        codes = list(results.values())
        self.assertIn(200, codes, f"Expected exactly one 200 OK, got: {results}")
        self.assertIn(409, codes, f"Expected one 409 Conflict, got: {results}")

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.version, 2)
        self.assertEqual(self.rfq.status, RFQStatus.DRAFT)

    def test_update_vs_publish_race(self):
        """
        Two concurrent threads race: one attempts to update draft, one attempts to publish.
        Both pass expected_version=1.
        Final state must NEVER contain a post-publication write based on stale Draft state.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_update():
            client = APIClient()
            client.force_authenticate(user=self.data["owner_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.patch(
                    f"/api/trade-hub/rfqs/{self.rfq.id}/",
                    {"expected_version": 1, "quantity": "9999.000"},
                    format="json",
                )
                results["update"] = resp.status_code
            except Exception as exc:
                results["update"] = exc
            finally:
                connection.close()

        def thread_publish():
            client = APIClient()
            client.force_authenticate(user=self.data["manager_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.post(
                    f"/api/trade-hub/rfqs/{self.rfq.id}/publish/",
                    {"expected_version": 1},
                    format="json",
                )
                results["publish"] = resp.status_code
            except Exception as exc:
                results["publish"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_update)
        t2 = threading.Thread(target=thread_publish)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        # Assert exactly one 200 OK and one 409 Conflict
        self.assertEqual(len([c for c in results.values() if c == 200]), 1, f"Results: {results}")
        self.assertEqual(len([c for c in results.values() if c == 409]), 1, f"Results: {results}")

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.version, 2)

        # If publish won: status is published and quantity is NOT 9999
        if results["publish"] == 200:
            self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)
            self.assertEqual(self.rfq.quantity, Decimal("1000.000"))
        else:
            # If update won: status is draft and quantity is 9999
            self.assertEqual(self.rfq.status, RFQStatus.DRAFT)
            self.assertEqual(self.rfq.quantity, Decimal("9999.000"))
