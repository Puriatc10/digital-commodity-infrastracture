from commodities.models import CommodityDefinition
from .models import OrganizationCommodity
from rest_framework.test import APIClient
from rest_framework import status
from identity.models import SystemRoleAssignment
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from identity.models import User, SystemRoleAssignment
from organizations.models import Organization, OrganizationMembership, OrganizationCapability

class OrganizationAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.org1 = Organization.objects.create(name="Org 1")
        self.org2 = Organization.objects.create(name="Org 2")
        self.inactive_org = Organization.objects.create(name="Inactive Org", is_active=False)

        # Base users
        self.user_viewer = User.objects.create_user(email="viewer@test.com", password="password")
        self.user_member = User.objects.create_user(email="member@test.com", password="password")
        self.user_manager = User.objects.create_user(email="manager@test.com", password="password")
        self.user_owner = User.objects.create_user(email="owner@test.com", password="password")
        self.user_operator = User.objects.create_user(email="operator@test.com", password="password")
        self.user_admin = User.objects.create_user(email="admin@test.com", password="password")
        self.user_no_role = User.objects.create_user(email="norole@test.com", password="password")
        self.user_inactive = User.objects.create_user(email="inactive@test.com", password="password", is_active=False)
        self.user_inactive_membership = User.objects.create_user(email="inactive_mem@test.com", password="password")

        # Memberships for Org 1
        OrganizationMembership.objects.create(
            user=self.user_viewer, organization=self.org1, role=OrganizationMembership.OrganizationRole.VIEWER
        )
        OrganizationMembership.objects.create(
            user=self.user_member, organization=self.org1, role=OrganizationMembership.OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            user=self.user_manager, organization=self.org1, role=OrganizationMembership.OrganizationRole.MANAGER
        )
        OrganizationMembership.objects.create(
            user=self.user_owner, organization=self.org1, role=OrganizationMembership.OrganizationRole.OWNER
        )
        OrganizationMembership.objects.create(
            user=self.user_inactive_membership, organization=self.org1,
            role=OrganizationMembership.OrganizationRole.OWNER, is_active=False
        )

        # System roles
        SystemRoleAssignment.objects.create(user=self.user_operator, role=SystemRoleAssignment.SystemRole.OPERATOR)
        SystemRoleAssignment.objects.create(user=self.user_admin, role=SystemRoleAssignment.SystemRole.ADMIN)

        # Capability (should not grant auth)
        self.user_capability_only = User.objects.create_user(email="cap@test.com", password="password")
        OrganizationCapability.objects.create(
            organization=self.org1, capability=OrganizationCapability.CapabilityType.BUYER
        )

        self.url_list = reverse('organization-list')
        self.url_org1 = reverse('organization-detail', kwargs={'pk': self.org1.id})
        self.url_org2 = reverse('organization-detail', kwargs={'pk': self.org2.id})

    def test_unauthenticated_access(self):
        response = self.client.get(self.url_list)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        response = self.client.get(self.url_org1)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        response = self.client.patch(self.url_org1, {"name": "Test"})
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_horizontal_access_isolation(self):
        self.client.force_authenticate(user=self.user_viewer)

        # User viewer is member of Org1, not Org2
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.org1.id))

        response = self.client.get(self.url_org2)
        # Using 404 convention for horizontal isolation (objects not in get_queryset)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_viewer_access(self):
        self.client.force_authenticate(user=self.user_viewer)
        response = self.client.get(self.url_org1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(self.url_org1, {"name": "New Name"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_access(self):
        self.client.force_authenticate(user=self.user_member)
        response = self.client.get(self.url_org1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(self.url_org1, {"name": "New Name"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_access(self):
        self.client.force_authenticate(user=self.user_manager)
        response = self.client.patch(self.url_org1, {"name": "New Name"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.org1.refresh_from_db()
        self.assertEqual(self.org1.name, "New Name")

    def test_owner_access(self):
        self.client.force_authenticate(user=self.user_owner)
        response = self.client.patch(self.url_org1, {"name": "New Name"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_operator_access(self):
        self.client.force_authenticate(user=self.user_operator)

        # Operators see all
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3) # Org1, Org2, InactiveOrg

        response = self.client.get(self.url_org2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Operators cannot update
        response = self.client.patch(self.url_org1, {"name": "Hacked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_access(self):
        self.client.force_authenticate(user=self.user_admin)

        response = self.client.get(self.url_list)
        self.assertEqual(len(response.data), 3)

        # Admins can update any org
        response = self.client.patch(self.url_org2, {"name": "Admin Update"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.org2.refresh_from_db()
        self.assertEqual(self.org2.name, "Admin Update")

    def test_inactive_user(self):
        self.client.force_authenticate(user=self.user_inactive)
        response = self.client.get(self.url_list)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        response = self.client.get(self.url_org1)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_inactive_membership(self):
        self.client.force_authenticate(user=self.user_inactive_membership)
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

        response = self.client.get(self.url_org1)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_capabilities_do_not_grant_permissions(self):
        # user_capability_only belongs to no org directly via membership, but org has capability
        self.client.force_authenticate(user=self.user_capability_only)
        response = self.client.get(self.url_list)
        self.assertEqual(len(response.data), 0)

        response = self.client.get(self.url_org1)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_writable_fields_restrictions(self):
        self.client.force_authenticate(user=self.user_owner)
        original_is_active = self.org1.is_active

        response = self.client.patch(self.url_org1, {
            "name": "New Name",
            "is_active": False,
            "id": "123e4567-e89b-12d3-a456-426614174000"
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.org1.refresh_from_db()
        self.assertEqual(self.org1.name, "New Name")
        # Ensure read_only fields are ignored
        self.assertEqual(self.org1.is_active, original_is_active)
        self.assertNotEqual(str(self.org1.id), "123e4567-e89b-12d3-a456-426614174000")


class OrganizationCommodityAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="password")
        self.org = Organization.objects.create(name="Test Org")
        self.commodity = CommodityDefinition.objects.create(name_en="Bitumen", code="bitumen")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url_add = f"/api/organizations/{self.org.id}/add_commodity/"
        self.url_remove = f"/api/organizations/{self.org.id}/remove_commodity/"

    def test_owner_manager_can_add(self):
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role=OrganizationMembership.OrganizationRole.MANAGER)
        response = self.client.post(self.url_add, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationCommodity.objects.filter(organization=self.org, commodity=self.commodity).exists())

    def test_member_viewer_cannot_add(self):
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role=OrganizationMembership.OrganizationRole.MEMBER)
        response = self.client.post(self.url_add, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OrganizationCommodity.objects.filter(organization=self.org, commodity=self.commodity).exists())

    def test_admin_can_add(self):
        SystemRoleAssignment.objects.create(user=self.user, role=SystemRoleAssignment.SystemRole.ADMIN)
        response = self.client.post(self.url_add, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_operator_cannot_add(self):
        SystemRoleAssignment.objects.create(user=self.user, role=SystemRoleAssignment.SystemRole.OPERATOR)
        response = self.client.post(self.url_add, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_without_role_cannot_add(self):
        superuser = User.objects.create_superuser(email="super@example.com", password="password")
        self.client.force_authenticate(user=superuser)
        response = self.client.post(self.url_add, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_remove(self):
        OrganizationCommodity.objects.create(organization=self.org, commodity=self.commodity)
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role=OrganizationMembership.OrganizationRole.OWNER)
        response = self.client.delete(self.url_remove, {"commodity_code": "bitumen"})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationCommodity.objects.filter(organization=self.org, commodity=self.commodity).exists())
