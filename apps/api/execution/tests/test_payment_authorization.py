from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import PaymentStatus
from execution.exceptions import ExecutionPermissionDeniedError
from execution.models.payment import ExecutionPayment
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    confirm_payment,
    create_or_get_execution_for_deal,
    report_payment,
)
from execution.tests.base import BaseExecutionTestCase
from identity.models import SystemRoleAssignment
from organizations.models import Organization, OrganizationMembership

User = get_user_model()


class PaymentAuthorizationTests(BaseExecutionTestCase):
    """
    Tests for side-authority, product roles, external seller paths, and permission matrices (Epic 10 Contract §57, T1006).
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

    def test_buyer_can_report_payment(self):
        """Buyer organization operational non-viewer member can report payment."""
        pmt = report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            reference="REF-BUYER-001",
            notes="Buyer payment reported via TT",
        )
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)
        self.assertEqual(pmt.reported_by, self.buyer_owner)
        self.assertEqual(pmt.reference, "REF-BUYER-001")
        self.assertIsNotNone(pmt.reported_at)

    def test_buyer_can_report_payment_via_api(self):
        """Buyer reporting payment via REST API succeeds."""
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/execution/{self.execution.id}/payment/report/"
        resp = self.client.post(
            url,
            {"expected_version": 1, "reference": "REF-API-101", "notes": "API report"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "REPORTED")
        self.assertEqual(resp.data["reported_by_id"], str(self.buyer_owner.id))

    def test_seller_can_report_payment(self):
        """Seller organization operational non-viewer member can report payment fact."""
        pmt = report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            reference="REF-SELLER-001",
            notes="Seller received check/remittance advice",
        )
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)
        self.assertEqual(pmt.reported_by, self.supplier_user)

    def test_operator_and_admin_full_authority(self):
        """Platform Operator and Product Admin can report and confirm payments."""
        # 1. Operator reports
        pmt = report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.operator_user,
            reference="OP-REP-01",
        )
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)
        self.assertEqual(pmt.reported_by, self.operator_user)

        # 2. Admin confirms
        pmt = confirm_payment(
            self.execution.id,
            expected_version=2,
            actor=self.admin_user,
            reference="ADMIN-CONF-01",
            notes="Confirmed with central operations bank account",
        )
        self.assertEqual(pmt.status, PaymentStatus.CONFIRMED)
        self.assertEqual(pmt.confirmed_by, self.admin_user)
        self.assertIsNotNone(pmt.confirmed_at)

    def test_buyer_strictly_denied_confirmation(self):
        """Buyer organization member is strictly forbidden from confirming payment (403 Forbidden)."""
        # First report payment so status is REPORTED
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)

        # Attempt confirm via service
        with self.assertRaises(ExecutionPermissionDeniedError):
            confirm_payment(
                self.execution.id,
                expected_version=2,
                actor=self.buyer_owner,
            )

        # Attempt confirm via API
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/execution/{self.execution.id}/payment/confirm/"
        resp = self.client.post(
            url,
            {"expected_version": 2, "reference": "ILLEGAL-CONFIRM"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("restricted to Platform Operators and Admins", resp.data["detail"])

    def test_seller_strictly_denied_confirmation(self):
        """Seller organization member is strictly forbidden from confirming payment (403 Forbidden)."""
        report_payment(self.execution.id, expected_version=1, actor=self.supplier_user)

        # Attempt confirm via service
        with self.assertRaises(ExecutionPermissionDeniedError):
            confirm_payment(
                self.execution.id,
                expected_version=2,
                actor=self.supplier_user,
            )

        # Attempt confirm via API
        self.client.force_authenticate(user=self.supplier_user)
        url = f"/api/execution/{self.execution.id}/payment/confirm/"
        resp = self.client.post(
            url,
            {"expected_version": 2, "reference": "ILLEGAL-CONFIRM"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_role_denied_mutation(self):
        """Viewer role in buyer or seller organization is strictly read-only (403 Forbidden)."""
        # Buyer viewer report
        with self.assertRaises(ExecutionPermissionDeniedError):
            report_payment(self.execution.id, expected_version=1, actor=self.buyer_viewer)

        self.client.force_authenticate(user=self.buyer_viewer)
        resp = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Seller viewer report
        with self.assertRaises(ExecutionPermissionDeniedError):
            report_payment(self.execution.id, expected_version=1, actor=self.supplier_viewer)

        self.client.force_authenticate(user=self.supplier_viewer)
        resp = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_role_can_read_payment(self):
        """Viewer role can read payment monitoring details."""
        self.client.force_authenticate(user=self.buyer_viewer)
        resp = self.client.get(f"/api/execution/{self.execution.id}/payment/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "EXPECTED")

        # Via deal route
        resp_deal = self.client.get(f"/api/deals/{self.deal.id}/execution/payment/")
        self.assertEqual(resp_deal.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_deal.data["status"], "EXPECTED")

    def test_attributed_only_broker_denied(self):
        """Attributed-only Broker has NO access to payment details or mutation (403 Forbidden)."""
        self.client.force_authenticate(user=self.broker_user)

        resp_get = self.client.get(f"/api/execution/{self.execution.id}/payment/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        resp_rep = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_rep.status_code, status.HTTP_403_FORBIDDEN)

        resp_conf = self.client.post(
            f"/api/execution/{self.execution.id}/payment/confirm/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_conf.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_or_superuser_without_system_role_denied(self):
        """Django staff/superuser alone confers NO product authority (403 Forbidden)."""
        self.client.force_authenticate(user=self.staff_only_user)

        resp_get = self.client.get(f"/api/execution/{self.execution.id}/payment/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        resp_rep = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_rep.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelated_organization_denied(self):
        """Competitors / unrelated organizations have no access (403 Forbidden)."""
        self.client.force_authenticate(user=self.unrelated_user)

        resp_get = self.client.get(f"/api/execution/{self.execution.id}/payment/")
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        resp_rep = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertEqual(resp_rep.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_denied(self):
        """Unauthenticated requests are rejected."""
        resp_get = self.client.get(f"/api/execution/{self.execution.id}/payment/")
        self.assertIn(resp_get.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        resp_rep = self.client.post(
            f"/api/execution/{self.execution.id}/payment/report/",
            {"expected_version": 1},
            format="json",
        )
        self.assertIn(resp_rep.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_external_seller_flow_handled_via_operator(self):
        """
        When seller is ExternalCounterparty (no platform account):
        Operator/Admin monitors payment on external side without creating fake user accounts.
        """
        ext_deal = self.create_sample_deal(external_seller=True)
        self.assertIsNotNone(ext_deal.seller_external_counterparty)
        self.assertIsNone(ext_deal.seller_organization)

        ext_exec = create_or_get_execution_for_deal(deal_id=ext_deal.id, actor=self.operator_user)
        pmt = ExecutionPayment.objects.get(execution=ext_exec)
        self.assertEqual(pmt.status, PaymentStatus.EXPECTED)

        # Operator reports on behalf of external workflow
        pmt = report_payment(
            ext_exec.id,
            expected_version=1,
            actor=self.operator_user,
            reference="EXT-TXN-001",
            notes="Payment received by external counterparty verified via SWIFT advice",
        )
        self.assertEqual(pmt.status, PaymentStatus.REPORTED)
        self.assertEqual(pmt.reported_by, self.operator_user)

        # Operator confirms
        pmt = confirm_payment(
            ext_exec.id,
            expected_version=2,
            actor=self.operator_user,
            reference="OP-CONF-EXT",
        )
        self.assertEqual(pmt.status, PaymentStatus.CONFIRMED)
        self.assertEqual(pmt.confirmed_by, self.operator_user)
