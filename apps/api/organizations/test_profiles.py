from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from rest_framework import status
from .models import Organization, OrganizationCapability, OrganizationCommodity
from commodities.models import CommodityDefinition
from organizations.verification.models import OrganizationVerification, VerificationStatus

User = get_user_model()

class ProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="test@example.com", password="password")

        self.org1 = Organization.objects.create(name="Alpha Org", website="https://alpha.local", country="IR", registration_identifier="12345", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org", country="AE", is_active=True)
        self.org_inactive = Organization.objects.create(name="Gamma Org", country="TR", is_active=False)

        OrganizationCapability.objects.create(organization=self.org1, capability=OrganizationCapability.CapabilityType.BUYER)
        OrganizationCapability.objects.create(organization=self.org1, capability=OrganizationCapability.CapabilityType.SUPPLIER)

        OrganizationVerification.objects.create(organization=self.org1, status=VerificationStatus.VERIFIED)

        self.commodity = CommodityDefinition.objects.create(name_en="Bitumen", code="bitumen")
        OrganizationCommodity.objects.create(organization=self.org1, commodity=self.commodity)

    def test_anonymous_denial(self):
        response = self.client.get(f'/api/organizations/profiles/{self.org1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_visibility(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/organizations/profiles/{self.org1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Alpha Org")
        self.assertEqual(response.data['website'], "https://alpha.local")
        self.assertEqual(response.data['country'], "IR")
        self.assertEqual(response.data['verification_status'], "verified")
        self.assertCountEqual(response.data['capabilities'], ["buyer", "supplier"])
        self.assertCountEqual(response.data['commodities'], ["bitumen"])
        self.assertEqual(response.data['activity_summary'], {})

    def test_inactive_exclusion(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/organizations/profiles/{self.org_inactive.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_safe_projection(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/organizations/profiles/{self.org1.id}/')
        item = response.data
        self.assertIn("id", item)
        self.assertIn("name", item)
        self.assertIn("country", item)
        self.assertIn("website", item)
        self.assertIn("capabilities", item)
        self.assertIn("commodities", item)
        self.assertIn("verification_status", item)
        self.assertIn("activity_summary", item)
        self.assertNotIn("registration_identifier", item)
        self.assertNotIn("created_at", item)
        self.assertNotIn("updated_at", item)
