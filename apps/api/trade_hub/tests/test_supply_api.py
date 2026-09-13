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
    OrganizationCommodity,
    OrganizationMembership,
)
from trade_hub.models import SupplyListing, SupplyListingStatus, SupplyListingVisibility
from trade_hub.services import activate_supply


def _setup_api_test_data():
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

    # Supplier Organization A
    supplier_org_a = Organization.objects.create(
        name="Gulf Bitumen Refineries",
        registration_identifier="REG-SUP-A01",
        country="AE",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=supplier_org_a,
        capability=OrganizationCapability.CapabilityType.SUPPLIER,
    )

    # Supplier Organization B
    supplier_org_b = Organization.objects.create(
        name="Oman Bitumen Industries",
        registration_identifier="REG-SUP-B02",
        country="OM",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=supplier_org_b,
        capability=OrganizationCapability.CapabilityType.SUPPLIER,
    )

    # Buyer-only Organization C
    buyer_org = Organization.objects.create(
        name="Emirates Asphalt Buyers",
        registration_identifier="REG-BUY-C03",
        country="AE",
        is_active=True,
    )
    OrganizationCapability.objects.create(
        organization=buyer_org,
        capability=OrganizationCapability.CapabilityType.BUYER,
    )

    # Users for Supplier Org A
    owner_a = User.objects.create_user(email="owner_a@test.com")
    OrganizationMembership.objects.create(
        organization=supplier_org_a,
        user=owner_a,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    manager_a = User.objects.create_user(email="manager_a@test.com")
    OrganizationMembership.objects.create(
        organization=supplier_org_a,
        user=manager_a,
        role=OrganizationMembership.OrganizationRole.MANAGER,
        is_active=True,
    )

    member_a = User.objects.create_user(email="member_a@test.com")
    OrganizationMembership.objects.create(
        organization=supplier_org_a,
        user=member_a,
        role=OrganizationMembership.OrganizationRole.MEMBER,
        is_active=True,
    )

    viewer_a = User.objects.create_user(email="viewer_a@test.com")
    OrganizationMembership.objects.create(
        organization=supplier_org_a,
        user=viewer_a,
        role=OrganizationMembership.OrganizationRole.VIEWER,
        is_active=True,
    )

    # User for Supplier Org B (Foreign)
    owner_b = User.objects.create_user(email="owner_b@test.com")
    OrganizationMembership.objects.create(
        organization=supplier_org_b,
        user=owner_b,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    # User for Buyer Org C
    buyer_owner = User.objects.create_user(email="buyer_owner@test.com")
    OrganizationMembership.objects.create(
        organization=buyer_org,
        user=buyer_owner,
        role=OrganizationMembership.OrganizationRole.OWNER,
        is_active=True,
    )

    # Platform Operator
    operator_user = User.objects.create_user(email="operator@platform.com")
    SystemRoleAssignment.objects.create(
        user=operator_user,
        role=SystemRoleAssignment.SystemRole.OPERATOR,
    )

    # Platform Admin
    admin_user = User.objects.create_user(email="admin@platform.com")
    SystemRoleAssignment.objects.create(
        user=admin_user,
        role=SystemRoleAssignment.SystemRole.ADMIN,
    )

    # Django Staff only (no system role)
    staff_user = User.objects.create_user(
        email="staff@platform.com", is_staff=True
    )

    return {
        "bitumen": bitumen,
        "bitumen_v1": bitumen_v1,
        "base_oil": base_oil,
        "base_oil_v1": base_oil_v1,
        "supplier_org_a": supplier_org_a,
        "supplier_org_b": supplier_org_b,
        "buyer_org": buyer_org,
        "owner_a": owner_a,
        "manager_a": manager_a,
        "member_a": member_a,
        "viewer_a": viewer_a,
        "owner_b": owner_b,
        "buyer_owner": buyer_owner,
        "operator_user": operator_user,
        "admin_user": admin_user,
        "staff_user": staff_user,
    }


class SupplyListingAuthorizationAPITests(TestCase):
    def setUp(self):
        self.data = _setup_api_test_data()
        self.client = APIClient()

    def test_supplier_owner_can_create_draft(self):
        """Supplier Owner can create a new Supply Listing draft."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "2500.000",
            "unit": "MT",
            "indicative_price": "365.00",
            "currency": "USD",
            "origin": "Bandar Abbas",
            "specifications": {"penetration_grade": "60/70", "softening_point": 49.0},
            "visibility": "public",
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(response.data["quantity"], "2500.000")
        self.assertEqual(response.data["indicative_price"], "365.00")
        self.assertFalse(response.data["created_by_operator"])

    def test_supplier_manager_can_create_draft(self):
        """Supplier Manager can create a new Supply Listing draft."""
        self.client.force_authenticate(user=self.data["manager_a"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 201)

    def test_supplier_member_denied_create_draft(self):
        """Supplier Member cannot create a Supply Listing draft (403 Forbidden)."""
        self.client.force_authenticate(user=self.data["member_a"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 403)

    def test_supplier_viewer_denied_create_draft(self):
        """Supplier Viewer cannot create a Supply Listing draft (403 Forbidden)."""
        self.client.force_authenticate(user=self.data["viewer_a"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 403)

    def test_buyer_only_organization_denied_create_draft(self):
        """Organization lacking Supplier capability cannot create a Supply Listing draft (403 Forbidden)."""
        self.client.force_authenticate(user=self.data["buyer_owner"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 403)

    def test_client_spoofing_organization_prevented(self):
        """Regular user passing another organization's ID has it ignored; bound to session org."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {
            "organization_id": str(self.data["supplier_org_b"].id),  # Spoofing Org B
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        # Authoritative organization is Org A, NOT Org B
        self.assertEqual(response.data["organization"]["id"], str(self.data["supplier_org_a"].id))

    def test_platform_operator_can_create_on_behalf_of_supplier(self):
        """Platform Operator can create supply listing on behalf of target supplier."""
        self.client.force_authenticate(user=self.data["operator_user"])
        payload = {
            "organization_id": str(self.data["supplier_org_a"].id),
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "5000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["organization"]["id"], str(self.data["supplier_org_a"].id))
        self.assertTrue(response.data["created_by_operator"])

    def test_django_staff_alone_denied(self):
        """Django staff user without system role assignment cannot create supply listing."""
        self.client.force_authenticate(user=self.data["staff_user"])
        payload = {
            "commodity_id": str(self.data["bitumen"].id),
            "schema_version_id": str(self.data["bitumen_v1"].id),
            "quantity": "1000.000",
            "specifications": {"penetration_grade": "60/70"},
        }
        response = self.client.post("/api/trade-hub/supply-listings/", payload, format="json")
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_denied(self):
        """Unauthenticated caller receives 401 or 403."""
        response = self.client.post("/api/trade-hub/supply-listings/", {}, format="json")
        self.assertIn(response.status_code, (401, 403))


class SupplyListingDraftUpdateAPITests(TestCase):
    def setUp(self):
        self.data = _setup_api_test_data()
        self.client = APIClient()
        self.listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            indicative_price=Decimal("350.00"),
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

    def test_update_draft_fields_success(self):
        """Approved draft fields can be updated with expected_version."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {
            "expected_version": 1,
            "quantity": "1800.000",
            "indicative_price": "375.50",
            "origin": "Sharjah Port",
            "notes": "Internal warehouse notes",
            "specifications": {"penetration_grade": "85/100", "softening_point": 48.5},
        }
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["quantity"], "1800.000")
        self.assertEqual(response.data["indicative_price"], "375.50")
        self.assertEqual(response.data["origin"], "Sharjah Port")
        self.assertEqual(response.data["notes"], "Internal warehouse notes")

    def test_mass_assignment_of_system_fields_prevented(self):
        """Client attempting to mutate status, version, or organization in PATCH is thwarted."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {
            "expected_version": 1,
            "quantity": "1200.000",
            "status": "active",
            "version": 99,
            "organization_id": str(self.data["supplier_org_b"].id),
            "created_by_operator": True,
        }
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["version"], 2)
        self.assertEqual(response.data["organization"]["id"], str(self.data["supplier_org_a"].id))
        self.assertFalse(response.data["created_by_operator"])

    def test_stale_expected_version_returns_409_conflict(self):
        """Passing stale expected_version returns HTTP 409 Conflict."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {"expected_version": 99, "quantity": "2000.000"}
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", payload, format="json")
        self.assertEqual(response.status_code, 409)

    def test_missing_expected_version_returns_400_bad_request(self):
        """Omitting expected_version returns HTTP 400 Bad Request."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {"quantity": "2000.000"}
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("expected_version", response.data)

    def test_cannot_update_active_listing(self):
        """Attempting to update an Active listing returns 400 Bad Request."""
        activate_supply(self.listing.id, expected_version=1)
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {"expected_version": 2, "quantity": "5000.000"}
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only draft listings can be modified", response.data["detail"])

    def test_safe_commodity_switching_in_draft(self):
        """Switching commodity from Bitumen to Base Oil re-validates specs against new schema."""
        self.client.force_authenticate(user=self.data["owner_a"])
        # Attempt switch with invalid Base Oil specs (missing viscosity_index)
        bad_payload = {
            "expected_version": 1,
            "commodity_id": str(self.data["base_oil"].id),
            "schema_version_id": str(self.data["base_oil_v1"].id),
            "specifications": {"penetration_grade": "60/70"},  # Bitumen spec!
        }
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", bad_payload, format="json")
        self.assertEqual(response.status_code, 400)

        # Successful switch with valid Base Oil specs
        good_payload = {
            "expected_version": 1,
            "commodity_id": str(self.data["base_oil"].id),
            "schema_version_id": str(self.data["base_oil_v1"].id),
            "specifications": {"viscosity_index": 100},
        }
        response = self.client.patch(f"/api/trade-hub/supply-listings/{self.listing.id}/", good_payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["commodity_code"], "base_oil")
        self.assertEqual(response.data["specifications"]["viscosity_index"], 100)


class SupplyListingActivationAndCloseAPITests(TestCase):
    def setUp(self):
        self.data = _setup_api_test_data()
        self.client = APIClient()
        self.listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            indicative_price=Decimal("350.00"),
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

    def test_activate_draft_listing_success(self):
        """Explicit activate action transitions Draft to Active and freezes version."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {"expected_version": 1}
        response = self.client.post(
            f"/api/trade-hub/supply-listings/{self.listing.id}/activate/", payload, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "active")
        self.assertEqual(response.data["version"], 2)
        self.assertIsNotNone(response.data["activated_at"])

    def test_close_listing_success(self):
        """Close action transitions listing to Closed."""
        self.client.force_authenticate(user=self.data["owner_a"])
        payload = {"expected_version": 1}
        response = self.client.post(
            f"/api/trade-hub/supply-listings/{self.listing.id}/close/", payload, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "closed")
        self.assertEqual(response.data["version"], 2)

    def test_unauthorized_user_cannot_activate_or_close(self):
        """Member of organization or foreign supplier cannot activate or close listing."""
        self.client.force_authenticate(user=self.data["member_a"])
        response = self.client.post(
            f"/api/trade-hub/supply-listings/{self.listing.id}/activate/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(user=self.data["owner_b"])
        response = self.client.post(
            f"/api/trade-hub/supply-listings/{self.listing.id}/activate/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class SupplyListingHistoricalIntegrityAPITests(TestCase):
    def setUp(self):
        self.data = _setup_api_test_data()
        self.client = APIClient()

    def test_historical_schema_version_integrity(self):
        """
        Regression: Listing created with schema v1.
        New v2 schema is published and activated for commodity.
        Listing remains bound to v1 and valid.
        """
        listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70", "softening_point": 49.0},
            quantity=Decimal("1000.000"),
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

        # Publish and activate Bitumen schema v2 with a new required attribute
        bitumen_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.data["bitumen"],
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=bitumen_v2,
            key="flash_point",
            label_fa="نقطه اشتعال",
            label_en="Flash Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,  # New required attribute in v2!
            sort_order=1,
        )
        publish_schema(bitumen_v2, activate=True)

        # Reload listing and verify it remains bound to v1
        self.client.force_authenticate(user=self.data["owner_a"])
        response = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["schema_version_number"], 1)

        # Activate listing: must validate against stored v1 (not v2, which would fail due to missing flash_point)
        act_resp = self.client.post(
            f"/api/trade-hub/supply-listings/{listing.id}/activate/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(act_resp.status_code, 200)
        self.assertEqual(act_resp.data["status"], "active")
        self.assertEqual(act_resp.data["schema_version_number"], 1)


class SupplyListingVisibilityAPITests(TestCase):
    def setUp(self):
        self.data = _setup_api_test_data()
        self.client = APIClient()

    def test_draft_is_hidden_from_external_organizations(self):
        """Draft supply listing is hidden from external organizations (404 on direct ID)."""
        listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            status=SupplyListingStatus.DRAFT,
            visibility=SupplyListingVisibility.PUBLIC,
        )

        # Owner can see draft
        self.client.force_authenticate(user=self.data["owner_a"])
        resp_owner = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(resp_owner.status_code, 200)

        # Operator can see draft
        self.client.force_authenticate(user=self.data["operator_user"])
        resp_op = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(resp_op.status_code, 200)

        # External Buyer sees 404 (hidden)
        self.client.force_authenticate(user=self.data["buyer_owner"])
        resp_buyer = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(resp_buyer.status_code, 404)

        # External Supplier sees 404 (hidden)
        self.client.force_authenticate(user=self.data["owner_b"])
        resp_supp_b = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(resp_supp_b.status_code, 404)

    def test_active_public_visible_with_safe_projection(self):
        """Active Public listing is visible to external buyers, with internal notes stripped."""
        listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            indicative_price=Decimal("350.00"),
            notes="Secret internal cost margin notes",
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
            version=2,
        )

        # External buyer gets safe projection
        self.client.force_authenticate(user=self.data["buyer_owner"])
        response = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["quantity"], "1000.000")
        self.assertEqual(response.data["indicative_price"], "350.00")
        self.assertNotIn("notes", response.data)
        self.assertNotIn("created_by_operator", response.data)

        # Owner gets full projection with internal notes
        self.client.force_authenticate(user=self.data["owner_a"])
        resp_owner = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(resp_owner.status_code, 200)
        self.assertEqual(resp_owner.data["notes"], "Secret internal cost margin notes")

    def test_active_network_visibility_scoping(self):
        """Active Network listing is visible only to orgs with matching OrganizationCommodity."""
        listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.NETWORK,
            version=2,
        )

        # Buyer org NOT associated with Bitumen sees 404
        self.client.force_authenticate(user=self.data["buyer_owner"])
        response = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(response.status_code, 404)

        # Associate Buyer org with Bitumen
        OrganizationCommodity.objects.create(
            organization=self.data["buyer_org"],
            commodity=self.data["bitumen"],
        )

        # Now Buyer org CAN see listing
        response_assoc = self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/")
        self.assertEqual(response_assoc.status_code, 200)

    def test_active_private_visible_only_to_owner_and_operator(self):
        """Active Private listing is visible only to the owning supplier and operator."""
        listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PRIVATE,
            version=2,
        )

        # External Buyer sees 404
        self.client.force_authenticate(user=self.data["buyer_owner"])
        self.assertEqual(self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/").status_code, 404)

        # Owner sees 200
        self.client.force_authenticate(user=self.data["owner_a"])
        self.assertEqual(self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/").status_code, 200)

        # Operator sees 200
        self.client.force_authenticate(user=self.data["operator_user"])
        self.assertEqual(self.client.get(f"/api/trade-hub/supply-listings/{listing.id}/").status_code, 200)


class SupplyListingAPIConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded API concurrency tests:
    1. update vs update race -> exactly one 200 OK, one 409 Conflict.
    2. update vs activate race -> update cannot overwrite state once activated.
    """

    def setUp(self):
        self.data = _setup_api_test_data()
        self.listing = SupplyListing.objects.create(
            organization=self.data["supplier_org_a"],
            created_by=self.data["owner_a"],
            commodity=self.data["bitumen"],
            schema_version=self.data["bitumen_v1"],
            quantity=Decimal("1000.000"),
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.DRAFT,
            version=1,
        )

    def test_api_update_vs_update_race(self):
        """Two concurrent API clients attempt to update Draft listing with expected_version=1."""
        barrier = threading.Barrier(2)
        results = {}

        def thread_update_1():
            client = APIClient()
            client.force_authenticate(user=self.data["owner_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.patch(
                    f"/api/trade-hub/supply-listings/{self.listing.id}/",
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
                    f"/api/trade-hub/supply-listings/{self.listing.id}/",
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

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.version, 2)
        self.assertEqual(self.listing.status, SupplyListingStatus.DRAFT)

    def test_api_update_vs_activate_race(self):
        """Two concurrent threads race: one updates draft, one activates. Both pass expected_version=1."""
        barrier = threading.Barrier(2)
        results = {}

        def thread_update():
            client = APIClient()
            client.force_authenticate(user=self.data["owner_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.patch(
                    f"/api/trade-hub/supply-listings/{self.listing.id}/",
                    {"expected_version": 1, "quantity": "5000.000"},
                    format="json",
                )
                results["update"] = resp.status_code
            except Exception as exc:
                results["update"] = exc
            finally:
                connection.close()

        def thread_activate():
            client = APIClient()
            client.force_authenticate(user=self.data["owner_a"])
            try:
                barrier.wait()
                time.sleep(0.01)
                resp = client.post(
                    f"/api/trade-hub/supply-listings/{self.listing.id}/activate/",
                    {"expected_version": 1},
                    format="json",
                )
                results["activate"] = resp.status_code
            except Exception as exc:
                results["activate"] = exc
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_update)
        t2 = threading.Thread(target=thread_activate)

        t1.start()
        t2.start()

        t1.join(timeout=10)
        t2.join(timeout=10)

        codes = list(results.values())
        self.assertIn(200, codes, f"Expected exactly one 200 OK, got: {results}")
        self.assertIn(409, codes, f"Expected one 409 Conflict, got: {results}")

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.version, 2)
