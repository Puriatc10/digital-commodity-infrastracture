from decimal import Decimal
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment, User
from opportunities.models import (
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity
from organizations.models import Organization, OrganizationCapability


class OpportunityLifecycleAPITests(TestCase):
    """
    API integration tests for explicit Opportunity lifecycle action endpoints.

    Endpoints:
    - POST /api/opportunities/opportunities/{id}/contact/
    - POST /api/opportunities/opportunities/{id}/qualify/
    - POST /api/opportunities/opportunities/{id}/match/
    - POST /api/opportunities/opportunities/{id}/hold/
    - POST /api/opportunities/opportunities/{id}/resume/
    - POST /api/opportunities/opportunities/{id}/reject/
    - POST /api/opportunities/opportunities/{id}/lost/
    - POST /api/opportunities/opportunities/{id}/expire/
    """

    def setUp(self):
        self.client = APIClient()

        # Operator user for authentication
        self.operator = User.objects.create_user(email="operator@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )
        self.client.force_authenticate(user=self.operator)

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_api_test",
            name_en="Bitumen API Test",
            name_fa="قیر تست ای پی آی",
        )
        self.buyer_org = Organization.objects.create(name="API Buyer Corp")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("300.000"),
            indicative_price=Decimal("360.00"),
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        self.base_url = f"/api/opportunities/opportunities/{self.opp.id}/"

    # -------------------------------------------------------------------------
    # 1. Contact Action
    # -------------------------------------------------------------------------

    def test_contact_endpoint_success(self):
        """POST contact returns HTTP 200 with updated status=Contacted and version=2."""
        url = f"{self.base_url}contact/"
        res = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.CONTACTED)
        self.assertEqual(res.data["version"], 2)
        self.assertIsNotNone(res.data["contacted_at"])

    def test_contact_endpoint_stale_version_returns_409(self):
        """POST contact with stale version returns HTTP 409 Conflict."""
        url = f"{self.base_url}contact/"
        res = self.client.post(url, {"expected_version": 99}, format="json")

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version error", res.data["detail"])

    def test_contact_endpoint_missing_expected_version_returns_400(self):
        """POST contact with missing expected_version returns HTTP 400."""
        url = f"{self.base_url}contact/"
        res = self.client.post(url, {}, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # 2. Qualify Action
    # -------------------------------------------------------------------------

    def test_qualify_endpoint_success(self):
        """POST qualify returns HTTP 200 with status=Qualified and version=2."""
        url = f"{self.base_url}qualify/"
        res = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.QUALIFIED)
        self.assertEqual(res.data["version"], 2)
        self.assertIsNotNone(res.data["qualified_at"])

    # -------------------------------------------------------------------------
    # 3. Match Action
    # -------------------------------------------------------------------------

    def test_match_endpoint_success(self):
        """POST match advances Qualified opportunity to Matching."""
        # First qualify
        self.client.post(f"{self.base_url}qualify/", {"expected_version": 1}, format="json")

        url = f"{self.base_url}match/"
        res = self.client.post(url, {"expected_version": 2}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.MATCHING)
        self.assertEqual(res.data["version"], 3)

    def test_match_endpoint_invalid_transition_from_captured_returns_400(self):
        """Attempting to match a Captured opportunity directly returns HTTP 400."""
        url = f"{self.base_url}match/"
        res = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only Qualified opportunities can enter Matching", res.data["detail"])

    # -------------------------------------------------------------------------
    # 4. Hold & Resume Actions
    # -------------------------------------------------------------------------

    def test_hold_endpoint_success(self):
        """POST hold requires reason, returns HTTP 200 with status=On Hold."""
        url = f"{self.base_url}hold/"
        payload = {"expected_version": 1, "reason": "Awaiting customer inspection results"}
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.ON_HOLD)
        self.assertEqual(res.data["status_before_hold"], OpportunityStatus.CAPTURED)
        self.assertEqual(res.data["hold_reason"], "Awaiting customer inspection results")
        self.assertEqual(res.data["version"], 2)

    def test_hold_endpoint_missing_reason_returns_400(self):
        """POST hold without reason returns HTTP 400."""
        url = f"{self.base_url}hold/"
        res = self.client.post(url, {"expected_version": 1, "reason": ""}, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resume_endpoint_success(self):
        """POST resume restores pre-hold status without requiring target status."""
        self.client.post(f"{self.base_url}qualify/", {"expected_version": 1}, format="json")
        self.client.post(
            f"{self.base_url}hold/",
            {"expected_version": 2, "reason": "Paused for pricing check"},
            format="json",
        )

        url = f"{self.base_url}resume/"
        res = self.client.post(url, {"expected_version": 3}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.QUALIFIED)
        self.assertEqual(res.data["status_before_hold"], "")
        self.assertEqual(res.data["version"], 4)

    # -------------------------------------------------------------------------
    # 5. Reject, Lost, Expire Actions
    # -------------------------------------------------------------------------

    def test_reject_endpoint_success(self):
        """POST reject transitions to Rejected with mandatory reason."""
        url = f"{self.base_url}reject/"
        payload = {"expected_version": 1, "reason": "Counterparty declined terms"}
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.REJECTED)
        self.assertEqual(res.data["rejection_reason"], "Counterparty declined terms")
        self.assertIsNotNone(res.data["rejected_at"])
        self.assertEqual(res.data["version"], 2)

    def test_reject_endpoint_missing_reason_returns_400(self):
        """POST reject without reason returns HTTP 400."""
        url = f"{self.base_url}reject/"
        res = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lost_endpoint_success(self):
        """POST lost transitions to Lost with mandatory reason."""
        url = f"{self.base_url}lost/"
        payload = {"expected_version": 1, "reason": "Lost to direct refinery deal"}
        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.LOST)
        self.assertEqual(res.data["lost_reason"], "Lost to direct refinery deal")
        self.assertIsNotNone(res.data["lost_at"])
        self.assertEqual(res.data["version"], 2)

    def test_expire_endpoint_success(self):
        """POST expire transitions to Expired with optional reason."""
        url = f"{self.base_url}expire/"
        res = self.client.post(url, {"expected_version": 1, "reason": "Window closed"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.EXPIRED)
        self.assertEqual(res.data["expiration_reason"], "Window closed")
        self.assertIsNotNone(res.data["expired_at"])
        self.assertEqual(res.data["version"], 2)

    # -------------------------------------------------------------------------
    # 6. Not Found & Generic Update Guards
    # -------------------------------------------------------------------------

    def test_action_on_non_existent_opportunity_returns_404(self):
        """Action endpoint on non-existent UUID returns HTTP 404."""
        random_id = uuid.uuid4()
        url = f"/api/opportunities/opportunities/{random_id}/contact/"
        res = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_generic_patch_cannot_modify_status(self):
        """Attempting to PATCH status directly via generic update endpoint is ignored/not updated."""
        res = self.client.patch(self.base_url, {"status": OpportunityStatus.CONVERTED}, format="json")

        # Generic update ignores status as it is not writable on OpportunityUpdateSerializer
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
