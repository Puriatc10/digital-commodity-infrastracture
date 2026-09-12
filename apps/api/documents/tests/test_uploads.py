from io import BytesIO
from unittest import mock
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from documents.models import VerificationDocument, DocumentType
from organizations.models import Organization, OrganizationMembership
from organizations.verification.models import OrganizationVerification, VerificationStatus
from identity.models import User, SystemRoleAssignment

class MockMinioResponse:
    def read(self):
        return b"fake-pdf-content"
    def close(self):
        pass
    def release_conn(self):
        pass

class DocumentUploadTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@test.com", password="password")
        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.OrganizationRole.OWNER
        )

        self.other_user = User.objects.create_user(email="other@test.com", password="password")
        self.other_org = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(
            user=self.other_user,
            organization=self.other_org,
            role=OrganizationMembership.OrganizationRole.OWNER
        )

        self.verification = OrganizationVerification.objects.create(
            organization=self.org,
            status=VerificationStatus.UNVERIFIED
        )

        self.url = reverse("document-upload")

    def test_upload_success(self):
        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VerificationDocument.objects.count(), 1)
        doc = VerificationDocument.objects.first()
        self.assertEqual(doc.organization, self.org)
        self.assertEqual(doc.type, DocumentType.COMPANY_REGISTRATION)

        self.assertTrue(doc.object_key.startswith(str(self.org.id)))

    def test_upload_unauthorized_foreign_org(self):
        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.other_org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_upload_invalid_type(self):
        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.txt"
        file_obj.content_type = "text/plain" # We simulate it here, DRF might infer

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_upload_size_limit(self):
        self.client.force_login(self.user)

        file_obj = BytesIO(b"a" * (10 * 1024 * 1024 + 1)) # 10MB + 1 byte
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10 MB limit", response.data["detail"])
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_upload_replaces_and_invalidates_trust(self):
        # Initial doc
        VerificationDocument.objects.create(
            organization=self.org,
            type=DocumentType.TAX_ID,
            file_name="old.pdf",
            object_key="fake-old",
            mime_type="application/pdf",
            size_bytes=100,
            verification_status="accepted"
        )

        self.verification.status = VerificationStatus.VERIFIED
        self.verification.save()

        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new.pdf"

        data = {
            "type": DocumentType.TAX_ID,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VerificationDocument.objects.count(), 2)

        old_doc = VerificationDocument.objects.get(file_name="old.pdf")
        new_doc = VerificationDocument.objects.get(file_name="new.pdf")
        self.assertEqual(old_doc.verification_status, "replaced")
        self.assertEqual(new_doc.verification_status, "pending")

        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.DOCUMENTS_SUBMITTED)
        self.assertEqual(self.verification.decisions.count(), 1)

    def test_upload_storage_failure(self):
        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document', side_effect=Exception("Storage error")):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(VerificationDocument.objects.count(), 0)

    def test_upload_m6_basic_verified_invalidation(self):
        self.verification.status = VerificationStatus.BASIC_VERIFIED
        self.verification.save()
        self.client.force_login(self.user)

        # 1. Trade License First Upload -> No downgrade
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_trade_license.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.TRADE_LICENSE, "organization": str(self.org.id), "file": file_obj}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.BASIC_VERIFIED)

        # 2. Trade License Replacement -> No downgrade (Not required for Basic)
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_trade_license_2.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.TRADE_LICENSE, "organization": str(self.org.id), "file": file_obj}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.BASIC_VERIFIED)

        # 3. Bank Details Replacement -> No downgrade
        VerificationDocument.objects.create(organization=self.org, type=DocumentType.BANK_DETAILS, file_name="old_bd.pdf", object_key="bd1", mime_type="application/pdf", size_bytes=100, is_current=True, verification_status="accepted")
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_bank.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.BANK_DETAILS, "organization": str(self.org.id), "file": file_obj}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.BASIC_VERIFIED)

        # 4. Registration Replacement -> Downgrade
        VerificationDocument.objects.create(organization=self.org, type=DocumentType.COMPANY_REGISTRATION, file_name="old_reg.pdf", object_key="fake-reg-old", mime_type="application/pdf", size_bytes=100, is_current=True, verification_status="accepted")
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_reg.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.COMPANY_REGISTRATION, "organization": str(self.org.id), "file": file_obj}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.DOCUMENTS_SUBMITTED)

    def test_upload_m6_verified_invalidation(self):
        self.verification.status = VerificationStatus.VERIFIED
        self.verification.save()
        self.client.force_login(self.user)

        # 1. Certifications Replacement -> No downgrade
        VerificationDocument.objects.create(organization=self.org, type=DocumentType.CERTIFICATIONS, file_name="old_cert.pdf", object_key="cert1", mime_type="application/pdf", size_bytes=100, is_current=True, verification_status="accepted")
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_cert.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.CERTIFICATIONS, "organization": str(self.org.id), "file": file_obj}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.VERIFIED)

        # 2. Trade License Replacement -> Downgrade
        VerificationDocument.objects.create(organization=self.org, type=DocumentType.TRADE_LICENSE, file_name="old_tl.pdf", object_key="fake-tl-old", mime_type="application/pdf", size_bytes=100, is_current=True, verification_status="accepted")
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_tl.pdf"
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, {"type": DocumentType.TRADE_LICENSE, "organization": str(self.org.id), "file": file_obj}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.DOCUMENTS_SUBMITTED)

    def test_immutable_history(self):
        # M4: Replacing evidence leaves old review intact.
        doc1 = VerificationDocument.objects.create(
            organization=self.org,
            type=DocumentType.CERTIFICATIONS,
            file_name="old.pdf",
            object_key="fake-old-cert",
            mime_type="application/pdf",
            size_bytes=100,
            is_current=True,
            verification_status="accepted"
        )

        from organizations.verification.models import VerificationChecklistReview
        # create legacy review history
        VerificationChecklistReview.objects.create(
            verification=self.verification,
            document=doc1,
            reviewer=self.operator,
            outcome="accepted"
        )

        self.client.force_login(self.user)
        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new_cert.pdf"
        data = {
            "type": DocumentType.CERTIFICATIONS,
            "organization": str(self.org.id),
            "file": file_obj
        }
        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # doc1 is no longer current, but its review history remains
        doc1.refresh_from_db()
        self.assertFalse(doc1.is_current)

        # Verify the review hasn't been touched or removed
        reviews = VerificationChecklistReview.objects.filter(document=doc1)
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews[0].outcome, "accepted")

    def test_upload_certifications_no_invalidation(self):
        VerificationDocument.objects.create(
            organization=self.org,
            type=DocumentType.CERTIFICATIONS,
            file_name="old.pdf",
            object_key="fake-old",
            mime_type="application/pdf",
            size_bytes=100,
            is_current=True,
            verification_status="accepted"
        )

        self.verification.status = VerificationStatus.VERIFIED
        self.verification.save()

        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "new.pdf"

        data = {
            "type": DocumentType.CERTIFICATIONS,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VerificationDocument.objects.count(), 2)

        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.VERIFIED)

    def test_upload_db_failure_preserves_trust(self):
        self.verification.status = VerificationStatus.VERIFIED
        self.verification.save()

        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document'):
            with mock.patch('documents.models.VerificationDocument.objects.create', side_effect=Exception("DB Error")):
                response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.VERIFIED)

    def test_upload_storage_failure_preserves_trust(self):
        self.verification.status = VerificationStatus.VERIFIED
        self.verification.save()

        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        with mock.patch('documents.api.views.upload_document', side_effect=Exception("Storage Error")):
            response = self.client.post(self.url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        self.verification.refresh_from_db()
        self.assertEqual(self.verification.status, VerificationStatus.VERIFIED)

    def test_inactive_organization_rejects_upload(self):
        self.org.is_active = False
        self.org.save()

        self.client.force_login(self.user)

        file_obj = BytesIO(b"%PDF-fake-pdf-content")
        file_obj.name = "test.pdf"

        data = {
            "type": DocumentType.COMPANY_REGISTRATION,
            "organization": str(self.org.id),
            "file": file_obj
        }

        response = self.client.post(self.url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
