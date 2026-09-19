from datetime import timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
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
from identity.models import SystemRoleAssignment
from offers.enums import LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.models import OfferCostComponent
from offers.services.creation import create_offer
from offers.services.version_services import create_draft_offer_version
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQInvitation, RFQInvitationStatus, RFQStatus, RFQVisibility

User = get_user_model()


class OfferSubmissionAPITests(TestCase):
    """
    Comprehensive REST API tests for T0803:
    POST /api/offers/offer-versions/{version_id}/submit/
    POST /api/offer-versions/{version_id}/submit/
    """

    def setUp(self):
        self.client = APIClient()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_api_{uuid.uuid4().hex[:6]}",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.schema_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
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

        # Buyer Org & User
        self.buyer_org = Organization.objects.create(
            name=f"Buyer Corp {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email=f"buyer_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Published RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_v1,
            quantity=Decimal("1000.000"),
            unit="MT",
            submission_deadline=timezone.now() + timedelta(days=7),
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier Org
        self.supplier_org = Organization.objects.create(
            name=f"Supplier Co {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        self.supplier_cap = OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )

        # Supplier Users with different roles
        self.supplier_owner = User.objects.create_user(
            email=f"owner_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.supplier_manager = User.objects.create_user(
            email=f"mgr_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_manager,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        self.supplier_member = User.objects.create_user(
            email=f"mem_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        self.supplier_viewer = User.objects.create_user(
            email=f"view_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # Competitor Supplier Org & User
        self.competitor_org = Organization.objects.create(
            name=f"Competitor Co {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.competitor_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.competitor_user = User.objects.create_user(
            email=f"comp_{uuid.uuid4().hex[:4]}@competitor.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.competitor_org,
            user=self.competitor_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Operator User
        self.operator_user = User.objects.create_user(
            email=f"op_{uuid.uuid4().hex[:4]}@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # Base Offer and Draft
        self.offer = create_offer(
            actor=self.supplier_owner,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.draft = create_draft_offer_version(
            actor=self.supplier_owner,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("430.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.offer.refresh_from_db()
        self.endpoint_url = f"/api/offers/offer-versions/{self.draft.id}/submit/"
        self.direct_url = f"/api/offer-versions/{self.draft.id}/submit/"

    # -------------------------------------------------------------------------
    # 1. Authentication & Role Permissions
    # -------------------------------------------------------------------------

    def test_unauthenticated_request_rejected_401(self):
        """Unauthenticated user receives 401 Unauthorized or 403 Forbidden."""
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_owner_can_submit_successfully(self):
        """Organization Owner can submit draft offer version (200 OK)."""
        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], OfferVersionStatus.SUBMITTED)
        self.assertEqual(response.data["version_number"], 1)
        self.assertEqual(response.data["submitted_by_id"], self.supplier_owner.id)

    def test_manager_can_submit_successfully(self):
        """Organization Manager can submit draft offer version (200 OK)."""
        self.client.force_authenticate(user=self.supplier_manager)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], OfferVersionStatus.SUBMITTED)

    def test_member_can_submit_successfully(self):
        """Organization Member can submit draft offer version (200 OK)."""
        self.client.force_authenticate(user=self.supplier_member)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], OfferVersionStatus.SUBMITTED)

    def test_viewer_is_forbidden_403(self):
        """Organization Viewer role is read-only and receives 403 Forbidden."""
        self.client.force_authenticate(user=self.supplier_viewer)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Viewers have read-only access", response.data["detail"])

    # -------------------------------------------------------------------------
    # 2. Competitor Isolation / IDOR Security (404 Not Found)
    # -------------------------------------------------------------------------

    def test_competitor_attempting_submit_receives_404(self):
        """
        Competitor attempting to submit or probe another org's offer version
        receives 404 Not Found (privacy guard to conceal existence).
        """
        self.client.force_authenticate(user=self.competitor_user)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("does not exist", response.data["detail"])

    def test_nonexistent_version_id_receives_404(self):
        """Submitting non-existent version ID returns 404 Not Found."""
        self.client.force_authenticate(user=self.supplier_owner)
        url = f"/api/offers/offer-versions/{uuid.uuid4()}/submit/"
        response = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # 3. Optimistic Concurrency Control (400 / 409)
    # -------------------------------------------------------------------------

    def test_missing_expected_version_rejected_400(self):
        """Missing expected_version in request body returns 400 Bad Request."""
        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expected_version", response.data)

    def test_invalid_expected_version_type_rejected_400(self):
        """Non-integer expected_version returns 400 Bad Request."""
        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": "not-an-integer"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stale_expected_version_rejected_409(self):
        """Stale expected_version returns 409 Conflict with clear error."""
        self.client.force_authenticate(user=self.supplier_owner)
        stale_version = self.offer.aggregate_version + 5
        response = self.client.post(self.endpoint_url, {"expected_version": stale_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version", response.data["detail"])

    def test_resubmitting_already_submitted_version_rejected_409(self):
        """Submitting an already SUBMITTED version returns 409 Conflict."""
        self.client.force_authenticate(user=self.supplier_owner)
        # First submission succeeds
        resp1 = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        self.offer.refresh_from_db()
        # Second submission of same version fails with 409 Conflict
        resp2 = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("cannot be submitted again", resp2.data["detail"])

    # -------------------------------------------------------------------------
    # 4. Direct URL Alias Support
    # -------------------------------------------------------------------------

    def test_direct_url_alias_works_identically(self):
        """Direct route /api/offer-versions/{id}/submit/ executes identically."""
        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.direct_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], OfferVersionStatus.SUBMITTED)

    # -------------------------------------------------------------------------
    # 5. Actor & Field Spoofing Guard
    # -------------------------------------------------------------------------

    def test_actor_spoofing_payload_ignored(self):
        """
        Client sending spoofed fields (submitted_by, status, quantity, etc.)
        in POST body cannot override authenticated actor or draft data.
        """
        self.client.force_authenticate(user=self.supplier_member)
        payload = {
            "expected_version": self.offer.aggregate_version,
            "submitted_by": self.supplier_owner.id,
            "status": "DRAFT",
            "offered_quantity": "99999.000",
            "unit_price": "1.00",
        }
        response = self.client.post(self.endpoint_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify authenticated actor is set, not spoofed actor
        self.assertEqual(response.data["submitted_by_id"], self.supplier_member.id)
        self.assertEqual(response.data["status"], OfferVersionStatus.SUBMITTED)
        # Verify draft data remains intact
        self.assertEqual(Decimal(response.data["offered_quantity"]), Decimal("500.000"))

    # -------------------------------------------------------------------------
    # 6. Organization Capability Revalidation
    # -------------------------------------------------------------------------

    def test_revoked_capability_at_submit_rejected_400(self):
        """If organization loses its Supplier capability, submission is rejected with 400."""
        self.supplier_cap.delete()

        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lacks required Supplier capability", response.data["detail"])

    # -------------------------------------------------------------------------
    # 7. RFQ Lifecycle & State Transitions
    # -------------------------------------------------------------------------

    def test_submit_transitions_published_rfq_to_collecting_offers(self):
        """Submitting first offer against Published RFQ transitions RFQ to Collecting Offers."""
        self.assertEqual(self.rfq.status, RFQStatus.PUBLISHED)

        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.COLLECTING_OFFERS)

    def test_submit_against_closed_rfq_rejected_400(self):
        """Submitting against a Closed RFQ returns 400 Bad Request."""
        self.rfq.status = RFQStatus.CLOSED
        self.rfq.save(update_fields=["status"])

        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Offers can only be submitted against Published or Collecting Offers RFQs", response.data["detail"])

    # -------------------------------------------------------------------------
    # 8. Private RFQ Invitation Lifecycle
    # -------------------------------------------------------------------------

    def test_submit_updates_private_rfq_invitation_to_responded(self):
        """Submitting offer for private RFQ transitions active invitation to RESPONDED."""
        self.rfq.visibility = RFQVisibility.PRIVATE
        self.rfq.save(update_fields=["visibility"])

        invitation = RFQInvitation.objects.create(
            rfq=self.rfq,
            organization=self.supplier_org,
            invited_by=self.buyer_user,
            status=RFQInvitationStatus.INVITED,
        )

        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, RFQInvitationStatus.RESPONDED)
        self.assertIsNotNone(invitation.responded_at)

    # -------------------------------------------------------------------------
    # 9. Response Serialization Details
    # -------------------------------------------------------------------------

    def test_response_includes_cost_components_and_aggregate_version(self):
        """Response accurately serializes cost components and current aggregate_version."""
        OfferCostComponent.objects.create(
            offer_version=self.draft,
            kind="LOGISTICS",
            amount=Decimal("25.00"),
            currency="USD",
            description="Terminal handling fee",
        )

        self.client.force_authenticate(user=self.supplier_owner)
        response = self.client.post(self.endpoint_url, {"expected_version": self.offer.aggregate_version}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.data["cost_components"]), 1)
        self.assertEqual(response.data["cost_components"][0]["kind"], "LOGISTICS")
        self.assertEqual(Decimal(response.data["cost_components"][0]["amount"]), Decimal("25.00"))
        # aggregate_version incremented to 2
        self.assertEqual(response.data["aggregate_version"], 2)
