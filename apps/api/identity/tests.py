from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import SystemRoleAssignment
from django.test import override_settings
from django.core.management import call_command
import io



User = get_user_model()


class AuthTests(APITestCase):
    def setUp(self):
        self.user_data = {
            "email": "test@example.com",
            "password": "password123",
        }
        self.user = User.objects.create_user(**self.user_data)
        self.login_url = reverse("login")
        self.logout_url = reverse("logout")
        self.me_url = reverse("me")
        self.csrf_url = reverse("csrf")

    def test_user_creation(self):
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get(email="test@example.com"), self.user)
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_unique_email(self):
        with self.assertRaises(Exception):
            User.objects.create_user(email="test@example.com", password="password")

    def test_password_hashing(self):
        self.assertNotEqual(self.user.password, "password123")
        self.assertTrue(self.user.check_password("password123"))

    def test_login_success(self):
        response = self.client.post(self.login_url, self.user_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user_data["email"])

    def test_login_invalid_password(self):
        response = self.client.post(self.login_url, {"email": self.user_data["email"], "password": "wrong"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_unknown_user(self):
        response = self.client.post(self.login_url, {"email": "notfound@example.com", "password": "password"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.login_url, self.user_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_authenticated(self):
        self.client.login(email=self.user_data["email"], password=self.user_data["password"])

        # Give the user some context to test
        from organizations.models import Organization, OrganizationMembership, OrganizationCapability
        from .models import SystemRoleAssignment
        SystemRoleAssignment.objects.create(user=self.user, role=SystemRoleAssignment.SystemRole.OPERATOR)
        org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(user=self.user, organization=org, role=OrganizationMembership.OrganizationRole.MANAGER)
        OrganizationCapability.objects.create(organization=org, capability=OrganizationCapability.CapabilityType.BUYER)

        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user_data["email"])
        self.assertEqual(response.data["system_roles"], ["operator"])
        self.assertEqual(len(response.data["organizations"]), 1)
        self.assertEqual(response.data["organizations"][0]["role"], "manager")
        self.assertEqual(response.data["organizations"][0]["capabilities"], ["buyer"])
        self.assertEqual(response.data["organizations"][0]["organization"]["name"], "Test Org")

    def test_me_unauthenticated(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_logout(self):
        self.client.login(email=self.user_data["email"], password=self.user_data["password"])
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # After logout, me endpoint should fail
        me_response = self.client.get(self.me_url)
        self.assertEqual(me_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_csrf_cookie(self):
        response = self.client.get(self.csrf_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("csrftoken", response.cookies)


class SystemRoleTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@example.com", password="password")
        self.user2 = User.objects.create_user(email="operator@example.com", password="password")

    def test_create_system_role(self):
        role = SystemRoleAssignment.objects.create(
            user=self.user,
            role=SystemRoleAssignment.SystemRole.ADMIN
        )
        self.assertEqual(role.user, self.user)
        self.assertEqual(role.role, "admin")

    def test_duplicate_system_role_rejection(self):
        SystemRoleAssignment.objects.create(
            user=self.user,
            role=SystemRoleAssignment.SystemRole.ADMIN
        )
        with self.assertRaises(IntegrityError):
            SystemRoleAssignment.objects.create(
                user=self.user,
                role=SystemRoleAssignment.SystemRole.ADMIN
            )

    def test_invalid_system_role_rejection(self):
        with self.assertRaises(IntegrityError):
            SystemRoleAssignment.objects.create(
                user=self.user,
                role="superuser"
            )

    def test_multiple_roles_for_user(self):
        SystemRoleAssignment.objects.create(
            user=self.user,
            role=SystemRoleAssignment.SystemRole.ADMIN
        )
        SystemRoleAssignment.objects.create(
            user=self.user,
            role=SystemRoleAssignment.SystemRole.OPERATOR
        )
        self.assertEqual(self.user.system_roles.count(), 2)

    def test_no_organization_required(self):
        # We did not create any organization or membership, but role was created.
        role = SystemRoleAssignment.objects.create(
            user=self.user,
            role=SystemRoleAssignment.SystemRole.OPERATOR
        )
        self.assertEqual(role.user, self.user)



class DemoPersonaSwitcherTests(APITestCase):
    def setUp(self):
        self.url = reverse("demo-switch")

    def test_switcher_disabled_by_default(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(self.url, {"persona": "buyer"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_switcher_enabled_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("buyer", response.data)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_switcher_enabled_post_invalid_persona(self):
        response = self.client.post(self.url, {"persona": "invalid"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_switcher_enabled_valid_but_not_seeded(self):
        response = self.client.post(self.url, {"persona": "buyer"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_switcher_enabled_success(self):
        user = User.objects.create(email="buyer@demo.local", is_active=True)
        user.set_password("demo1234")
        user.save()

        response = self.client.post(self.url, {"persona": "buyer"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "buyer@demo.local")

        response = self.client.get(reverse("me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "buyer@demo.local")

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_switcher_csrf_enforced(self):
        user = User.objects.create(email="buyer@demo.local", is_active=True)
        user.set_password("demo1234")
        user.save()

        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(self.url, {"persona": "buyer"})
        self.assertEqual(response.status_code, 403)

class SeedDemoPersonasTests(APITestCase):
    def test_seed_idempotency(self):
        out = io.StringIO()
        call_command("seed_demo_personas", stdout=out)
        self.assertIn("Successfully seeded demo personas.", out.getvalue())
        self.assertEqual(User.objects.filter(email="buyer@demo.local").count(), 1)

        out = io.StringIO()
        call_command("seed_demo_personas", stdout=out)
        self.assertIn("Successfully seeded demo personas.", out.getvalue())
        self.assertEqual(User.objects.filter(email="buyer@demo.local").count(), 1)
