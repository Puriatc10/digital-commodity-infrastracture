from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status

from execution.enums import ExecutionDocumentCategory
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal
from execution.tests.base import BaseExecutionTestCase
from organizations.models import OrganizationMembership

User = get_user_model()


class ExecutionDocumentAuthorizationTests(BaseExecutionTestCase):
    """Exhaustive authorization tests for Execution Documents (Epic 10 Contract §77–§84, T1007)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        # Buyer viewer
        self.buyer_viewer = User.objects.create_user(
            email="buyer_viewer@test.com", password="password123"
        )
        OrganizationMembership.objects.create(
            user=self.buyer_viewer,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # Unrelated Organization & User
        from organizations.models import Organization
        self.unrelated_org = Organization.objects.create(name="Unrelated Org", country="IR", is_active=True)
        self.unrelated_user = User.objects.create_user(
            email="unrelated_doc@test.com", password="password123"
        )
        OrganizationMembership.objects.create(
            user=self.unrelated_user,
            organization=self.unrelated_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Create a document in execution for reading tests
        self.existing_doc = ExecutionDocument.objects.create(
            execution=self.execution,
            category=ExecutionDocumentCategory.CONTRACT,
            file_name="existing_contract.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            object_key=f"execution-documents/{self.execution.id}/seed-contract.pdf",
            uploaded_by=self.buyer_user,
        )

        self.upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution.id})
        self.list_url = reverse("execution-document-list", kwargs={"execution_id": self.execution.id})
        self.detail_url = reverse(
            "execution-document-detail",
            kwargs={"execution_id": self.execution.id, "document_id": self.existing_doc.id},
        )
        self.download_url = reverse(
            "execution-document-download",
            kwargs={"execution_id": self.execution.id, "document_id": self.existing_doc.id},
        )

    def _make_dummy_pdf(self, filename="test.pdf"):
        content = b"%PDF-1.4 dummy valid pdf content"
        f = BytesIO(content)
        f.name = filename
        f.content_type = "application/pdf"
        return f, content

    @patch("execution.services.document_service.upload_document")
    def test_buyer_permitted_categories(self, mock_upload):
        """Buyer non-viewer can upload CONTRACT, PAYMENT_PROOF, DELIVERY_PROOF, ACCEPTANCE_DOCUMENT, OTHER."""
        mock_upload.return_value = None
        self.client.force_login(self.buyer_user)

        buyer_categories = [
            ExecutionDocumentCategory.CONTRACT,
            ExecutionDocumentCategory.PAYMENT_PROOF,
            ExecutionDocumentCategory.DELIVERY_PROOF,
            ExecutionDocumentCategory.ACCEPTANCE_DOCUMENT,
            ExecutionDocumentCategory.OTHER,
        ]

        for cat in buyer_categories:
            f, _ = self._make_dummy_pdf(f"{cat.lower()}.pdf")
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": cat},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, f"Failed for buyer on category {cat}: {resp.data}")

    @patch("execution.services.document_service.upload_document")
    def test_buyer_denied_seller_exclusive_categories(self, mock_upload):
        """Buyer non-viewer cannot upload LOADING_DOCUMENT, INSPECTION_REPORT, TRANSPORT_DOCUMENT."""
        self.client.force_login(self.buyer_user)

        seller_categories = [
            ExecutionDocumentCategory.LOADING_DOCUMENT,
            ExecutionDocumentCategory.INSPECTION_REPORT,
            ExecutionDocumentCategory.TRANSPORT_DOCUMENT,
        ]

        for cat in seller_categories:
            f, _ = self._make_dummy_pdf(f"{cat.lower()}.pdf")
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": cat},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, f"Buyer should be forbidden for category {cat}")

    @patch("execution.services.document_service.upload_document")
    def test_seller_permitted_categories(self, mock_upload):
        """Seller non-viewer can upload CONTRACT, PAYMENT_PROOF, LOADING_DOCUMENT, INSPECTION_REPORT, TRANSPORT_DOCUMENT, OTHER."""
        mock_upload.return_value = None
        self.client.force_login(self.supplier_user)

        seller_categories = [
            ExecutionDocumentCategory.CONTRACT,
            ExecutionDocumentCategory.PAYMENT_PROOF,
            ExecutionDocumentCategory.LOADING_DOCUMENT,
            ExecutionDocumentCategory.INSPECTION_REPORT,
            ExecutionDocumentCategory.TRANSPORT_DOCUMENT,
            ExecutionDocumentCategory.OTHER,
        ]

        for cat in seller_categories:
            f, _ = self._make_dummy_pdf(f"{cat.lower()}.pdf")
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": cat},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, f"Failed for seller on category {cat}: {resp.data}")

    @patch("execution.services.document_service.upload_document")
    def test_seller_denied_buyer_exclusive_categories(self, mock_upload):
        """Seller non-viewer cannot upload DELIVERY_PROOF, ACCEPTANCE_DOCUMENT."""
        self.client.force_login(self.supplier_user)

        buyer_categories = [
            ExecutionDocumentCategory.DELIVERY_PROOF,
            ExecutionDocumentCategory.ACCEPTANCE_DOCUMENT,
        ]

        for cat in buyer_categories:
            f, _ = self._make_dummy_pdf(f"{cat.lower()}.pdf")
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": cat},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, f"Seller should be forbidden for category {cat}")

    @patch("execution.services.document_service.upload_document")
    def test_operator_can_upload_all_categories(self, mock_upload):
        """Operator can upload any document category."""
        mock_upload.return_value = None
        self.client.force_login(self.operator_user)

        for cat in ExecutionDocumentCategory.values:
            f, _ = self._make_dummy_pdf(f"op_{cat.lower()}.pdf")
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": cat},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, f"Failed for operator on category {cat}")

    def test_viewer_upload_denied_read_permitted(self):
        """Viewer role (buyer or seller) cannot upload documents, but can view and download."""
        for viewer in [self.buyer_viewer, self.supplier_viewer]:
            self.client.force_login(viewer)

            # Upload attempt fails with 403
            f, _ = self._make_dummy_pdf()
            resp = self.client.post(
                self.upload_url,
                {"file": f, "category": ExecutionDocumentCategory.OTHER},
                format="multipart",
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

            # List succeeds
            resp = self.client.get(self.list_url)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)

            # Detail succeeds
            resp = self.client.get(self.detail_url)
            self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_attributed_only_broker_denied(self):
        """Attributed-only broker is denied list, detail, download, and upload access."""
        self.client.force_login(self.broker_user)

        f, _ = self._make_dummy_pdf()
        # Upload
        resp = self.client.post(self.upload_url, {"file": f, "category": ExecutionDocumentCategory.OTHER}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # List
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Detail
        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Download
        resp = self.client.get(self.download_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_organization_denied(self):
        """Unrelated user from competitor organization is denied all document access."""
        self.client.force_login(self.unrelated_user)

        f, _ = self._make_dummy_pdf()
        resp = self.client.post(self.upload_url, {"file": f, "category": ExecutionDocumentCategory.OTHER}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.get(self.detail_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.get(self.download_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_denied(self):
        """Anonymous user is denied all document endpoints."""
        self.client.logout()

        f, _ = self._make_dummy_pdf()
        resp = self.client.post(self.upload_url, {"file": f, "category": ExecutionDocumentCategory.OTHER}, format="multipart")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        resp = self.client.get(self.list_url)
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        resp = self.client.get(self.detail_url)
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        resp = self.client.get(self.download_url)
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_staff_without_system_role_assignment_denied(self):
        """Django is_staff user lacking SystemRoleAssignment is denied execution access."""
        staff_user = User.objects.create_user(
            email="staff_no_role@test.com", password="password123", is_staff=True
        )
        self.client.force_login(staff_user)

        f, _ = self._make_dummy_pdf()
        resp = self.client.post(self.upload_url, {"file": f, "category": ExecutionDocumentCategory.OTHER}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.get(self.list_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @patch("execution.services.document_service.upload_document")
    def test_external_seller_flow(self, mock_upload):
        """
        External Seller Execution:
        - Deal has external seller (seller_organization_id is None).
        - No fake user account created for external counterparty.
        - Buyer can view documents and upload buyer documents.
        - Buyer cannot upload seller documents (LOADING_DOCUMENT).
        - Operator can upload seller documents on behalf of external seller.
        """
        mock_upload.return_value = None
        ext_deal = self.create_sample_deal(external_seller=True)
        self.assertIsNone(ext_deal.seller_organization_id)
        self.assertIsNotNone(ext_deal.seller_external_counterparty_id)

        ext_exec = create_or_get_execution_for_deal(deal_id=ext_deal.id, actor=self.operator_user)
        ext_upload_url = reverse("execution-document-upload", kwargs={"execution_id": ext_exec.id})
        ext_list_url = reverse("execution-document-list", kwargs={"execution_id": ext_exec.id})

        # Buyer can read documents
        self.client.force_login(self.buyer_user)
        resp = self.client.get(ext_list_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Buyer cannot upload seller loading document
        f, _ = self._make_dummy_pdf("buyer_loading.pdf")
        resp = self.client.post(ext_upload_url, {"file": f, "category": ExecutionDocumentCategory.LOADING_DOCUMENT}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Operator can upload seller loading document
        self.client.force_login(self.operator_user)
        f_op, _ = self._make_dummy_pdf("op_loading.pdf")
        resp = self.client.post(ext_upload_url, {"file": f_op, "category": ExecutionDocumentCategory.LOADING_DOCUMENT}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
