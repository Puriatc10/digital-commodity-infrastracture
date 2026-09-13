from unittest import mock
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from documents.models import VerificationDocument, DocumentType
from organizations.models import Organization, OrganizationMembership
from identity.models import User, SystemRoleAssignment

class DocumentAccessTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@test.com", password="password")
        self.member = User.objects.create_user(email="member@test.com", password="password")
        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.OrganizationRole.OWNER
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role=OrganizationMembership.OrganizationRole.MEMBER
        )

        self.doc = VerificationDocument.objects.create(
            organization=self.org,
            type=DocumentType.COMPANY_REGISTRATION,
            file_name="test.pdf",
            object_key=f"{self.org.id}/test.pdf",
            mime_type="application/pdf",
            size_bytes=100
        )

    def test_list_documents_owner(self):
        self.client.force_login(self.owner)
        url = reverse("document-list")
        response = self.client.get(url, {"organization": self.org.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_list_documents_member(self):
        self.client.force_login(self.member)
        url = reverse("document-list")
        response = self.client.get(url, {"organization": self.org.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_list_documents_operator(self):
        self.client.force_login(self.operator)
        url = reverse("document-list")
        response = self.client.get(url, {"organization": self.org.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    @mock.patch('documents.api.views.get_document_bytes', return_value=b"fake-bytes")
    def test_download_document_owner(self, mock_get):
        self.client.force_login(self.owner)
        url = reverse("document-download", kwargs={"pk": self.doc.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"fake-bytes")

    @mock.patch('documents.api.views.get_document_bytes', return_value=b"fake-bytes")
    def test_download_document_member(self, mock_get):
        self.client.force_login(self.member)
        url = reverse("document-download", kwargs={"pk": self.doc.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @mock.patch('documents.api.views.get_document_bytes', return_value=b"fake-bytes")
    def test_download_document_operator(self, mock_get):
        self.client.force_login(self.operator)
        url = reverse("document-download", kwargs={"pk": self.doc.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"fake-bytes")

    def test_download_nonexistent_file(self):
        self.client.force_login(self.owner)
        url = reverse("document-download", kwargs={"pk": self.doc.id})
        with mock.patch('documents.api.views.get_document_bytes', return_value=None):
            response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_documents_invalid_uuid(self):
        self.client.force_login(self.owner)
        url = reverse("document-list")
        response = self.client.get(url, {"organization": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
