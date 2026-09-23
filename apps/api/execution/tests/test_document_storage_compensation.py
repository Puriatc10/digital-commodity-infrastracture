from io import BytesIO
from unittest.mock import patch

from django.conf import settings

from documents.storage import get_minio_client
from execution.enums import ExecutionDocumentCategory
from execution.models import ExecutionDocument
from execution.seed import seed_bitumen_workflow_v1
from execution.services import create_or_get_execution_for_deal, upload_execution_document
from execution.tests.base import BaseExecutionTestCase


class ExecutionDocumentStorageCompensationTests(BaseExecutionTestCase):
    """
    Tests for storage atomicity and practical compensation on database failure (T1007).
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

    def tearDown(self):
        for key in list(self.created_keys):
            try:
                self.client_minio.remove_object(self.bucket, key)
            except Exception:
                pass
        super().tearDown()

    def test_database_failure_triggers_minio_compensation_no_orphan(self):
        """
        When MinIO upload succeeds but PostgreSQL database transaction aborts/fails,
        practical compensation must remove the uploaded object from MinIO to prevent orphans.
        """
        pdf_content = b"%PDF-1.4 compensation-test-bytes"
        file_obj = BytesIO(pdf_content)
        file_obj.name = "orphan_check.pdf"
        file_obj.content_type = "application/pdf"

        # Simulate database failure during model creation
        with patch.object(
            ExecutionDocument.objects,
            "create",
            side_effect=RuntimeError("Simulated database failure during document persistence"),
        ):
            with self.assertRaises(RuntimeError):
                upload_execution_document(
                    self.execution.id,
                    file_obj=file_obj,
                    category=ExecutionDocumentCategory.CONTRACT,
                    actor=self.buyer_user,
                )

        # Verify that no document record exists in DB
        self.assertEqual(ExecutionDocument.objects.count(), 0)

        # Check MinIO: list objects under prefix execution-documents/{self.execution.id}/
        objects = list(
            self.client_minio.list_objects(
                self.bucket,
                prefix=f"execution-documents/{self.execution.id}/",
                recursive=True,
            )
        )
        self.assertEqual(len(objects), 0, f"Expected 0 orphaned objects in MinIO, found: {[o.object_name for o in objects]}")
