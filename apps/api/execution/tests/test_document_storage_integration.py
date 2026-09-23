from io import BytesIO
import uuid

from django.conf import settings
from django.urls import reverse
from rest_framework import status

from documents.storage import get_minio_client
from execution.enums import ExecutionDocumentCategory
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal
from execution.tests.base import BaseExecutionTestCase


class ExecutionDocumentStorageIntegrationTests(BaseExecutionTestCase):
    """
    Real MinIO object storage integration tests (T1007).

    Invariants:
    - Uses real configured MinIO instance.
    - Verifies upload, physical storage existence, authorized retrieval, and metadata.
    - Strict isolated cleanup: cleans up ONLY test-owned objects; never wipes shared storage.
    """

    def setUp(self):
        super().setUp()
        self.client_minio = get_minio_client()
        self.bucket = settings.MINIO_BUCKET_NAME
        self.created_keys = set()

        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        self.upload_url = reverse("execution-document-upload", kwargs={"execution_id": self.execution.id})

    def tearDown(self):
        # Isolated cleanup: remove ONLY objects created during this test
        for key in list(self.created_keys):
            try:
                self.client_minio.remove_object(self.bucket, key)
            except Exception:
                pass
        super().tearDown()

    def test_real_minio_upload_existence_and_download(self):
        """Verify real upload to MinIO, physical object existence, and authorized streaming download."""
        self.client.force_login(self.buyer_user)

        pdf_content = b"%PDF-1.4 real-minio-integration-test-payload-" + uuid.uuid4().bytes
        file_obj = BytesIO(pdf_content)
        file_obj.name = "real_commercial_contract.pdf"
        file_obj.content_type = "application/pdf"

        resp = self.client.post(
            self.upload_url,
            {
                "file": file_obj,
                "category": ExecutionDocumentCategory.CONTRACT,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        doc_id = resp.data["id"]
        doc = ExecutionDocument.objects.get(id=doc_id)
        self.created_keys.add(doc.object_key)

        # 1. Verify metadata in DB and response
        self.assertEqual(doc.file_name, "real_commercial_contract.pdf")
        self.assertEqual(doc.content_type, "application/pdf")
        self.assertEqual(doc.size_bytes, len(pdf_content))
        self.assertEqual(doc.category, ExecutionDocumentCategory.CONTRACT)

        # 2. Verify physical object existence in MinIO
        minio_response = self.client_minio.get_object(self.bucket, doc.object_key)
        try:
            stored_bytes = minio_response.read()
            self.assertEqual(stored_bytes, pdf_content)
        finally:
            minio_response.close()
            minio_response.release_conn()

        # 3. Verify authorized API download endpoint
        download_url = reverse(
            "execution-document-download",
            kwargs={"execution_id": self.execution.id, "document_id": doc.id},
        )
        dl_resp = self.client.get(download_url)
        self.assertEqual(dl_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(dl_resp.content, pdf_content)
        self.assertEqual(dl_resp["Content-Type"], "application/pdf")
        self.assertIn("real_commercial_contract.pdf", dl_resp["Content-Disposition"])

    def test_real_minio_deal_nested_upload(self):
        """Verify Deal-nested upload endpoint works with real MinIO."""
        self.client.force_login(self.supplier_user)

        png_content = b"\x89PNG\r\n\x1a\nfake-png-payload-bytes"
        file_obj = BytesIO(png_content)
        file_obj.name = "loading_weighbridge.png"
        file_obj.content_type = "image/png"

        deal_upload_url = reverse("deals:deal-execution-document-upload", kwargs={"deal_id": self.deal.id})
        resp = self.client.post(
            deal_upload_url,
            {
                "file": file_obj,
                "category": ExecutionDocumentCategory.LOADING_DOCUMENT,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        doc = ExecutionDocument.objects.get(id=resp.data["id"])
        self.created_keys.add(doc.object_key)

        minio_response = self.client_minio.get_object(self.bucket, doc.object_key)
        try:
            self.assertEqual(minio_response.read(), png_content)
        finally:
            minio_response.close()
            minio_response.release_conn()
