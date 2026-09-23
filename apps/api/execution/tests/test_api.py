from rest_framework import status
from rest_framework.test import APITestCase

from execution.services import publish_version
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowApiTests(BaseExecutionTestCase, APITestCase):
    """Test REST API endpoints for workflow templates and versions."""

    def test_operator_list_templates(self):
        """Operator can list workflow templates."""
        self.create_sample_template(code="tmpl_api_1")
        self.create_sample_template(code="tmpl_api_2")

        self.client.force_authenticate(user=self.operator_user)
        response = self.client.get("/api/execution/templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.data]
        self.assertIn("tmpl_api_1", codes)
        self.assertIn("tmpl_api_2", codes)

    def test_operator_get_template_detail(self):
        """Operator can retrieve template details by code."""
        template = self.create_sample_template(code="detail_tmpl")
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        self.client.force_authenticate(user=self.operator_user)
        response = self.client.get(f"/api/execution/templates/{template.code}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "detail_tmpl")
        self.assertEqual(response.data["active_version"]["version_number"], 1)

    def test_operator_get_active_version(self):
        """Operator can retrieve active published version by template code."""
        template = self.create_sample_template(code="active_tmpl")
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        self.client.force_authenticate(user=self.operator_user)
        response = self.client.get(f"/api/execution/templates/{template.code}/active-version/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version_number"], 1)
        self.assertEqual(response.data["status"], "PUBLISHED")
        self.assertEqual(len(response.data["milestones"]), 3)

    def test_operator_get_version_detail(self):
        """Operator can retrieve version detail with milestones and prerequisites."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)

        self.client.force_authenticate(user=self.operator_user)
        response = self.client.get(f"/api/execution/versions/{v1.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version_number"], 1)
        milestones = response.data["milestones"]
        self.assertEqual(len(milestones), 3)

        # Check prerequisite codes
        step_two = next(m for m in milestones if m["code"] == "STEP_TWO")
        self.assertEqual(step_two["prerequisite_codes"], ["STEP_ONE"])

    def test_customer_denied(self):
        """Buyer/Supplier/Broker users are denied access to workflow template management APIs."""
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get("/api/execution/templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.supplier_user)
        response = self.client.get("/api/execution/templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.broker_user)
        response = self.client.get("/api/execution/templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_denied(self):
        """Unauthenticated requests are denied."""
        response = self.client.get("/api/execution/templates/")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_not_found_responses(self):
        """Non-existent template or version returns 404."""
        self.client.force_authenticate(user=self.operator_user)
        res_tmpl = self.client.get("/api/execution/templates/non_existent_code/")
        self.assertEqual(res_tmpl.status_code, status.HTTP_404_NOT_FOUND)

        import uuid
        res_ver = self.client.get(f"/api/execution/versions/{uuid.uuid4()}/")
        self.assertEqual(res_ver.status_code, status.HTTP_404_NOT_FOUND)
