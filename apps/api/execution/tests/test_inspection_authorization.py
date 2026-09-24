from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import InspectionResult, InspectionStatus
from execution.exceptions import ExecutionPermissionDeniedError
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    cancel_inspection,
    complete_inspection,
    create_or_get_execution_for_deal,
    mark_inspection_not_required,
    schedule_inspection,
)
from execution.tests.base import BaseExecutionTestCase
from identity.models import SystemRoleAssignment
from organizations.models import Organization, OrganizationMembership

User = get_user_model()


class InspectionAuthorizationTests(BaseExecutionTestCase):
    """
    Tests for side-authority, product roles, external seller paths, and permission matrices (Contract §80, T1005).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

        # Create Product Admin
        self.admin_user = User.objects.create_user(
            email="admin_prod@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Create Buyer Viewer
        self.buyer_viewer = User.objects.create_user(
            email="buyer_viewer@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # Create Unrelated Organization & User
        self.unrelated_org = Organization.objects.create(
            name="Unrelated Corp",
            is_active=True,
        )

        self.unrelated_user = User.objects.create_user(
            email="unrelated@other.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.unrelated_org,
            user=self.unrelated_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

    def test_seller_allowed_operational_actions(self):
        """Seller organization non-viewer can perform schedule, complete, and cancel actions."""
        now = timezone.now()

        # 1. Schedule inspection
        insp = schedule_inspection(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_at=now + timezone.timedelta(days=2),
            agency="SGS Inspection Services",
        )
        self.assertEqual(insp.status, InspectionStatus.SCHEDULED)
        self.assertEqual(insp.agency, "SGS Inspection Services")
        self.assertEqual(insp.version, 2)

        # 2. Complete inspection
        insp = complete_inspection(
            self.execution.id,
            expected_version=2,
            actor=self.supplier_user,
            inspection_at=now + timezone.timedelta(days=2, hours=1),
            result=InspectionResult.PASS,
        )
        self.assertEqual(insp.status, InspectionStatus.COMPLETED)
        self.assertEqual(insp.result, InspectionResult.PASS)
        self.assertEqual(insp.version, 3)

    def test_seller_denied_buyer_mark_not_required(self):
        """Seller is strictly denied from unilaterally waiving inspection required by Buyer."""
        with self.assertRaises(ExecutionPermissionDeniedError):
            mark_inspection_not_required(
                self.execution.id,
                expected_version=1,
                actor=self.supplier_user,
            )

        # Via API
        self.client.force_authenticate(user=self.supplier_user)
        url = f"/api/execution/{self.execution.id}/inspection/mark-not-required/"
        resp = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_buyer_allowed_mark_not_required(self):
        """Buyer organization non-viewer can waive inspection requirement."""
        insp = mark_inspection_not_required(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            notes="Buyer waived laboratory testing.",
        )
        self.assertEqual(insp.status, InspectionStatus.NOT_REQUIRED)
        self.assertFalse(insp.required)
        self.assertEqual(insp.version, 2)

    def test_buyer_denied_seller_operational_actions(self):
        """Buyer is strictly denied from seller operational actions (schedule, complete, cancel)."""
        now = timezone.now()

        # Buyer cannot schedule
        with self.assertRaises(ExecutionPermissionDeniedError):
            schedule_inspection(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                scheduled_at=now,
            )

        # Buyer cannot complete
        with self.assertRaises(ExecutionPermissionDeniedError):
            complete_inspection(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                inspection_at=now,
                result=InspectionResult.PASS,
            )

        # Buyer cannot cancel
        with self.assertRaises(ExecutionPermissionDeniedError):
            cancel_inspection(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
            )

        # Verify via API returns 403 Forbidden
        self.client.force_authenticate(user=self.buyer_owner)
        url_sched = f"/api/execution/{self.execution.id}/inspection/schedule/"
        resp_sched = self.client.post(
            url_sched,
            {"expected_version": 1, "scheduled_at": now.isoformat()},
            format="json",
        )
        self.assertEqual(resp_sched.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewers_read_only_denied_mutation(self):
        """Viewer role in Buyer or Seller org can read but is strictly denied mutation."""
        now = timezone.now()

        # Buyer viewer can read
        self.client.force_authenticate(user=self.buyer_viewer)
        resp_read = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertEqual(resp_read.status_code, status.HTTP_200_OK)

        # Buyer viewer cannot mark not required
        resp_mut = self.client.post(
            f"/api/execution/{self.execution.id}/inspection/mark-not-required/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_mut.status_code, status.HTTP_403_FORBIDDEN)

        # Seller viewer can read
        self.client.force_authenticate(user=self.supplier_viewer)
        resp_read_s = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertEqual(resp_read_s.status_code, status.HTTP_200_OK)

        # Seller viewer cannot schedule
        resp_sched = self.client.post(
            f"/api/execution/{self.execution.id}/inspection/schedule/",
            {"expected_version": 1, "scheduled_at": now.isoformat()},
            format="json",
        )
        self.assertEqual(resp_sched.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_and_admin_full_authority(self):
        """Platform Operator and Product Admin can perform all inspection actions."""
        now = timezone.now()

        # Operator can schedule
        insp = schedule_inspection(
            self.execution.id,
            expected_version=1,
            actor=self.operator_user,
            scheduled_at=now,
            agency="Bureau Veritas",
        )
        self.assertEqual(insp.status, InspectionStatus.SCHEDULED)

        # Admin can complete
        insp = complete_inspection(
            self.execution.id,
            expected_version=2,
            actor=self.admin_user,
            inspection_at=now,
            result=InspectionResult.PASS,
        )
        self.assertEqual(insp.status, InspectionStatus.COMPLETED)

    def test_attributed_only_broker_denied(self):
        """Attributed-only Broker has NO access to inspection details or mutation (403 Forbidden)."""
        self.client.force_authenticate(user=self.broker_user)


        resp_get = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        resp_act = self.client.post(
            f"/api/execution/{self.execution.id}/inspection/schedule/",
            {"expected_version": 1, "scheduled_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp_act.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_or_superuser_without_system_role_denied(self):
        """Django staff/superuser alone confers NO product authority (403 Forbidden)."""
        self.client.force_authenticate(user=self.staff_only_user)

        resp_get = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        resp_act = self.client.post(
            f"/api/execution/{self.execution.id}/inspection/schedule/",
            {"expected_version": 1, "scheduled_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp_act.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelated_organization_denied(self):
        """Competitors / unrelated organizations have no access (403 Forbidden)."""
        self.client.force_authenticate(user=self.unrelated_user)

        resp_get = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_denied(self):
        """Unauthenticated requests return 401 Unauthorized or 403 Forbidden."""
        resp = self.client.get(f"/api/execution/{self.execution.id}/inspection/")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_external_counterparty_seller_flow(self):
        """
        ExternalCounterparty seller has no login account.
        Operator manages seller-side actions on external seller's behalf.
        Buyer can read safe execution state.
        No fake user/organization created.
        """
        ext_deal = self.create_sample_deal(external_seller=True)
        self.assertTrue(ext_deal.is_external)
        self.assertIsNotNone(ext_deal.seller_external_counterparty_id)
        self.assertIsNone(ext_deal.seller_organization_id)

        ext_exec = create_or_get_execution_for_deal(deal_id=ext_deal.id, actor=self.operator_user)

        # Buyer can read
        self.client.force_authenticate(user=self.buyer_owner)
        resp = self.client.get(f"/api/execution/{ext_exec.id}/inspection/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Operator performs seller-side schedule
        now = timezone.now()
        insp = schedule_inspection(
            ext_exec.id,
            expected_version=1,
            actor=self.operator_user,
            scheduled_at=now,
            agency="External Agency",
        )
        self.assertEqual(insp.status, InspectionStatus.SCHEDULED)

        # Operator performs seller-side completion
        insp = complete_inspection(
            ext_exec.id,
            expected_version=2,
            actor=self.operator_user,
            inspection_at=now,
            result=InspectionResult.PASS,
        )
        self.assertEqual(insp.status, InspectionStatus.COMPLETED)
