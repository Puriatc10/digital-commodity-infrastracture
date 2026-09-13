from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment, User
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQInvitation, RFQInvitationStatus, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import publish_rfq


class RFQWorkspaceAPITests(TestCase):
    """
    Test suite for RFQ Workspace API operations (T0507):
    - RFQ Close action with concurrency checks
    - RFQ Cancel action with concurrency and reason checks
    - Chronological activity facts projection and competitor isolation
    - Direct route security (scoping before retrieval)
    """

    def setUp(self):
        # 1. Commodities & Schemas
        self.bitumen = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.schema_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_v1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.schema_v1, activate=True)

        # 2. Organizations
        # Buyer Org A (Owner)
        self.buyer_org = Organization.objects.create(
            name="Pars Procurement",
            registration_identifier="REG-BUYER-01",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )

        # Supplier Org 1 (Invited)
        self.supplier_org_1 = Organization.objects.create(
            name="Tehran Bitumen Refinery",
            registration_identifier="REG-SUPP-01",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org_1,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )

        # Supplier Org 2 (Competitor, Invited)
        self.supplier_org_2 = Organization.objects.create(
            name="Isfahan Oil Products",
            registration_identifier="REG-SUPP-02",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org_2,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )

        # Uninvited Supplier Org 3
        self.supplier_org_3 = Organization.objects.create(
            name="Shiraz Petro Supplies",
            registration_identifier="REG-SUPP-03",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org_3,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )

        # 3. Users & Memberships
        self.buyer_owner = User.objects.create_user(
            email="buyer_owner@example.com", password="TestPassword123!"
        )
        OrganizationMembership.objects.create(
            user=self.buyer_owner,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.buyer_member = User.objects.create_user(
            email="buyer_member@example.com", password="TestPassword123!"
        )
        OrganizationMembership.objects.create(
            user=self.buyer_member,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        self.supplier_user_1 = User.objects.create_user(
            email="supplier_user_1@example.com", password="TestPassword123!"
        )
        OrganizationMembership.objects.create(
            user=self.supplier_user_1,
            organization=self.supplier_org_1,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.supplier_user_2 = User.objects.create_user(
            email="supplier_user_2@example.com", password="TestPassword123!"
        )
        OrganizationMembership.objects.create(
            user=self.supplier_user_2,
            organization=self.supplier_org_2,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.uninvited_user = User.objects.create_user(
            email="uninvited_user@example.com", password="TestPassword123!"
        )
        OrganizationMembership.objects.create(
            user=self.uninvited_user,
            organization=self.supplier_org_3,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.operator_user = User.objects.create_user(
            email="operator_user@example.com", password="TestPassword123!"
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # 4. Create base draft RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_owner,
            commodity=self.bitumen,
            schema_version=self.schema_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("5000.000"),
            unit="MT",
            target_price=Decimal("420.00"),
            currency="USD",
            incoterm="FOB",
            origin="Bandar Abbas",
            destination="Jebel Ali",
            status=RFQStatus.DRAFT,
            visibility=RFQVisibility.PRIVATE,
            version=1,
        )

        self.client = APIClient()

    # --- Close Action Tests ---

    def test_close_published_rfq_success(self):
        """Buyer Owner can successfully close a Published RFQ with expected_version."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)
        self.assertEqual(self.rfq.version, 2)

        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 2}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], RFQStatus.CLOSED)
        self.assertEqual(response.data["version"], 3)
        self.assertIsNotNone(response.data["closed_at"])

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.CLOSED)
        self.assertEqual(self.rfq.version, 3)

    def test_close_stale_expected_version_returns_409(self):
        """Stale expected_version returns 409 Conflict without modifying RFQ."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 1}, format="json")  # Stale: version is 2

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)
        self.assertEqual(self.rfq.version, 2)

    def test_close_draft_rfq_returns_400(self):
        """Closing a draft RFQ is an invalid transition and returns 400 Bad Request."""
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 1}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.DRAFT)

    def test_close_permission_denied_for_regular_member(self):
        """Regular organization member without Owner/Manager role receives 403 Forbidden."""
        publish_rfq(self.rfq.id, expected_version=1)

        self.client.force_authenticate(user=self.buyer_member)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 2}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_close_permission_denied_for_supplier(self):
        """Invited supplier cannot close RFQ (403 Forbidden)."""
        publish_rfq(self.rfq.id, expected_version=1)

        self.client.force_authenticate(user=self.supplier_user_1)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 2}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_can_close_rfq(self):
        """Platform operator can close RFQ on behalf of buyer."""
        publish_rfq(self.rfq.id, expected_version=1)

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/close/"
        response = self.client.post(url, {"expected_version": 2}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], RFQStatus.CLOSED)

    # --- Cancel Action Tests ---

    def test_cancel_draft_rfq_success(self):
        """Buyer Owner can cancel a Draft RFQ without a reason."""
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/cancel/"
        response = self.client.post(url, {"expected_version": 1, "reason": ""}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], RFQStatus.CANCELLED)
        self.assertEqual(response.data["version"], 2)
        self.assertIsNotNone(response.data["cancelled_at"])

    def test_cancel_published_rfq_with_reason_success(self):
        """Buyer Owner can cancel a Published RFQ with a non-empty reason."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/cancel/"
        response = self.client.post(
            url,
            {"expected_version": 2, "reason": "Market price volatility"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], RFQStatus.CANCELLED)
        self.assertEqual(response.data["cancellation_reason"], "Market price volatility")
        self.assertEqual(response.data["version"], 3)

    def test_cancel_published_rfq_without_reason_returns_400(self):
        """Cancelling a Published RFQ without reason is rejected with 400 Bad Request."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/cancel/"
        response = self.client.post(
            url,
            {"expected_version": 2, "reason": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)

    def test_cancel_stale_expected_version_returns_409(self):
        """Cancelling with stale version returns 409 Conflict."""
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/cancel/"
        response = self.client.post(
            url,
            {"expected_version": 99, "reason": "Test"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    # --- Activity Projection & Competitor Isolation Tests ---

    def test_activity_buyer_sees_all_facts(self):
        """Buyer sees full chronological facts: created, published, all supplier invitations, and views."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

        # Create two invitations
        RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.supplier_org_1,
            invited_by=self.buyer_owner,
            status=RFQInvitationStatus.VIEWED,
            viewed_at=timezone.now(),
        )
        RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.supplier_org_2,
            invited_by=self.buyer_owner,
            status=RFQInvitationStatus.DECLINED,
            declined_at=timezone.now(),
            decline_reason="No capacity currently",
        )

        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/activity/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = response.data
        event_types = [e["event_type"] for e in events]

        self.assertIn("rfq_created", event_types)
        self.assertIn("rfq_published", event_types)
        self.assertIn("participant_invited", event_types)
        self.assertIn("participant_viewed", event_types)
        self.assertIn("participant_declined", event_types)

        # Confirm Buyer sees both organizations
        org_names = [e["organization_name"] for e in events if e.get("organization_name")]
        self.assertIn(self.supplier_org_1.name, org_names)
        self.assertIn(self.supplier_org_2.name, org_names)

    def test_activity_external_supplier_never_sees_competitors(self):
        """External invited Supplier sees ONLY their own invitation events and public milestones."""
        publish_rfq(self.rfq.id, expected_version=1)
        self.rfq.refresh_from_db()

        # Inv1 for supplier 1
        RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.supplier_org_1,
            invited_by=self.buyer_owner,
            status=RFQInvitationStatus.VIEWED,
            viewed_at=timezone.now(),
        )
        # Inv2 for competitor supplier 2
        RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.supplier_org_2,
            invited_by=self.buyer_owner,
            status=RFQInvitationStatus.DECLINED,
            declined_at=timezone.now(),
            decline_reason="Secret competitor capacity reason",
        )

        self.client.force_authenticate(user=self.supplier_user_1)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/activity/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = response.data

        # Verify supplier 1 sees only published milestone and their own invitation/view
        for e in events:
            org_id = e.get("organization_id")
            if org_id and str(org_id) != str(self.buyer_org.id):
                self.assertEqual(
                    str(org_id),
                    str(self.supplier_org_1.id),
                    "Competitor event leaked to supplier!",
                )
                self.assertEqual(e["organization_name"], self.supplier_org_1.name)

        # Confirm supplier 2 was NEVER in the list
        all_text = str(response.data)
        self.assertNotIn("Isfahan Oil Products", all_text)
        self.assertNotIn("Secret competitor capacity reason", all_text)
        self.assertNotIn(str(self.supplier_org_2.id), all_text)

    def test_activity_hidden_rfq_returns_404(self):
        """Uninvited organization querying activity of private RFQ receives 404 Not Found."""
        publish_rfq(self.rfq.id, expected_version=1)

        self.client.force_authenticate(user=self.uninvited_user)
        url = f"/api/trade-hub/rfqs/{self.rfq.id}/activity/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
