from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from offers.enums import CostComponentKind, OfferorRole
from offers.models import OfferCostComponent
from offers.services.creation import create_offer
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.revision_service import (
    cancel_revision_request,
    create_revised_draft_offer_version,
    create_revision_request,
    decline_revision_request,
    submit_revised_offer_version,
)
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from offers.tests.base import BaseOffersTestCase
from opportunities.models import ExternalCounterparty, Opportunity, OpportunityDirection, OpportunityStatus
from organizations.models import Organization, OrganizationCapability, OrganizationMembership

User = get_user_model()


class OfferNegotiationHistoryTests(BaseOffersTestCase):
    """Authoritative test suite for Offer Negotiation History projection (T0812)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Create competitor org & user
        self.competitor_org = Organization.objects.create(
            name="Competitor Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.competitor_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.competitor_user = User.objects.create_user(
            email="competitor@competitor.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.competitor_org,
            user=self.competitor_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Create foreign buyer org & user
        self.foreign_buyer_org = Organization.objects.create(
            name="Foreign Buyer Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.foreign_buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.foreign_buyer_user = User.objects.create_user(
            email="foreign@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=self.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Standard Supplier Offer
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        # Submit V1
        self.draft_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            incoterm="FOB",
            payment_terms="LC at sight",
            delivery_terms="Bandar Abbas",
            specifications={"penetration_grade": "60/70"},
            notes="Initial proposal V1",
        )
        OfferCostComponent.objects.create(
            offer_version=self.draft_v1,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("25.00"),
            currency="USD",
            description="Freight to port",
        )
        self.offer.refresh_from_db()
        self.v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.draft_v1,
            expected_version=self.offer.aggregate_version,
        )

    def test_negotiation_history_v1_only(self):
        """V1 only: single submitted version, no revision requests."""
        self.client.force_authenticate(user=self.buyer_user)
        url = f"/api/offers/{self.offer.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["offer_id"], str(self.offer.id))
        self.assertEqual(data["counterparty_name"], self.supplier_org.name)
        self.assertFalse(data["is_external"])
        self.assertFalse(data["entered_by_operator"])
        self.assertEqual(len(data["versions"]), 1)
        self.assertEqual(data["versions"][0]["version_number"], 1)
        self.assertEqual(data["versions"][0]["unit_price"], "350.00")
        self.assertEqual(len(data["versions"][0]["cost_components"]), 1)
        self.assertEqual(len(data["revision_requests"]), 0)
        self.assertIsNotNone(data["schema"])
        self.assertEqual(len(data["schema"]["attributes"]), 1)

    def test_negotiation_history_v1_r1_v2(self):
        """V1 -> R1 (RESOLVED) -> V2 explicit relationship."""
        self.offer.refresh_from_db()
        # Buyer requests revision
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["unit_price", "payment_terms"],
            message="Please lower price to 340 and offer TT payment.",
            expected_version=self.offer.aggregate_version,
        )

        self.offer.refresh_from_db()
        # Supplier creates revised draft
        draft_v2 = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        draft_v2.unit_price = Decimal("340.00")
        draft_v2.payment_terms = "TT 30 days"
        draft_v2.notes = "Revised per request"
        draft_v2.save()

        self.offer.refresh_from_db()
        # Supplier submits V2
        v2, resolved_req = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
            draft_version=draft_v2,
        )

        self.client.force_authenticate(user=self.buyer_user)
        url = f"/api/offers/{self.offer.id}/history/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(len(data["versions"]), 2)
        self.assertEqual(data["versions"][0]["version_number"], 1)
        self.assertEqual(data["versions"][1]["version_number"], 2)
        self.assertEqual(data["versions"][1]["unit_price"], "340.00")

        self.assertEqual(len(data["revision_requests"]), 1)
        req_data = data["revision_requests"][0]
        self.assertEqual(req_data["id"], str(rev_req.id))
        self.assertEqual(req_data["status"], "RESOLVED")
        self.assertEqual(req_data["base_offer_version_id"], str(self.v1.id))
        self.assertEqual(req_data["base_version_number"], 1)
        self.assertEqual(req_data["resolved_by_version_id"], str(v2.id))
        self.assertEqual(req_data["resolved_version_number"], 2)
        self.assertEqual(req_data["requested_by_role"], "BUYER")

    def test_negotiation_history_multiple_cycles(self):
        """V1 -> R1 -> V2 -> R2 -> V3 multi-cycle negotiation."""
        self.offer.refresh_from_db()
        # Cycle 1: V1 -> R1 -> V2
        r1 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["unit_price"],
            message="Price request 1",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        draft_v2 = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=r1,
            expected_version=self.offer.aggregate_version,
        )
        draft_v2.unit_price = Decimal("340.00")
        draft_v2.save()
        self.offer.refresh_from_db()
        v2, _ = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=r1,
            expected_version=self.offer.aggregate_version,
            draft_version=draft_v2,
        )

        self.offer.refresh_from_db()
        # Cycle 2: V2 -> R2 -> V3
        r2 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=v2,
            requested_fields=["delivery_terms"],
            message="Delivery request 2",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        draft_v3 = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=r2,
            expected_version=self.offer.aggregate_version,
        )
        draft_v3.delivery_terms = "FOB Imam Khomeini Port"
        draft_v3.save()
        self.offer.refresh_from_db()
        v3, _ = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=r2,
            expected_version=self.offer.aggregate_version,
            draft_version=draft_v3,
        )

        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get(f"/api/offers/{self.offer.id}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(len(data["versions"]), 3)
        self.assertEqual(len(data["revision_requests"]), 2)
        self.assertEqual(data["revision_requests"][0]["base_version_number"], 1)
        self.assertEqual(data["revision_requests"][0]["resolved_version_number"], 2)
        self.assertEqual(data["revision_requests"][1]["base_version_number"], 2)
        self.assertEqual(data["revision_requests"][1]["resolved_version_number"], 3)

    def test_negotiation_history_open_and_terminal_requests(self):
        """History correctly presents DECLINED, CANCELLED, and OPEN requests without resolving versions."""
        self.offer.refresh_from_db()
        # 1. First request declined
        r1 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["unit_price"],
            message="Discount please",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        decline_revision_request(
            actor=self.supplier_user,
            revision_request=r1,
            expected_version=self.offer.aggregate_version,
        )

        self.offer.refresh_from_db()
        # 2. Second request cancelled
        r2 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["payment_terms"],
            message="Change terms",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        cancel_revision_request(
            actor=self.buyer_user,
            revision_request=r2,
            expected_version=self.offer.aggregate_version,
        )

        self.offer.refresh_from_db()
        # 3. Third request remains OPEN
        r3 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["delivery_terms"],
            message="Change delivery",
            expected_version=self.offer.aggregate_version,
        )

        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get(f"/api/offers/{self.offer.id}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(len(data["revision_requests"]), 3)
        self.assertEqual(data["revision_requests"][2]["id"], str(r3.id))
        self.assertEqual(data["revision_requests"][0]["status"], "DECLINED")
        self.assertIsNone(data["revision_requests"][0]["resolved_by_version_id"])
        self.assertEqual(data["revision_requests"][1]["status"], "CANCELLED")
        self.assertIsNone(data["revision_requests"][1]["resolved_by_version_id"])
        self.assertEqual(data["revision_requests"][2]["status"], "OPEN")
        self.assertIsNone(data["revision_requests"][2]["resolved_by_version_id"])

    def test_draft_privacy_isolation(self):
        """Buyer cannot see supplier's in-progress unsubmitted draft; supplier and operator can see it."""
        self.offer.refresh_from_db()
        r1 = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["unit_price"],
            message="Discount please",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=r1,
            expected_version=self.offer.aggregate_version,
        )

        # Buyer sees only SUBMITTED V1
        self.client.force_authenticate(user=self.buyer_user)
        buyer_resp = self.client.get(f"/api/offers/{self.offer.id}/history/")
        self.assertEqual(buyer_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(buyer_resp.data["versions"]), 1)
        self.assertEqual(buyer_resp.data["versions"][0]["status"], "SUBMITTED")

        # Supplier sees V1 (SUBMITTED) and V2 (DRAFT)
        self.client.force_authenticate(user=self.supplier_user)
        supplier_resp = self.client.get(f"/api/offers/{self.offer.id}/history/")
        self.assertEqual(supplier_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(supplier_resp.data["versions"]), 2)
        self.assertEqual(supplier_resp.data["versions"][0]["status"], "SUBMITTED")
        self.assertEqual(supplier_resp.data["versions"][1]["status"], "DRAFT")

        # Operator also sees V1 and V2 (DRAFT)
        self.client.force_authenticate(user=self.operator_user)
        op_resp = self.client.get(f"/api/offers/{self.offer.id}/history/")
        self.assertEqual(op_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(op_resp.data["versions"]), 2)

    def test_authorization_matrix(self):
        """Rigorous authorization verification for all actor types."""
        url = f"/api/offers/{self.offer.id}/history/"

        # 1. Unauthenticated -> 401 or 403
        self.client.logout()
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # 2. Competitor supplier -> 404
        self.client.force_authenticate(user=self.competitor_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # 3. Foreign buyer -> 404
        self.client.force_authenticate(user=self.foreign_buyer_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # 4. Staff without system role -> 404
        staff_user = User.objects.create_user(
            email="staff_no_role@platform.com",
            password="testpassword123",
            is_staff=True,
        )
        self.client.force_authenticate(user=staff_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # 5. Offering org member -> 200
        self.client.force_authenticate(user=self.supplier_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # 6. RFQ Buyer -> 200
        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # 7. Operator -> 200
        self.client.force_authenticate(user=self.operator_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_external_offer_privacy_for_buyer(self):
        """External counterparty offer shows company name, entered_by_operator=True, no CRM leak."""
        ext_party = ExternalCounterparty.objects.create(
            company_name="Gulf Petrochemicals FZE",
            geography="AE",
            phone="+971501234567",
            email="contact@gulfpetro.ae",
            notes="Private CRM notes that should not leak to buyer",
        )
        opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=ext_party,
            commodity=self.commodity,
            schema_version=self.schema_version,
            status=OpportunityStatus.QUALIFIED,
            notes="Private sourcing note: Supplier willing to discount by $5/MT.",
            created_by=self.operator_user,
        )

        ext_offer, ext_v1 = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=opp,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("360.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Commercial offer terms",
            external_counterparty=ext_party,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/{ext_offer.id}/history/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data

        self.assertEqual(data["counterparty_name"], "Gulf Petrochemicals FZE")
        self.assertTrue(data["is_external"])
        self.assertTrue(data["entered_by_operator"])
        self.assertTrue(data["versions"][0]["entered_by_operator"])
        self.assertEqual(data["versions"][0]["submitted_by_name"], "اپراتور سامانه")

        # Verify no CRM leaks in response string representation
        resp_text = str(resp.data)
        self.assertNotIn("+971501234567", resp_text)
        self.assertNotIn("contact@gulfpetro.ae", resp_text)
        self.assertNotIn("Private CRM notes", resp_text)
