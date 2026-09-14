from decimal import Decimal
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment, User
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)


class OpportunityAPITests(TestCase):
    """
    Canonical API and authorization tests for Opportunity capture and management.
    """

    def setUp(self):
        self.client = APIClient()

        # System roles
        self.operator = User.objects.create_user(email="operator@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.admin = User.objects.create_user(email="admin@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        # Buyer user
        self.buyer_org = Organization.objects.create(name="Buyer Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Supplier user
        self.supplier_org = Organization.objects.create(name="Supplier Org", country="IR")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Broker user
        self.broker_org = Organization.objects.create(name="Broker Org", country="TR")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Django staff-only and superuser-only without Product SystemRole
        self.staff_only = User.objects.create_user(email="staff@platform.com", password="password", is_staff=True)
        self.superuser_only = User.objects.create_superuser(
            email="superuser@platform.com", password="password"
        )

        # Off-platform external counterparty
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Caspian Petroleum Ltd",
            contact_name="Aleksei Petrov",
            geography="Baku, Azerbaijan",
        )

        # Commodity
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_60_70",
            name_en="Bitumen 60/70",
            name_fa="قیر 60/70",
        )

        # Seed opportunity
        self.opportunity = Opportunity.objects.create(
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("380.00"),
            currency="USD",
            created_by=self.operator,
        )

    # -------------------------------------------------------------------------
    # Authorization Matrix
    # -------------------------------------------------------------------------

    def test_operator_allowed_list_create_detail_update(self):
        """Operator can list, create, view, and update opportunities."""
        self.client.force_authenticate(user=self.operator)

        # List
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Create
        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Demand",
                "organization_id": str(self.buyer_org.id),
                "quantity": "200.000",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Detail
        res = self.client.get(f"/api/opportunities/opportunities/{self.opportunity.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Update
        res = self.client.patch(
            f"/api/opportunities/opportunities/{self.opportunity.id}/",
            {"notes": "Updated operational note"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["notes"], "Updated operational note")

    def test_admin_allowed(self):
        """Product Admin can list, create, and view opportunities."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_buyer_denied(self):
        """Buyer organization user is denied access (HTTP 403)."""
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post("/api/opportunities/opportunities/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_denied(self):
        """Supplier organization user is denied access (HTTP 403)."""
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_broker_denied(self):
        """Broker organization user is denied access (HTTP 403)."""
        self.client.force_authenticate(user=self.broker_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_staff_only_denied(self):
        """Django is_staff alone does not grant access (HTTP 403)."""
        self.client.force_authenticate(user=self.staff_only)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_superuser_only_denied(self):
        """Django is_superuser alone does not grant access (HTTP 403)."""
        self.client.force_authenticate(user=self.superuser_only)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_denied(self):
        """Unauthenticated user is denied (HTTP 401 or 403)."""
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


    # -------------------------------------------------------------------------
    # API Operations: Create & Projections
    # -------------------------------------------------------------------------

    def test_create_opportunity_with_internal_organization(self):
        """Capture opportunity with an internal Organization."""
        self.client.force_authenticate(user=self.operator)
        payload = {
            "direction": "Demand",
            "organization_id": str(self.buyer_org.id),
            "commodity_id": str(self.commodity.id),
            "quantity": "750.500",
            "unit": "MT",
            "indicative_price": "410.00",
            "currency": "USD",
            "payment_terms": "100% LC at sight",
            "geography": "Jebel Ali Port",
            "notes": "Urgent procurement lead",
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data

        self.assertEqual(data["direction"], "Demand")
        self.assertEqual(data["counterparty_type"], "organization")
        self.assertIsNotNone(data["organization"])
        self.assertEqual(data["organization"]["id"], str(self.buyer_org.id))
        self.assertEqual(data["organization"]["name"], "Buyer Org")
        self.assertEqual(data["organization"]["country"], "AE")
        self.assertIsNone(data["external_counterparty"])
        self.assertEqual(data["commodity"]["code"], "bitumen_60_70")
        self.assertEqual(data["status"], OpportunityStatus.CAPTURED)

    def test_create_opportunity_with_external_counterparty(self):
        """Capture opportunity with an off-platform ExternalCounterparty."""
        self.client.force_authenticate(user=self.operator)
        payload = {
            "direction": "Supply",
            "external_counterparty_id": str(self.external_cp.id),
            "quantity": "1200.000",
            "unit": "MT",
            "geography": "Baku, Azerbaijan",
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data

        self.assertEqual(data["direction"], "Supply")
        self.assertEqual(data["counterparty_type"], "external_counterparty")
        self.assertIsNone(data["organization"])
        self.assertIsNotNone(data["external_counterparty"])
        self.assertEqual(data["external_counterparty"]["id"], str(self.external_cp.id))
        self.assertEqual(data["external_counterparty"]["company_name"], "Caspian Petroleum Ltd")
        self.assertEqual(data["external_counterparty"]["contact_name"], "Aleksei Petrov")

    def test_create_opportunity_both_counterparties_rejected(self):
        """Providing both organization_id and external_counterparty_id returns HTTP 400."""
        self.client.force_authenticate(user=self.operator)
        payload = {
            "direction": "Supply",
            "organization_id": str(self.buyer_org.id),
            "external_counterparty_id": str(self.external_cp.id),
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("counterparty", str(res.data))

    def test_create_opportunity_neither_counterparty_rejected(self):
        """Providing neither organization_id nor external_counterparty_id returns HTTP 400."""
        self.client.force_authenticate(user=self.operator)
        payload = {
            "direction": "Supply",
            "quantity": "500.000",
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("counterparty", str(res.data))

    def test_create_opportunity_invalid_direction_rejected(self):
        """Providing invalid direction returns HTTP 400."""
        self.client.force_authenticate(user=self.operator)
        payload = {
            "direction": "Arbitrary",
            "organization_id": str(self.buyer_org.id),
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # Detail Projection & Safe Representation
    # -------------------------------------------------------------------------

    def test_detail_projection_safe(self):
        """Opportunity detail does not leak private organization internals or audit secrets."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.get(f"/api/opportunities/opportunities/{self.opportunity.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        # Checks that nested organization only exposes safe public projection
        self.assertIn("id", data["organization"])
        self.assertIn("name", data["organization"])
        self.assertIn("country", data["organization"])
        self.assertNotIn("registration_identifier", data["organization"])

    # -------------------------------------------------------------------------
    # Mass Assignment Protection
    # -------------------------------------------------------------------------

    def test_mass_assignment_protection_on_create(self):
        """Client cannot forge status, created_by, or id on create."""
        self.client.force_authenticate(user=self.operator)
        forged_id = str(uuid.uuid4())
        payload = {
            "id": forged_id,
            "direction": "Supply",
            "organization_id": str(self.supplier_org.id),
            "status": "Converted",  # Attempting to forge future status
            "created_by": str(self.admin.id),  # Attempting to forge creator
        }
        res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data

        self.assertNotEqual(data["id"], forged_id)
        self.assertEqual(data["status"], OpportunityStatus.CAPTURED)
        self.assertEqual(data["created_by"], self.operator.id)

    def test_mass_assignment_protection_on_update(self):
        """Client cannot forge status or created_by on update."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.patch(
            f"/api/opportunities/opportunities/{self.opportunity.id}/",
            {"status": "Qualified", "notes": "Updated note"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opportunity.notes, "Updated note")

    # -------------------------------------------------------------------------
    # Malformed UUID & Method Not Allowed (Delete)
    # -------------------------------------------------------------------------

    def test_malformed_uuid_returns_404(self):
        """Malformed UUID returns HTTP 404 cleanly."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.get("/api/opportunities/opportunities/not-a-valid-uuid/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_returns_405_method_not_allowed(self):
        """Deleting an Opportunity is not permitted (HTTP 405) to preserve auditability."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.delete(f"/api/opportunities/opportunities/{self.opportunity.id}/")
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
