
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import IssueType
from execution.exceptions import ExecutionPermissionDeniedError
from execution.services import (
    create_or_get_execution_for_deal,
    open_issue,
    publish_version,
    resolve_issue,
    start_issue,
)
from execution.tests.base import BaseExecutionTestCase
from organizations.models import Organization, OrganizationMembership

User = get_user_model()


class IssueAuthorizationTests(BaseExecutionTestCase):
    """Authorization tests for ExecutionIssue actions and access control (Epic 10 Contract §77–§83, T1008)."""

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code="issue_auth_test")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        # Attributed broker (Attribution is provenance, NOT authorization)
        self.broker_user = User.objects.create_user(
            email="broker_attributed@platform.com",
            password="testpassword123",
        )
        self.deal.attribution_type = "BROKER"
        self.deal.broker_organization = Organization.objects.create(
            name="Attributed Broker Org",
            country="IR",
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=self.deal.broker_organization,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        self.deal.save()

        # Staff without SystemRoleAssignment
        self.staff_only_user = User.objects.create_user(
            email="staff_no_assignment@platform.com",
            password="testpassword123",
            is_staff=True,
        )

        # Superuser without SystemRoleAssignment
        self.superuser_only_user = User.objects.create_superuser(
            email="superuser_no_assignment@platform.com",
            password="testpassword123",
        )

        # Unrelated organization user
        self.unrelated_user = User.objects.create_user(
            email="unrelated_actor@competitor.com",
            password="testpassword123",
        )
        unrelated_org = Organization.objects.create(
            name="Unrelated Corp",
            country="IR",
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=unrelated_org,
            user=self.unrelated_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.client = APIClient()

    def test_buyer_and_seller_authorized(self):
        """Active non-viewer members of Buyer and Seller organizations can manage issues."""
        # Buyer opens issue
        issue = open_issue(
            self.execution.id,
            type=IssueType.LOGISTICS,
            title="Buyer report",
            actor=self.buyer_owner,
        )
        self.assertEqual(issue.opened_by, self.buyer_owner)

        # Seller investigates
        started = start_issue(self.execution.id, issue.id, expected_version=1, actor=self.supplier_user)
        self.assertEqual(started.version, 2)

        # Buyer resolves
        resolved = resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=2,
            resolution_notes="Resolved with supplier",
            actor=self.buyer_owner,
        )
        self.assertEqual(resolved.status, "RESOLVED")

    def test_operator_and_admin_authorized(self):
        """Platform Operator and Admin with SystemRoleAssignment have full issue authority."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.CONTRACT,
            title="Operator flagged discrepancy",
            actor=self.operator_user,
        )
        self.assertEqual(issue.opened_by, self.operator_user)

        admin_resolved = resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Admin cleared issue after verification",
            actor=self.admin_user,
        )
        self.assertEqual(admin_resolved.status, "RESOLVED")
        self.assertEqual(admin_resolved.resolved_by, self.admin_user)

    def test_viewer_role_rejected(self):
        """Viewer role in buyer or seller organization is strictly read-only (denied mutations)."""
        # Viewer in supplier org
        with self.assertRaises(ExecutionPermissionDeniedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Viewer attempt",
                actor=self.supplier_viewer,
            )

        # Via API returns 403
        self.client.force_authenticate(user=self.supplier_viewer)
        url = f"/api/execution/{self.execution.id}/issues/"
        resp = self.client.post(url, {"type": "OTHER", "title": "Viewer attempt"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_attributed_only_broker_rejected(self):
        """
        Attributed Broker confers provenance, NEVER operational authorization.
        Attributed broker must be denied all issue actions.
        """
        with self.assertRaises(ExecutionPermissionDeniedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Broker attempt",
                actor=self.broker_user,
            )

        self.client.force_authenticate(user=self.broker_user)
        url = f"/api/execution/{self.execution.id}/issues/"
        resp = self.client.post(url, {"type": "OTHER", "title": "Broker attempt"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Read also rejected for attributed broker
        resp_get = self.client.get(url)
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_and_superuser_without_assignment_rejected(self):
        """Django staff and superusers lacking explicit SystemRoleAssignment have NO product authority."""
        # Staff without SystemRoleAssignment
        with self.assertRaises(ExecutionPermissionDeniedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Staff attempt",
                actor=self.staff_only_user,
            )

        self.client.force_authenticate(user=self.staff_only_user)
        url = f"/api/execution/{self.execution.id}/issues/"
        resp = self.client.post(url, {"type": "OTHER", "title": "Staff attempt"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Superuser without SystemRoleAssignment
        with self.assertRaises(ExecutionPermissionDeniedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Superuser attempt",
                actor=self.superuser_only_user,
            )

        self.client.force_authenticate(user=self.superuser_only_user)
        resp_su = self.client.post(url, {"type": "OTHER", "title": "Superuser attempt"}, format="json")
        self.assertEqual(resp_su.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_and_unrelated_rejected(self):
        """Anonymous and unrelated organization users are strictly rejected."""
        # Unrelated user
        with self.assertRaises(ExecutionPermissionDeniedError):
            open_issue(
                self.execution.id,
                type=IssueType.OTHER,
                title="Competitor attempt",
                actor=self.unrelated_user,
            )

        self.client.force_authenticate(user=self.unrelated_user)
        url = f"/api/execution/{self.execution.id}/issues/"
        resp = self.client.post(url, {"type": "OTHER", "title": "Competitor attempt"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Anonymous
        self.client.force_authenticate(user=None)
        resp_anon = self.client.post(url, {"type": "OTHER", "title": "Anon attempt"}, format="json")
        self.assertIn(resp_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_external_seller_flow_no_fake_account(self):
        """
        External Seller execution (Epic 10 Contract §82):
        Deal with ExternalCounterparty seller has NO platform user account.
        Operator manages external-side actions; buyer sees safe state without fake account.
        """
        deal_ext = self.create_sample_deal(external_seller=True)
        self.assertIsNone(deal_ext.seller_organization)
        self.assertIsNotNone(deal_ext.seller_external_counterparty)

        exec_ext = create_or_get_execution_for_deal(
            deal_id=deal_ext.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

        # Operator opens and resolves issue on external side without fake account
        issue = open_issue(
            exec_ext.id,
            type=IssueType.QUALITY,
            title="External seller batch variance",
            actor=self.operator_user,
        )
        self.assertEqual(issue.opened_by, self.operator_user)

        res = resolve_issue(
            exec_ext.id,
            issue.id,
            expected_version=1,
            resolution_notes="External supplier provided replacement batch.",
            actor=self.operator_user,
        )
        self.assertEqual(res.status, "RESOLVED")
        self.assertEqual(res.resolved_by, self.operator_user)

        # Buyer can safely read issue state
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/execution/{exec_ext.id}/issues/{issue.id}/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "RESOLVED")
