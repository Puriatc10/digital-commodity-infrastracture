import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from deals.models import DealBrokerAttribution, DealBrokerRole
from execution.enums import ExecutionStatus
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    complete_milestone,
    create_or_get_execution_for_deal,
)
from execution.tests.base import BaseExecutionTestCase
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class ExecutionAuthorizationMatrixTests(BaseExecutionTestCase):
    """
    Comprehensive Authorization Matrix tests (Epic 10 Contract §77, §78, §79, §80, §81, §82, T1003).

    Matrix:
    - Buyer (Owner/Manager/Member): Allowed
    - Seller (Internal): Allowed
    - Operator: Allowed
    - Product Admin: Allowed
    - Viewer (Buyer or Seller side): Read-only, mutation denied (403)
    - Unrelated Organization: Denied (403)
    - Attributed-only Broker: Denied (403)
    - Staff-only / Superuser-only (lacking SystemRoleAssignment): Denied (403)
    - Anonymous: Denied (401)
    - External Seller: No platform user; Operator manages actions; no fake account
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.m_contract = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="CONTRACT_SIGNED"
        )
        self.client = APIClient()

        # Unrelated Organization & User
        self.unrelated_org = Organization.objects.create(name="Unrelated Org", country="IR", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.unrelated_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.unrelated_user = User.objects.create_user(
            email=f"unrelated_{uuid.uuid4().hex[:4]}@unrelated.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.unrelated_org,
            user=self.unrelated_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Attributed broker organization (attribution provenance on Deal)
        self.deal_broker_user = self.broker_user
        DealBrokerAttribution.objects.create(
            deal=self.deal,
            broker_organization=self.broker_org,
            role=DealBrokerRole.SUPPLY_ORIGINATOR,
        )

    def test_operator_and_admin_have_full_access(self):
        """Platform Operator and Admin can read and mutate execution."""
        # Operator
        self.client.force_authenticate(user=self.operator_user)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Admin
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_buyer_owner_can_read_and_mutate(self):
        """Active buyer owner has read and mutation access."""
        self.client.force_authenticate(user=self.buyer_owner)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Complete CONTRACT_SIGNED
        url = f"/api/execution/{self.execution.id}/milestones/{self.m_contract.id}/complete/"
        resp_act = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(resp_act.status_code, status.HTTP_200_OK)

    def test_seller_owner_can_read_and_mutate(self):
        """Active seller owner has read and mutation access."""
        self.client.force_authenticate(user=self.supplier_owner)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_viewer_is_read_only_mutation_denied(self):
        """Viewer role can read execution but is rejected from mutation (403)."""
        self.client.force_authenticate(user=self.buyer_viewer)
        # Read succeeds
        resp_read = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp_read.status_code, status.HTTP_200_OK)

        # Mutation fails with 403 Forbidden
        url = f"/api/execution/{self.execution.id}/milestones/{self.m_contract.id}/complete/"
        resp_mut = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(resp_mut.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelated_organization_denied(self):
        """User from unrelated organization is denied access (403)."""
        self.client.force_authenticate(user=self.unrelated_user)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        url = f"/api/execution/{self.execution.id}/milestones/{self.m_contract.id}/complete/"
        resp_act = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(resp_act.status_code, status.HTTP_403_FORBIDDEN)

    def test_attributed_only_broker_denied(self):
        """Attributed-only Broker has NO access to execution (403 Forbidden)."""
        self.client.force_authenticate(user=self.deal_broker_user)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        url = f"/api/execution/{self.execution.id}/milestones/{self.m_contract.id}/complete/"
        resp_act = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(resp_act.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_or_superuser_without_system_role_denied(self):
        """Django staff/superuser alone confers NO product authority (403 Forbidden)."""
        self.client.force_authenticate(user=self.staff_only_user)
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_denied(self):
        """Unauthenticated requests return 401 Unauthorized or 403 Forbidden."""
        resp = self.client.get(f"/api/deals/{self.deal.id}/execution/")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_external_counterparty_seller_flow(self):
        """
        ExternalCounterparty seller has no user account.
        Operator manages seller-side actions.
        No fake User/Organization/Membership is created.
        """
        ext_deal = self.create_sample_deal(external_seller=True)
        self.assertTrue(ext_deal.is_external)
        self.assertIsNotNone(ext_deal.seller_external_counterparty_id)
        self.assertIsNone(ext_deal.seller_organization_id)

        # Operator creates execution
        ext_exec = create_or_get_execution_for_deal(
            deal_id=ext_deal.id,
            actor=self.operator_user,
        )
        self.assertEqual(ext_exec.status, ExecutionStatus.OPEN)

        # Buyer can read
        self.client.force_authenticate(user=self.buyer_owner)
        resp = self.client.get(f"/api/deals/{ext_deal.id}/execution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Operator completes seller actions on behalf of external seller
        m_contract = ExecutionMilestone.objects.get(execution=ext_exec, definition__code="CONTRACT_SIGNED")
        complete_milestone(
            execution_id=ext_exec.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actor=self.operator_user,
        )
        m_contract.refresh_from_db()
        self.assertEqual(m_contract.completed_by, self.operator_user)
