from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from rest_framework import status
from .models import Organization, OrganizationCapability, OrganizationMembership, OrganizationCommodity
from commodities.models import CommodityDefinition
from organizations.verification.models import OrganizationVerification, VerificationStatus

User = get_user_model()

class DirectoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="test@example.com", password="password")
        self.user2 = User.objects.create_user(email="test2@example.com", password="password")

        self.org1 = Organization.objects.create(name="Alpha Org", country="IR", is_active=True)
        self.org2 = Organization.objects.create(name="Beta Org", country="AE", is_active=True)
        self.org_inactive = Organization.objects.create(name="Gamma Org", country="TR", is_active=False)

        OrganizationMembership.objects.create(user=self.user, organization=self.org1, role=OrganizationMembership.OrganizationRole.MEMBER)

        OrganizationCapability.objects.create(organization=self.org1, capability=OrganizationCapability.CapabilityType.BUYER)
        OrganizationCapability.objects.create(organization=self.org1, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCapability.objects.create(organization=self.org2, capability=OrganizationCapability.CapabilityType.BROKER)

        OrganizationVerification.objects.create(organization=self.org1, status=VerificationStatus.VERIFIED)
        OrganizationVerification.objects.create(organization=self.org2, status=VerificationStatus.UNVERIFIED)

        self.commodity = CommodityDefinition.objects.create(name_en="Bitumen", code="bitumen")
        self.commodity2 = CommodityDefinition.objects.create(name_en="Base Oil", code="base-oil")

        OrganizationCommodity.objects.create(organization=self.org1, commodity=self.commodity)
        OrganizationCommodity.objects.create(organization=self.org1, commodity=self.commodity2)
        OrganizationCommodity.objects.create(organization=self.org2, commodity=self.commodity)

    def test_anonymous_denial(self):
        response = self.client.get('/api/organizations/directory/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_visibility(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['name'], "Alpha Org")
        self.assertEqual(response.data[1]['name'], "Beta Org")

    def test_inactive_exclusion(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/')
        names = [item['name'] for item in response.data]
        self.assertNotIn("Gamma Org", names)

    def test_safe_projection(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/')
        item = response.data[0]
        self.assertIn("id", item)
        self.assertIn("name", item)
        self.assertIn("country", item)
        self.assertIn("capabilities", item)
        self.assertIn("commodities", item)
        self.assertIn("verification_status", item)
        self.assertIsInstance(item["capabilities"], list)
        self.assertIsInstance(item["commodities"], list)
        self.assertNotIn("registration_identifier", item)
        self.assertNotIn("website", item)

    def test_search_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?search=Alpha')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Alpha Org")

    def test_capability_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?capability=buyer')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Alpha Org")

    def test_country_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?country=AE')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Beta Org")

    def test_commodity_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?commodity=base-oil')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Alpha Org")

    def test_verification_filter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?verification=unverified')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Beta Org")

    def test_verification_filter_absent_row(self):
        # Organization without an OrganizationVerification row must be returned when filtering for 'unverified'
        org_no_row = Organization.objects.create(name="Delta Org", country="IR", is_active=True)
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?verification=unverified')
        names = [item['name'] for item in response.data]
        self.assertIn("Beta Org", names)
        self.assertIn("Delta Org", names)
        # Check projection reports 'unverified' status
        delta_item = next(item for item in response.data if item['name'] == "Delta Org")
        self.assertEqual(delta_item['id'], str(org_no_row.id))
        self.assertEqual(delta_item['verification_status'], "unverified")

    def test_directory_query_count_constant(self):
        self.client.force_authenticate(user=self.user)
        # Create 5 additional organizations with capabilities and commodities
        for i in range(5):
            org = Organization.objects.create(name=f"Extra Org {i}", country="IR", is_active=True)
            OrganizationCapability.objects.create(organization=org, capability=OrganizationCapability.CapabilityType.BUYER)
            OrganizationCommodity.objects.create(organization=org, commodity=self.commodity)

        # Total organizations is now 7 active organizations
        # Queries should be O(1): 1 main org query with select_related, 1 prefetch capabilities, 1 prefetch commodities (+auth/session)
        with self.assertNumQueries(4):
            response = self.client.get('/api/organizations/directory/')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.data), 7)

    def test_multi_capability_deduplication(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/organizations/directory/?capability=buyer&capability=supplier')
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], "Alpha Org")
