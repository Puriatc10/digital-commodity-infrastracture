from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from django.urls import reverse
from organizations.models import Organization, OrganizationMembership
from documents.models import VerificationDocument, DocumentType
from identity.models import SystemRoleAssignment

User = get_user_model()

class VerificationChecklistAPITests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(email="admin@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.admin_user, role=SystemRoleAssignment.SystemRole.ADMIN)

        self.operator_user = User.objects.create_user(email="op@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator_user, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.superuser = User.objects.create_user(email="super@test.com", password="password", is_superuser=True)

        self.owner_user = User.objects.create_user(email="owner@test.com", password="password")
        self.member_user = User.objects.create_user(email="member@test.com", password="password")

        self.org = Organization.objects.create(name="Test Org", country="IR")
        OrganizationMembership.objects.create(user=self.owner_user, organization=self.org, role=OrganizationMembership.OrganizationRole.OWNER, is_active=True)
        OrganizationMembership.objects.create(user=self.member_user, organization=self.org, role=OrganizationMembership.OrganizationRole.MEMBER, is_active=True)

        # Setup verification
        from organizations.verification.services import VerificationService
        VerificationService.submit(self.org.id, self.admin_user)
        VerificationService.start_review(self.org.id, self.admin_user)

        self.doc = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.COMPANY_REGISTRATION,
            object_key="key1", size_bytes=100
        )
        self.url = reverse('verification:checklist-review', kwargs={'org_id': self.org.id})

    def test_operator_can_review(self):
        client = APIClient()
        client.force_authenticate(user=self.operator_user)
        response = client.post(self.url, {"document_id": self.doc.id, "outcome": "accepted"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_cannot_review(self):
        client = APIClient()
        client.force_authenticate(user=self.owner_user)
        response = client.post(self.url, {"document_id": self.doc.id, "outcome": "accepted"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_review(self):
        client = APIClient()
        client.force_authenticate(user=self.member_user)
        response = client.post(self.url, {"document_id": self.doc.id, "outcome": "accepted"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_without_role_cannot_review(self):
        client = APIClient()
        client.force_authenticate(user=self.superuser)
        response = client.post(self.url, {"document_id": self.doc.id, "outcome": "accepted"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
