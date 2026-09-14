import uuid
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


class ExternalCounterpartyAPITests(TestCase):
    """
    API endpoint tests for ExternalCounterparty.
    """

    def setUp(self):
        self.client = APIClient()
        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )
        self.client.force_authenticate(user=self.operator)

        self.list_url = "/api/opportunities/external-counterparties/"

    def test_create_external_counterparty_success(self):
        """Operator can create an external counterparty and receive projected response."""
        payload = {
            "company_name": "Middle East Bitumen Corp",
            "contact_name": "Farhad Karimi",
            "phone": "+989121112233",
            "email": "farhad@me-bitumen.ir",
            "geography": "Bandar Abbas, Iran",
            "notes": "Direct bitumen manufacturer contact.",
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.data
        self.assertTrue(uuid.UUID(data["id"]))
        self.assertEqual(data["company_name"], "Middle East Bitumen Corp")
        self.assertEqual(data["contact_name"], "Farhad Karimi")
        self.assertEqual(data["phone"], "+989121112233")
        self.assertEqual(data["email"], "farhad@me-bitumen.ir")
        self.assertEqual(data["geography"], "Bandar Abbas, Iran")
        self.assertEqual(data["notes"], "Direct bitumen manufacturer contact.")
        self.assertEqual(data["created_by"], self.operator.id)
        self.assertIsNotNone(data["created_at"])
        self.assertIsNotNone(data["updated_at"])

    def test_create_external_counterparty_creates_no_platform_identity(self):
        """API creation creates no fake User or Organization."""
        user_count = User.objects.count()
        org_count = Organization.objects.count()
        mem_count = OrganizationMembership.objects.count()
        cap_count = OrganizationCapability.objects.count()

        response = self.client.post(
            self.list_url,
            {"company_name": "Off-Platform Trader"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(User.objects.count(), user_count)
        self.assertEqual(Organization.objects.count(), org_count)
        self.assertEqual(OrganizationMembership.objects.count(), mem_count)
        self.assertEqual(OrganizationCapability.objects.count(), cap_count)

    def test_retrieve_detail_success(self):
        """Operator can retrieve counterparty details."""
        cp = ExternalCounterparty.objects.create(
            company_name="Caspian Petrochemicals",
            contact_name="Elena Petrova",
            email="elena@caspian.az",
            geography="Baku, Azerbaijan",
            created_by=self.operator,
        )

        detail_url = f"{self.list_url}{cp.id}/"
        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(cp.id))
        self.assertEqual(response.data["company_name"], "Caspian Petrochemicals")
        self.assertEqual(response.data["contact_name"], "Elena Petrova")

    def test_patch_partial_update_success(self):
        """Operator can partially update editable fields."""
        cp = ExternalCounterparty.objects.create(
            company_name="Original Name LLC",
            contact_name="Original Contact",
            phone="+11111111",
            created_by=self.operator,
        )

        detail_url = f"{self.list_url}{cp.id}/"
        response = self.client.patch(
            detail_url,
            {"contact_name": "Updated Contact", "notes": "Added notes"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cp.refresh_from_db()
        self.assertEqual(cp.company_name, "Original Name LLC")
        self.assertEqual(cp.contact_name, "Updated Contact")
        self.assertEqual(cp.notes, "Added notes")
        self.assertEqual(cp.phone, "+11111111")

    def test_put_full_update_success(self):
        """Operator can perform a full PUT update."""
        cp = ExternalCounterparty.objects.create(
            company_name="Old Name Corp",
            created_by=self.operator,
        )

        detail_url = f"{self.list_url}{cp.id}/"
        payload = {
            "company_name": "New Name Corp",
            "contact_name": "New Person",
            "phone": "+999999",
            "email": "new@corp.com",
            "geography": "Dubai",
            "notes": "Full update applied",
        }
        response = self.client.put(detail_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cp.refresh_from_db()
        self.assertEqual(cp.company_name, "New Name Corp")
        self.assertEqual(cp.contact_name, "New Person")
        self.assertEqual(cp.email, "new@corp.com")

    def test_delete_is_not_allowed(self):
        """
        Destructive deletion is intentionally NOT implemented/exposed.
        Returns 405 Method Not Allowed to preserve future Opportunity historical provenance.
        """
        cp = ExternalCounterparty.objects.create(
            company_name="Indelible Trading Co.",
            created_by=self.operator,
        )

        detail_url = f"{self.list_url}{cp.id}/"
        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(ExternalCounterparty.objects.filter(id=cp.id).exists())

    def test_list_and_search(self):
        """List supports search by query string across fields, explicit filters, and pagination."""
        ExternalCounterparty.objects.create(
            company_name="Al-Noor Bitumen Trading",
            contact_name="Tariq Mansoor",
            email="tariq@alnoor.om",
            geography="Muscat, Oman",
        )
        ExternalCounterparty.objects.create(
            company_name="Sahara Energy Resources",
            contact_name="Zayd Al-Hassan",
            email="zayd@sahara.eg",
            geography="Alexandria, Egypt",
        )
        ExternalCounterparty.objects.create(
            company_name="Anatolian Asphalt Ltd",
            contact_name="Emre Yilmaz",
            email="emre@anatolian.tr",
            geography="Izmir, Turkey",
        )

        # Search by company name
        res = self.client.get(self.list_url, {"search": "Al-Noor"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["company_name"], "Al-Noor Bitumen Trading")

        # Search by contact name
        res = self.client.get(self.list_url, {"search": "Yilmaz"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["company_name"], "Anatolian Asphalt Ltd")

        # Search by geography
        res = self.client.get(self.list_url, {"search": "Egypt"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["company_name"], "Sahara Energy Resources")

        # Explicit filter company_name
        res = self.client.get(self.list_url, {"company_name": "Sahara"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

        # Explicit filter geography
        res = self.client.get(self.list_url, {"geography": "Muscat"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_malformed_uuid_returns_404(self):
        """Malformed UUID in URL returns 404."""
        response = self.client.get(f"{self.list_url}not-a-valid-uuid/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_uuid_returns_404(self):
        """Non-existent UUID in URL returns 404."""
        random_id = uuid.uuid4()
        response = self.client.get(f"{self.list_url}{random_id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mass_assignment_protection(self):
        """
        Protected fields (id, created_by, created_at, updated_at) cannot be injected or modified.
        """
        spoofed_id = uuid.uuid4()
        fake_user = User.objects.create_user(email="fake@test.com", password="password")
        spoofed_time = "2020-01-01T00:00:00Z"

        payload = {
            "id": str(spoofed_id),
            "company_name": "Protected Corp",
            "created_by": fake_user.id,
            "created_at": spoofed_time,
            "updated_at": spoofed_time,
        }

        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        created_cp = ExternalCounterparty.objects.get(company_name="Protected Corp")
        self.assertNotEqual(created_cp.id, spoofed_id)
        self.assertEqual(created_cp.created_by, self.operator)
        self.assertNotEqual(str(created_cp.created_at)[:10], "2020-01-01")

        # Attempt to overwrite via PATCH
        detail_url = f"{self.list_url}{created_cp.id}/"
        patch_response = self.client.patch(
            detail_url,
            {
                "id": str(spoofed_id),
                "created_by": fake_user.id,
                "created_at": spoofed_time,
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        created_cp.refresh_from_db()
        self.assertNotEqual(created_cp.id, spoofed_id)
        self.assertEqual(created_cp.created_by, self.operator)
        self.assertNotEqual(str(created_cp.created_at)[:10], "2020-01-01")
