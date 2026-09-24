import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus, IssueType
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionIssueNotFoundError,
)
from execution.services import (
    cancel_issue,
    create_or_get_execution_for_deal,
    get_execution_issue_detail,
    open_issue,
    publish_version,
    resolve_issue,
    start_issue,
)
from execution.tests.base import BaseExecutionTestCase


class IssueCrossSecurityAndClosedTests(BaseExecutionTestCase):
    """
    Tests for cross-object integrity protection and closed execution safeguards for issues
    (Epic 10 Contract §67, §73, T1008).
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code=f"cross_sec_{uuid.uuid4().hex[:6]}")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal_1 = self.create_sample_deal()
        self.execution_1 = create_or_get_execution_for_deal(
            deal_id=self.deal_1.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        self.deal_2 = self.create_sample_deal()
        self.execution_2 = create_or_get_execution_for_deal(
            deal_id=self.deal_2.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        self.issue_1 = open_issue(
            self.execution_1.id,
            type=IssueType.QUALITY,
            title="Quality variance on deal 1",
            actor=self.buyer_owner,
        )

        self.client = APIClient()

    def test_cross_execution_issue_access_service_rejected(self):
        """Cross-referencing mismatched execution and issue raises CrossObjectIntegrityError or NotFound."""
        # 1. get_execution_issue_detail with mismatched execution
        with self.assertRaises((CrossObjectIntegrityError, ExecutionIssueNotFoundError)):
            get_execution_issue_detail(
                self.execution_2.id,
                self.issue_1.id,
                actor=self.operator_user,
            )

        # 2. start_issue with mismatched execution
        with self.assertRaises(CrossObjectIntegrityError):
            start_issue(
                self.execution_2.id,
                self.issue_1.id,
                expected_version=1,
                actor=self.operator_user,
            )

        # 3. resolve_issue with mismatched execution
        with self.assertRaises(CrossObjectIntegrityError):
            resolve_issue(
                self.execution_2.id,
                self.issue_1.id,
                expected_version=1,
                resolution_notes="Mismatched execution resolution attempt",
                actor=self.operator_user,
            )

        # 4. cancel_issue with mismatched execution
        with self.assertRaises(CrossObjectIntegrityError):
            cancel_issue(
                self.execution_2.id,
                self.issue_1.id,
                expected_version=1,
                actor=self.operator_user,
            )

    def test_cross_execution_issue_access_api_rejected(self):
        """Accessing issue_1 via execution_2 URL returns 404 or 400."""
        self.client.force_authenticate(user=self.operator_user)

        # Detail view returns 400 or 404
        url_detail = f"/api/execution/{self.execution_2.id}/issues/{self.issue_1.id}/"
        resp = self.client.get(url_detail)
        self.assertIn(resp.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

        # Actions via mismatched execution return 400 or 404
        url_start = f"/api/execution/{self.execution_2.id}/issues/{self.issue_1.id}/start/"
        resp_start = self.client.post(url_start, {"expected_version": 1}, format="json")
        self.assertIn(resp_start.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

        url_resolve = f"/api/execution/{self.execution_2.id}/issues/{self.issue_1.id}/resolve/"
        resp_resolve = self.client.post(
            url_resolve,
            {"expected_version": 1, "resolution_notes": "Attempt"},
            format="json",
        )
        self.assertIn(resp_resolve.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

        url_cancel = f"/api/execution/{self.execution_2.id}/issues/{self.issue_1.id}/cancel/"
        resp_cancel = self.client.post(url_cancel, {"expected_version": 1}, format="json")
        self.assertIn(resp_cancel.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

    def test_cross_deal_issue_access_api_404(self):
        """Accessing issue_1 via Deal 2 URL returns 400 or 404."""
        self.client.force_authenticate(user=self.operator_user)
        deal_url = f"/api/deals/{self.deal_2.id}/execution/issues/{self.issue_1.id}/"
        resp = self.client.get(deal_url)
        self.assertIn(resp.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

    def test_closed_execution_rejects_issue_mutations(self):
        """Mutations on an already CLOSED execution are rejected with ExecutionClosedError / 409."""
        self.execution_1.status = ExecutionStatus.CLOSED
        self.execution_1.closed_at = timezone.now()
        self.execution_1.save()

        # Service level
        with self.assertRaises(ExecutionClosedError):
            open_issue(
                self.execution_1.id,
                type=IssueType.LOGISTICS,
                title="Post-close dispute",
                actor=self.buyer_owner,
            )

        with self.assertRaises(ExecutionClosedError):
            start_issue(
                self.execution_1.id,
                self.issue_1.id,
                expected_version=1,
                actor=self.buyer_owner,
            )

        with self.assertRaises(ExecutionClosedError):
            resolve_issue(
                self.execution_1.id,
                self.issue_1.id,
                expected_version=1,
                resolution_notes="Post-close resolve",
                actor=self.buyer_owner,
            )

        with self.assertRaises(ExecutionClosedError):
            cancel_issue(
                self.execution_1.id,
                self.issue_1.id,
                expected_version=1,
                actor=self.buyer_owner,
            )

        # API level returns HTTP 400 or 409
        self.client.force_authenticate(user=self.buyer_owner)
        resp_open = self.client.post(
            f"/api/execution/{self.execution_1.id}/issues/",
            {"type": "LOGISTICS", "title": "Post close API open"},
            format="json",
        )
        self.assertIn(resp_open.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

        resp_start = self.client.post(
            f"/api/execution/{self.execution_1.id}/issues/{self.issue_1.id}/start/",
            {"expected_version": 1},
            format="json",
        )
        self.assertIn(resp_start.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

        resp_res = self.client.post(
            f"/api/execution/{self.execution_1.id}/issues/{self.issue_1.id}/resolve/",
            {"expected_version": 1, "resolution_notes": "Attempt"},
            format="json",
        )
        self.assertIn(resp_res.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

        resp_can = self.client.post(
            f"/api/execution/{self.execution_1.id}/issues/{self.issue_1.id}/cancel/",
            {"expected_version": 1},
            format="json",
        )
        self.assertIn(resp_can.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT])

    def test_unrelated_organization_isolation(self):
        """Unrelated organization actor is denied access to issues with HTTP 403."""
        self.client.force_authenticate(user=self.foreign_buyer_user)

        resp_list = self.client.get(f"/api/execution/{self.execution_1.id}/issues/")
        self.assertEqual(resp_list.status_code, status.HTTP_403_FORBIDDEN)

        resp_open = self.client.post(
            f"/api/execution/{self.execution_1.id}/issues/",
            {"type": "OTHER", "title": "Intruder issue"},
            format="json",
        )
        self.assertEqual(resp_open.status_code, status.HTTP_403_FORBIDDEN)
