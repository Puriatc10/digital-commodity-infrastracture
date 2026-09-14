from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from identity.models import SystemRoleAssignment, User
from opportunities.models import ExternalCounterparty
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)


class ExternalCounterpartyAuthorizationTests(TestCase):
    """
    Authorization policy tests for Market Discovery / ExternalCounterparty.

    Matrix:
    - Operator: Allowed (Create, Read, Update, List)
    - Admin: Allowed (Create, Read, Update, List)
    - Buyer Org User: Denied (403)
    - Supplier Org User: Denied (403)
    - Broker Org User: Denied (403)
    - Django Staff-only (no system role): Denied (403)
    - Django Superuser-only (no system role): Denied (403)
    - Anonymous: Denied (401)
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
        self.buyer_org = Organization.objects.create(name="Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Supplier user
        self.supplier_org = Organization.objects.create(name="Supplier Org")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Broker user
        self.broker_org = Organization.objects.create(name="Broker Org")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        # Django staff-only (no SystemRoleAssignment)
        self.staff_only_user = User.objects.create_user(
            email="staff@internal.com", password="password", is_staff=True
        )

        # Django superuser-only (no SystemRoleAssignment)
        self.superuser_only_user = User.objects.create_superuser(
            email="superuser@internal.com", password="password"
        )

        # Sample counterparty
        self.counterparty = ExternalCounterparty.objects.create(
            company_name="Target Petroleum Corp",
            contact_name="Bob Miller",
            email="bob@targetpetro.com",
            geography="Rotterdam",
        )

        self.list_url = "/api/opportunities/external-counterparties/"
        self.detail_url = f"/api/opportunities/external-counterparties/{self.counterparty.id}/"

    def test_anonymous_user_denied(self):
        """Anonymous requests receive 401 Unauthorized or 403 Forbidden under SessionAuthentication."""
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        response = self.client.post(self.list_url, {"company_name": "New Corp"}, format="json")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        response = self.client.get(self.detail_url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        response = self.client.patch(self.detail_url, {"notes": "Updated"}, format="json")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_operator_allowed(self):
        """Operator can list, create, retrieve, and update external counterparties."""
        self.client.force_authenticate(user=self.operator)

        # List
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Create
        res = self.client.post(
            self.list_url,
            {"company_name": "Operator Added Corp", "phone": "+12345678"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Detail
        res = self.client.get(self.detail_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Update
        res = self.client.patch(self.detail_url, {"notes": "Operator note"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_product_admin_allowed(self):
        """Product Admin can list, create, retrieve, and update external counterparties."""
        self.client.force_authenticate(user=self.admin)

        # List
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Create
        res = self.client.post(
            self.list_url,
            {"company_name": "Admin Added Corp"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Detail
        res = self.client.get(self.detail_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Update
        res = self.client.patch(self.detail_url, {"notes": "Admin note"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_buyer_denied(self):
        """Buyer organization user is denied access (403 Forbidden)."""
        self.client.force_authenticate(user=self.buyer_user)

        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.list_url, {"company_name": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(self.detail_url, {"notes": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_supplier_denied(self):
        """Supplier organization user is denied access (403 Forbidden)."""
        self.client.force_authenticate(user=self.supplier_user)

        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.list_url, {"company_name": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(self.detail_url, {"notes": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_broker_denied(self):
        """Broker organization user is denied access (403 Forbidden)."""
        self.client.force_authenticate(user=self.broker_user)

        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.list_url, {"company_name": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(self.detail_url, {"notes": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_staff_only_without_system_role_denied(self):
        """Django is_staff=True alone does NOT grant Operator/Admin privileges."""
        self.client.force_authenticate(user=self.staff_only_user)

        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.list_url, {"company_name": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_only_without_system_role_denied(self):
        """Django is_superuser=True alone does NOT grant Operator/Admin privileges."""
        self.client.force_authenticate(user=self.superuser_only_user)

        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.list_url, {"company_name": "Forbidden"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_403_FORBIDDEN)
