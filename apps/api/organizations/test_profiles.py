from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from rest_framework import status
from django.urls import reverse
from .models import Organization, OrganizationCapability, OrganizationMembership, OrganizationCommodity
from commodities.models import CommodityDefinition
from organizations.verification.models import OrganizationVerification, VerificationStatus

User = get_user_model()

class OrganizationProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner_user = User.objects.create_user(email="owner@example.com", password="password")
        self.manager_user = User.objects.create_user(email="manager@example.com", password="password")
        self.member_user = User.objects.create_user(email="member@example.com", password="password")
        self.other_user = User.objects.create_user(email="other@example.com", password="password")

        self.org = Organization.objects.create(name="Alpha Org", country="IR", is_active=True, registration_identifier="123", website="https://example.com")
        self.inactive_org = Organization.objects.create(name="Inactive Org", country="IR", is_active=False)

        OrganizationMembership.objects.create(user=self.owner_user, organization=self.org, role=OrganizationMembership.OrganizationRole.OWNER)
        OrganizationMembership.objects.create(user=self.manager_user, organization=self.org, role=OrganizationMembership.OrganizationRole.MANAGER)
        OrganizationMembership.objects.create(user=self.member_user, organization=self.org, role=OrganizationMembership.OrganizationRole.MEMBER)

        OrganizationCapability.objects.create(organization=self.org, capability=OrganizationCapability.CapabilityType.BUYER)
        OrganizationCapability.objects.create(organization=self.org, capability=OrganizationCapability.CapabilityType.SUPPLIER)

        OrganizationVerification.objects.create(organization=self.org, status=VerificationStatus.BASIC_VERIFIED)

        self.commodity = CommodityDefinition.objects.create(name_en="Bitumen", code="bitumen")
        OrganizationCommodity.objects.create(organization=self.org, commodity=self.commodity)

        self.url = reverse('organization-detail', kwargs={'pk': self.org.id})
        self.inactive_url = reverse('organization-detail', kwargs={'pk': self.inactive_org.id})

    def test_profile_safe_projection(self):
        self.client.force_authenticate(user=self.member_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data["name"], "Alpha Org")
        self.assertEqual(data["country"], "IR")
        self.assertEqual(data["registration_identifier"], "123")
        self.assertEqual(data["website"], "https://example.com")
        self.assertCountEqual(data["capabilities"], ["buyer", "supplier"])
        self.assertCountEqual(data["commodities"], ["bitumen"])
        self.assertEqual(data["verification_status"], "basic_verified")

        self.assertNotIn("documents", data)
        self.assertNotIn("bank_details", data)
        self.assertNotIn("internal_notes", data)
        self.assertNotIn("decisions", data)

    def test_profile_forbidden_mutations(self):
        self.client.force_authenticate(user=self.owner_user)

        patch_data = {
            "name": "Updated Org",
            "capabilities": ["broker"],
            "commodities": ["base-oil"],
            "verification_status": "verified",
            "is_active": False,
            "roles": ["admin"],
            "memberships": [{"user": "fake", "role": "fake"}]
        }

        response = self.client.patch(self.url, patch_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Updated Org")
        self.assertTrue(self.org.is_active)

        response = self.client.get(self.url)
        data = response.data
        self.assertCountEqual(data["capabilities"], ["buyer", "supplier"])
        self.assertCountEqual(data["commodities"], ["bitumen"])
        self.assertEqual(data["verification_status"], "basic_verified")

    def test_inactive_organization_unreachable(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.inactive_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        OrganizationMembership.objects.create(user=self.member_user, organization=self.inactive_org, role=OrganizationMembership.OrganizationRole.MEMBER)
        self.client.force_authenticate(user=self.member_user)
        response = self.client.get(self.inactive_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
