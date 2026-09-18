from decimal import Decimal
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from offers.enums import (
    OfferorRole,
    RevisionRequestStatus,
)
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    StaleVersionError,
)
from offers.models import OfferVersion, RevisionRequest
from offers.services.creation import create_offer
from offers.services.decision_service import execute_decision_run_pipeline
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.policy_seed import seed_decision_profile_v1
from offers.services.revision_service import (
    cancel_revision_request,
    create_revision_request,
    decline_revision_request,
)
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from offers.tests.base import BaseOffersTestCase
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class RevisionRequestDomainTests(BaseOffersTestCase):
    """Unit and service-level tests for RevisionRequest creation, decline, and cancel (T0810)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Create an Offer for supplier_org against published_rfq
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        # Create Draft OfferVersion V1
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            notes="Initial proposal V1",
        )

        # Submit V1
        self.offer.refresh_from_db()
        self.v1_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()
        self.published_rfq.refresh_from_db()

    # --- 1. Creation Tests ---

    def test_create_revision_request_success(self):
        """Current V1 Submitted -> OPEN RevisionRequest created with valid metadata."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price", "offered_quantity"],
            message="Please provide a more competitive price for 500 MT.",
            expected_version=self.offer.aggregate_version,
        )

        self.assertIsNotNone(rev_req.pk)
        self.assertEqual(rev_req.status, RevisionRequestStatus.OPEN)
        self.assertEqual(rev_req.offer_id, self.offer.id)
        self.assertEqual(rev_req.base_offer_version_id, self.v1_submitted.id)
        self.assertEqual(rev_req.requested_fields, ["unit_price", "offered_quantity"])
        self.assertEqual(rev_req.message, "Please provide a more competitive price for 500 MT.")
        self.assertEqual(rev_req.requested_by, self.buyer_user)
        self.assertIsNotNone(rev_req.requested_at)
        self.assertIsNone(rev_req.resolved_by_version)
        self.assertIsNone(rev_req.resolved_at)

        # Offer aggregate_version incremented
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 4)

    def test_rfq_lifecycle_transition_to_negotiating(self):
        """Successful revision request moves RFQ from Collecting Offers to Negotiating."""
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)
        initial_rfq_version = self.published_rfq.version

        create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.NEGOTIATING)
        self.assertEqual(self.published_rfq.version, initial_rfq_version + 1)

    def test_rfq_already_negotiating_is_idempotent(self):
        """If RFQ is already in Negotiating, subsequent revision request succeeds without error."""
        self.published_rfq.status = RFQStatus.NEGOTIATING
        self.published_rfq.save(update_fields=["status"])

        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.assertEqual(rev_req.status, RevisionRequestStatus.OPEN)
        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.NEGOTIATING)

    def test_terminal_rfq_rejects_revision_request(self):
        """Closed, Cancelled, or Awarded RFQ rejects revision request."""
        for term_status in [RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED]:
            self.published_rfq.status = term_status
            self.published_rfq.save(update_fields=["status"])

            with self.assertRaises(OfferStateError):
                create_revision_request(
                    actor=self.buyer_user,
                    offer=self.offer,
                    base_offer_version=self.v1_submitted,
                    requested_fields=["unit_price"],
                    expected_version=self.offer.aggregate_version,
                )

    def test_stale_base_offer_version_rejected(self):
        """Current V2, request targets V1 -> reject with OfferConflictError."""
        # Create and submit V2
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.offer.refresh_from_db()
        v2_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v2,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.current_submitted_version, v2_submitted)

        # Attempt revision request against stale V1
        with self.assertRaises(OfferConflictError) as ctx:
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("stale", str(ctx.exception).lower())

    def test_stale_expected_version_rejected(self):
        """Mismatched expected_version rejected with StaleVersionError; no mutation occurs."""
        wrong_version = self.offer.aggregate_version + 5
        with self.assertRaises(StaleVersionError):
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=wrong_version,
            )
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.revision_requests.count(), 0)

    def test_invalid_expected_version_rejected(self):
        """Missing, negative, or non-integer expected_version rejected."""
        for bad_ver in [None, -1, 0, "1", 1.5, True]:
            with self.assertRaises(InvalidVersionError):
                create_revision_request(
                    actor=self.buyer_user,
                    offer=self.offer,
                    base_offer_version=self.v1_submitted,
                    requested_fields=["unit_price"],
                    expected_version=bad_ver,
                )

    def test_one_open_revision_request_enforced_service_and_db(self):
        """At most one OPEN revision request allowed per Offer."""
        # 1st request succeeds
        create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        # 2nd request while 1st is OPEN fails with OfferConflictError
        with self.assertRaises(OfferConflictError) as ctx:
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["payment_terms"],
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("open revision request already exists", str(ctx.exception).lower())

    def test_requested_fields_canonical_validation(self):
        """Validate requested_fields: duplicates, empty, non-canonical, and forbidden server fields."""
        # Empty list
        with self.assertRaises(OfferValidationError):
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=[],
                expected_version=self.offer.aggregate_version,
            )

        # Duplicate entries
        with self.assertRaises(OfferValidationError) as ctx:
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price", "unit_price"],
                expected_version=self.offer.aggregate_version,
            )
        self.assertIn("duplicate", str(ctx.exception).lower())

        # Forbidden server fields
        for forbidden in ["id", "status", "currency", "version_number", "created_at"]:
            with self.assertRaises(OfferValidationError):
                create_revision_request(
                    actor=self.buyer_user,
                    offer=self.offer,
                    base_offer_version=self.v1_submitted,
                    requested_fields=[forbidden],
                    expected_version=self.offer.aggregate_version,
                )

        # Arbitrary non-canonical strings
        with self.assertRaises(OfferValidationError):
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["custom_fake_field"],
                expected_version=self.offer.aggregate_version,
            )

    def test_base_version_commercial_immutability(self):
        """Revision request must not mutate any field on base OfferVersion."""
        v1_before = OfferVersion.objects.get(pk=self.v1_submitted.pk)

        create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price", "offered_quantity"],
            message="Revise price please.",
            expected_version=self.offer.aggregate_version,
        )

        v1_after = OfferVersion.objects.get(pk=self.v1_submitted.pk)
        self.assertEqual(v1_before.unit_price, v1_after.unit_price)
        self.assertEqual(v1_before.offered_quantity, v1_after.offered_quantity)
        self.assertEqual(v1_before.currency, v1_after.currency)
        self.assertEqual(v1_before.specifications, v1_after.specifications)
        self.assertEqual(v1_before.payment_terms, v1_after.payment_terms)
        self.assertEqual(v1_before.delivery_terms, v1_after.delivery_terms)
        self.assertEqual(v1_before.notes, v1_after.notes)
        self.assertEqual(v1_before.status, v1_after.status)

    def test_failure_atomicity(self):
        """Failed revision request rolls back request, aggregate version, and RFQ state."""
        initial_agg_ver = self.offer.aggregate_version
        initial_rfq_ver = self.published_rfq.version
        initial_rfq_status = self.published_rfq.status

        with self.assertRaises(OfferValidationError):
            create_revision_request(
                actor=self.buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["id"],  # forbidden field
                expected_version=initial_agg_ver,
            )

        self.offer.refresh_from_db()
        self.published_rfq.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, initial_agg_ver)
        self.assertEqual(self.published_rfq.version, initial_rfq_ver)
        self.assertEqual(self.published_rfq.status, initial_rfq_status)
        self.assertEqual(RevisionRequest.objects.count(), 0)

    # --- 2. Authorization Tests ---

    def test_authorization_buyer_procurement_actors_allowed(self):
        """Owner and Manager of RFQ Buyer organization are allowed to request revisions."""
        # Manager
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.assertIsNotNone(rev_req.pk)

        # Clean up for Owner test
        rev_req.status = RevisionRequestStatus.CANCELLED
        rev_req.save()
        self.offer.refresh_from_db()

        # Buyer Owner
        buyer_owner = User.objects.create_user(
            email="owner@buyer-corp.com", password="testpassword123"
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=buyer_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        rev_req2 = create_revision_request(
            actor=buyer_owner,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["payment_terms"],
            expected_version=self.offer.aggregate_version,
        )
        self.assertIsNotNone(rev_req2.pk)

    def test_authorization_buyer_member_and_viewer_denied(self):
        """Buyer Member and Viewer roles are denied creation (403)."""
        buyer_member = User.objects.create_user(
            email="member@buyer-corp.com", password="testpassword123"
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=buyer_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=buyer_member,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

        buyer_viewer = User.objects.create_user(
            email="viewer@buyer-corp.com", password="testpassword123"
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=buyer_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=buyer_viewer,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

    def test_authorization_foreign_buyer_denied(self):
        """Buyer belonging to a different organization is rejected."""
        other_buyer_org = Organization.objects.create(name="Other Buyer Inc", is_active=True)
        OrganizationCapability.objects.create(
            organization=other_buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        other_buyer_user = User.objects.create_user(
            email="other@buyer.com", password="testpassword123"
        )
        OrganizationMembership.objects.create(
            organization=other_buyer_org,
            user=other_buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=other_buyer_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

    def test_supplier_self_request_denied(self):
        """Supplier participant cannot request revision on its own offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=self.supplier_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

    def test_authorization_operator_and_product_admin_allowed(self):
        """Platform Operator and Product Admin can create revision requests."""
        rev1 = create_revision_request(
            actor=self.operator_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.assertIsNotNone(rev1.pk)

        # Cancel rev1 to test Admin
        rev1.status = RevisionRequestStatus.CANCELLED
        rev1.save()
        self.offer.refresh_from_db()

        rev2 = create_revision_request(
            actor=self.admin_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["delivery_terms"],
            expected_version=self.offer.aggregate_version,
        )
        self.assertIsNotNone(rev2.pk)

    def test_django_staff_and_superuser_without_roles_denied(self):
        """Django is_staff and is_superuser alone without SystemRoleAssignment are denied."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=self.staff_only_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

        with self.assertRaises(OfferPermissionDeniedError):
            create_revision_request(
                actor=self.superuser_only_user,
                offer=self.offer,
                base_offer_version=self.v1_submitted,
                requested_fields=["unit_price"],
                expected_version=self.offer.aggregate_version,
            )

    # --- 3. Decline Tests ---

    def test_internal_supplier_member_can_decline(self):
        """Authorized member of the offering organization can decline an open revision request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        declined = decline_revision_request(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )

        self.assertEqual(declined.status, RevisionRequestStatus.DECLINED)
        self.assertIsNotNone(declined.resolved_at)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 5)

    def test_buyer_denied_decline(self):
        """Buyer procurement actor cannot decline revision requests."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        with self.assertRaises(OfferPermissionDeniedError):
            decline_revision_request(
                actor=self.buyer_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )

    def test_operator_can_decline_for_external_counterparty(self):
        """Operator can decline revision request on behalf of external counterparty."""
        # Create external offer via operator
        ext_offer, ext_v1 = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        # Open revision request by buyer
        ext_rev = create_revision_request(
            actor=self.buyer_user,
            offer=ext_offer,
            base_offer_version=ext_v1,
            requested_fields=["unit_price"],
            expected_version=ext_offer.aggregate_version,
        )
        ext_offer.refresh_from_db()

        # Decline by operator
        declined = decline_revision_request(
            actor=self.operator_user,
            revision_request=ext_rev,
            expected_version=ext_offer.aggregate_version,
        )
        self.assertEqual(declined.status, RevisionRequestStatus.DECLINED)

    # --- 4. Cancel Tests ---

    def test_buyer_can_cancel_revision_request(self):
        """Buyer procurement actor can cancel open revision request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        cancelled = cancel_revision_request(
            actor=self.buyer_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )

        self.assertEqual(cancelled.status, RevisionRequestStatus.CANCELLED)
        self.assertIsNotNone(cancelled.resolved_at)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 5)

    def test_supplier_denied_cancel(self):
        """Offer participant (supplier) cannot cancel Buyer's revision request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        with self.assertRaises(OfferPermissionDeniedError):
            cancel_revision_request(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )

    # --- 5. Terminal Immutability Tests ---

    def test_terminal_immutability_cannot_reopen_or_mutate(self):
        """Once DECLINED or CANCELLED, normal mutation or status change is forbidden."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        # Decline the request
        decline_revision_request(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        rev_req.refresh_from_db()

        # Attempt to cancel an already declined request
        with self.assertRaises(OfferConflictError):
            cancel_revision_request(
                actor=self.buyer_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )

        # Attempt to decline again
        with self.assertRaises(OfferConflictError):
            decline_revision_request(
                actor=self.supplier_user,
                revision_request=rev_req,
                expected_version=self.offer.aggregate_version,
            )


class RevisionRequestAPITests(BaseOffersTestCase):
    """API endpoint tests for POST /offers/{id}/revision-requests/, decline, cancel, and detail."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Offer & V1 submitted
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        # Submit V1
        self.offer.refresh_from_db()
        self.v1_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()

    def test_post_create_revision_request_api(self):
        """POST /api/offers/{offer_id}/revision-requests/ creates OPEN request."""
        self.client.force_authenticate(user=self.buyer_user)
        payload = {
            "expected_version": self.offer.aggregate_version,
            "base_offer_version": str(self.v1_submitted.id),
            "requested_fields": ["unit_price", "notes"],
            "message": "Negotiation message from Buyer.",
        }
        response = self.client.post(
            f"/api/offers/{self.offer.id}/revision-requests/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data
        self.assertEqual(data["status"], "OPEN")
        self.assertEqual(data["offer_id"], str(self.offer.id))
        self.assertEqual(data["base_offer_version_id"], str(self.v1_submitted.id))
        self.assertEqual(data["requested_fields"], ["unit_price", "notes"])
        self.assertEqual(data["message"], "Negotiation message from Buyer.")
        self.assertEqual(data["requested_by_id"], str(self.buyer_user.id))
        self.assertEqual(data["offer_aggregate_version"], 4)

    def test_actor_spoofing_prevented_by_server(self):
        """Client-provided requested_by, requested_at, status are ignored/overridden."""
        self.client.force_authenticate(user=self.buyer_user)
        payload = {
            "expected_version": self.offer.aggregate_version,
            "base_offer_version": str(self.v1_submitted.id),
            "requested_fields": ["unit_price"],
            "status": "RESOLVED",  # Attempt to spoof
            "requested_by_id": str(uuid.uuid4()),  # Attempt to spoof
        }
        response = self.client.post(
            f"/api/offers/{self.offer.id}/revision-requests/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "OPEN")
        self.assertEqual(response.data["requested_by_id"], str(self.buyer_user.id))

    def test_post_decline_api(self):
        """POST /api/revision-requests/{id}/decline/ declines OPEN request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        self.client.force_authenticate(user=self.supplier_user)
        payload = {"expected_version": self.offer.aggregate_version}
        response = self.client.post(
            f"/api/revision-requests/{rev_req.id}/decline/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "DECLINED")
        self.assertIsNotNone(response.data["resolved_at"])

    def test_post_cancel_api(self):
        """POST /api/revision-requests/{id}/cancel/ cancels OPEN request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

        self.client.force_authenticate(user=self.buyer_user)
        payload = {"expected_version": self.offer.aggregate_version}
        response = self.client.post(
            f"/api/revision-requests/{rev_req.id}/cancel/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "CANCELLED")
        self.assertIsNotNone(response.data["resolved_at"])

    def test_competitor_participant_privacy(self):
        """Competitor supplier receives 404 Not Found for another party's revision request."""
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1_submitted,
            requested_fields=["unit_price"],
            expected_version=self.offer.aggregate_version,
        )

        # Competitor (broker_user)
        self.client.force_authenticate(user=self.broker_user)

        # List
        res_list = self.client.get(f"/api/offers/{self.offer.id}/revision-requests/")
        self.assertEqual(res_list.status_code, status.HTTP_404_NOT_FOUND)

        # Detail
        res_detail = self.client.get(f"/api/revision-requests/{rev_req.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_404_NOT_FOUND)

        # Decline
        res_decline = self.client.post(
            f"/api/revision-requests/{rev_req.id}/decline/",
            {"expected_version": self.offer.aggregate_version},
            format="json",
        )
        self.assertEqual(res_decline.status_code, status.HTTP_404_NOT_FOUND)

    def test_external_offer_privacy_no_crm_leak(self):
        """Revision request response for external offer does not expose Opportunity CRM fields."""
        ext_offer, ext_v1 = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        ext_rev = create_revision_request(
            actor=self.buyer_user,
            offer=ext_offer,
            base_offer_version=ext_v1,
            requested_fields=["unit_price"],
            expected_version=ext_offer.aggregate_version,
        )

        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/revision-requests/{ext_rev.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Check no phone, email, contact_name leaked in response
        data_str = str(res.data)
        self.assertNotIn("farhad@gulfbitumen.ae", data_str)
        self.assertNotIn("+971501234567", data_str)
        self.assertNotIn("Farhad Khan", data_str)

    def test_decision_run_does_not_auto_create_revision_requests(self):
        """DecisionRun execution never automatically triggers or creates RevisionRequests."""
        initial_count = RevisionRequest.objects.count()

        # Seed profile and run pipeline
        profile_version = seed_decision_profile_v1()
        execute_decision_run_pipeline(
            self.published_rfq,
            actor=self.buyer_user,
            profile_version=profile_version,
        )

        after_count = RevisionRequest.objects.count()
        self.assertEqual(initial_count, after_count)


class RevisionRequestConcurrencyPostgreSQLTests(TransactionTestCase):
    """
    Multi-threaded concurrency tests using real PostgreSQL connections (T0810).
    Verifies race-condition semantics and authoritative ordering.
    """

    def setUp(self):
        super().setUp()
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_conc_{uuid.uuid4().hex[:6]}",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_version,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.schema_version, activate=True)

        self.buyer_org = Organization.objects.create(name=f"Buyer Corp {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER)
        self.buyer_user1 = User.objects.create_user(email=f"b1_{uuid.uuid4().hex[:4]}@buyer.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.buyer_org, user=self.buyer_user1, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True)
        self.buyer_user2 = User.objects.create_user(email=f"b2_{uuid.uuid4().hex[:4]}@buyer.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.buyer_org, user=self.buyer_user2, role=OrganizationMembership.OrganizationRole.OWNER, is_active=True)

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user1,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        self.supplier_org = Organization.objects.create(name=f"Supplier {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        self.supplier_user = User.objects.create_user(email=f"s_{uuid.uuid4().hex[:4]}@supplier.com", password="testpassword123")
        OrganizationMembership.objects.create(organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True)

        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        # Submit V1
        self.offer.refresh_from_db()
        self.v1_submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1,
            expected_version=self.offer.aggregate_version,
            require_expected_version=True,
        )
        self.offer.refresh_from_db()

    def test_concurrent_request_vs_request_exactly_one_succeeds(self):
        """
        Race — Request vs Request:
        Two concurrent threads on separate PostgreSQL connections attempt to create an OPEN
        RevisionRequest for the same Offer with the same expected_version.
        Exactly one succeeds; the second receives controlled conflict/stale error.
        Persisted OPEN requests must equal exactly 1.
        """
        barrier = threading.Barrier(2)
        results = {}

        def request_worker(thread_id, actor):
            connection.close()  # Separate thread connection
            try:
                barrier.wait()
                rev = create_revision_request(
                    actor=actor,
                    offer=self.offer.id,
                    base_offer_version=self.v1_submitted.id,
                    requested_fields=["unit_price"],
                    message=f"Request from thread {thread_id}",
                    expected_version=self.offer.aggregate_version,
                )
                results[thread_id] = ("SUCCESS", rev.id)
            except (OfferConflictError, StaleVersionError) as exc:
                results[thread_id] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results[thread_id] = ("ERROR", str(exc))
            finally:
                connection.close()

        t1 = threading.Thread(target=request_worker, args=(1, self.buyer_user1))
        t2 = threading.Thread(target=request_worker, args=(2, self.buyer_user2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [v for v in results.values() if v[0] == "SUCCESS"]
        conflicts = [v for v in results.values() if v[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got: {results}")
        self.assertEqual(len(conflicts), 1, f"Expected exactly 1 conflict, got: {results}")

        # Invariant: exactly 1 OPEN request persisted in database
        open_count = RevisionRequest.objects.filter(
            offer=self.offer, status=RevisionRequestStatus.OPEN
        ).count()
        self.assertEqual(open_count, 1)

    def test_concurrent_request_vs_new_version_authoritative_ordering(self):
        """
        Race — Request vs New Version:
        Thread A: Request revision against V1.
        Thread B: Submit V2.
        Both serialized under strict lock ordering.
        Must never end with an OPEN request whose base was already stale at commit.
        """
        # Create Draft V2 first
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("600.000"),
            quantity_unit="MT",
            unit_price=Decimal("330.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.offer.refresh_from_db()
        barrier = threading.Barrier(2)
        results = {}

        def revision_worker():
            connection.close()
            try:
                barrier.wait()
                rev = create_revision_request(
                    actor=self.buyer_user1,
                    offer=self.offer.id,
                    base_offer_version=self.v1_submitted.id,
                    requested_fields=["unit_price"],
                    expected_version=self.offer.aggregate_version,
                )
                results["REVISION"] = ("SUCCESS", rev.id)
            except (OfferConflictError, StaleVersionError, OfferStateError) as exc:
                results["REVISION"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["REVISION"] = ("ERROR", str(exc))
            finally:
                connection.close()

        def submission_worker():
            connection.close()
            try:
                barrier.wait()
                v2_sub = submit_internal_offer_version(
                    actor=self.supplier_user,
                    offer_version=v2.id,
                    expected_version=self.offer.aggregate_version,
                    require_expected_version=True,
                )
                results["SUBMISSION"] = ("SUCCESS", v2_sub.id)
            except (OfferConflictError, StaleVersionError, OfferStateError) as exc:
                results["SUBMISSION"] = ("CONFLICT", type(exc).__name__)
            except Exception as exc:
                results["SUBMISSION"] = ("ERROR", str(exc))
            finally:
                connection.close()

        t_rev = threading.Thread(target=revision_worker)
        t_sub = threading.Thread(target=submission_worker)

        t_rev.start()
        t_sub.start()
        t_rev.join()
        t_sub.join()

        self.offer.refresh_from_db()
        # Verify invariant: if revision succeeded, its base was V1 and current at its commit
        # If submission succeeded first, revision must have failed with CONFLICT or STALE
        open_rev = RevisionRequest.objects.filter(
            offer=self.offer, status=RevisionRequestStatus.OPEN
        ).first()

        if open_rev:
            # If an OPEN request exists, its base must equal the current submitted version
            # or the revision succeeded before V2 submission
            self.assertEqual(open_rev.base_offer_version_id, self.v1_submitted.id)
            # And V2 submission must have received CONFLICT or STALE
            self.assertEqual(results["SUBMISSION"][0], "CONFLICT")
        else:
            # If revision failed, submission succeeded
            self.assertEqual(results["SUBMISSION"][0], "SUCCESS")
            self.assertEqual(results["REVISION"][0], "CONFLICT")
