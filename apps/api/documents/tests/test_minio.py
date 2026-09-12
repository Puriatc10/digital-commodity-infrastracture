from io import BytesIO
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from documents.models import VerificationDocument, DocumentType
from organizations.models import Organization, OrganizationMembership
from identity.models import User
from documents.storage import get_minio_client
from django.conf import settings

class MinioIntegrationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@test.com", password="password")
        self.org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.OrganizationRole.OWNER
        )
        self.url = reverse("document-upload")

        # Clean up minio bucket before/after
        self.client_minio = get_minio_client()
        self.bucket = settings.MINIO_BUCKET_NAME
        self._clean_bucket()

    def tearDown(self):
        self._clean_bucket()

    def _clean_bucket(self):
        if self.client_minio.bucket_exists(self.bucket):
            objects = self.client_minio.list_objects(self.bucket, recursive=True)
            for obj in objects:
                self.client_minio.remove_object(self.bucket, obj.object_name)

    def test_real_minio_upload_and_download(self):
        self.client.force_login(self.user)

        content = b"%PDF-fake-pdf-content-for-real-minio"
        file_obj = BytesIO(content)
        file_obj.name = "real.pdf"
        file_obj.content_type = "application/pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        response = self.client.post(self.url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        doc = VerificationDocument.objects.first()
        self.assertIsNotNone(doc)

        # Verify it exists in MinIO
        response_minio = self.client_minio.get_object(self.bucket, doc.object_key)
        self.assertEqual(response_minio.read(), content)
        response_minio.close()
        response_minio.release_conn()

        # Test download API
        download_url = reverse("document-download", kwargs={"pk": doc.id})
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content)
        self.assertEqual(response["Content-Type"], "application/pdf")
