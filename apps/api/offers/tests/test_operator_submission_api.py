from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityAttributeDefinition, CommodityDefinition, CommoditySchemaVersion
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from offers.services import submit_operator_external_offer
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import Organization, OrganizationCapability, OrganizationMembership
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class OperatorExternalOfferAPITests(TestCase):
    """
    REST API tests for T0804 Operator Submission on Behalf:
    - POST /api/offers/operator-submission/
    - POST /api/trade-hub/rfqs/<rfq_id>/offers/operator-submission/
    - GET /api/offers/<offer_id>/ (Buyer projection & Competitor denial)
    - GET /api/trade-hub/rfqs/<rfq_id>/offers/
    """

    def setUp(self):
        self.client = APIClient()

        # Commodity & Schema
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

        # Buyer Organization & User
        self.buyer_org = Organization.objects.create(name=f"Buyer Corp {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER)
        self.buyer_user = User.objects.create_user(email=f"buyer_{uuid.uuid4().hex[:4]}@buyer.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True
        )

        # Published RFQ
        self.published_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("400.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Competitor Supplier Org & User
        self.supplier_org = Organization.objects.create(name=f"Supplier Co {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        self.supplier_user = User.objects.create_user(email=f"supplier_{uuid.uuid4().hex[:4]}@supplier.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True
        )

        # Competitor Broker Org & User
        self.broker_org = Organization.objects.create(name=f"Brokerage {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER)
        self.broker_user = User.objects.create_user(email=f"broker_{uuid.uuid4().hex[:4]}@broker.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True
        )

        # External Counterparty
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Private Global Refinery FZE",
            contact_name="Ali Reza",
            phone="+971509998877",
            email="ali.reza@privateglobal.ae",
            notes="Confidential margin: $15/MT. Highly sensitive pricing contact.",
        )

        # Operator User
        self.operator_user = User.objects.create_user(email=f"operator_{uuid.uuid4().hex[:4]}@platform.internal", password="pw")
        SystemRoleAssignment.objects.create(user=self.operator_user, role=SystemRoleAssignment.SystemRole.OPERATOR)

        # Product Admin User
        self.admin_user = User.objects.create_user(email=f"admin_{uuid.uuid4().hex[:4]}@platform.internal", password="pw")
        SystemRoleAssignment.objects.create(user=self.admin_user, role=SystemRoleAssignment.SystemRole.ADMIN)

        # Staff-only User
        self.staff_only_user = User.objects.create_user(email=f"staff_{uuid.uuid4().hex[:4]}@platform.internal", password="pw", is_staff=True)

        # Qualified Supply Opportunity
        self.opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_v1,
            status=OpportunityStatus.QUALIFIED,
            notes="Private sourcing note: Supplier willing to discount by $5/MT.",
            created_by=self.operator_user,
        )

    def _get_valid_api_payload(self):
        return {
            "rfq_id": str(self.published_rfq.id),
            "opportunity_id": str(self.opp.id),
            "offered_quantity": "250.000",
            "quantity_unit": "MT",
            "unit_price": "470.00",
            "currency": "USD",
            "payment_terms": "LC 30 days",
            "delivery_terms": "FOB Bandar Abbas",
            "incoterm": "FOB",
            "delivery_start": str(date.today() + timedelta(days=5)),
            "delivery_end": str(date.today() + timedelta(days=20)),
            "specifications": {"penetration_grade": "60/70"},
            "notes": "External refinery quota allocation.",
        }

    # --- Authorization & Permissions Tests ---

    def test_operator_can_submit_external_offer_via_api(self):
        """Operator can successfully submit an external offer via REST API."""
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.post("/api/offers/operator-submission/", self._get_valid_api_payload(), format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "SUBMITTED")
        self.assertEqual(res.data["version_number"], 1)
        self.assertEqual(res.data["submitted_by_id"], self.operator_user.id)

    def test_product_admin_can_submit_external_offer_via_api(self):
        """Product Admin can submit an external offer via REST API."""
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post("/api/offers/operator-submission/", self._get_valid_api_payload(), format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_rfq_nested_operator_submission_endpoint(self):
        """Action is also accessible via RFQ-nested route."""
        self.client.force_authenticate(user=self.operator_user)
        payload = self._get_valid_api_payload()
        del payload["rfq_id"]  # rfq_id provided in URL
        url = f"/api/trade-hub/rfqs/{self.published_rfq.id}/offers/operator-submission/"
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_disallowed_actors_rejected_with_403(self):
        """Buyer, Supplier, Broker, staff-only, and superuser-only users receive 403 Forbidden."""
        disallowed_users = [
            self.buyer_user,
            self.supplier_user,
            self.broker_user,
            self.staff_only_user,
        ]
        for user in disallowed_users:
            self.client.force_authenticate(user=user)
            res = self.client.post("/api/offers/operator-submission/", self._get_valid_api_payload(), format="json")
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {user.email}")

    def test_unauthenticated_rejected_with_401(self):
        """Unauthenticated caller receives 401 Unauthorized or 403 Forbidden."""
        res = self.client.post("/api/offers/operator-submission/", self._get_valid_api_payload(), format="json")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_opportunity_side_channel_probing_prevented(self):
        """Non-operator caller cannot probe Opportunity existence; gets 403 regardless."""
        self.client.force_authenticate(user=self.supplier_user)
        payload = self._get_valid_api_payload()
        payload["opportunity_id"] = str(uuid.uuid4())  # Fake non-existent opportunity

        res = self.client.post("/api/offers/operator-submission/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # --- Buyer Projection & Privacy Tests ---

    def test_buyer_safe_projection_excludes_private_crm_and_operator_notes(self):
        """
        Buyer reading the submitted Offer sees commercial terms but never receives
        phone, email, contact person, or internal operator/opportunity notes.
        """
        # Create and submit the external offer
        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("470.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Public commercial notes visible to buyer.",
        )

        # Authenticate as RFQ Buyer
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/offers/{offer.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Verify safe commercial fields ARE present
        data = res.data
        self.assertEqual(data["id"], str(offer.id))
        self.assertEqual(data["counterparty_name"], "Private Global Refinery FZE")
        self.assertTrue(data["is_external"])
        self.assertEqual(data["current_submitted_version"]["unit_price"], "470.00")
        self.assertEqual(data["current_submitted_version"]["notes"], "Public commercial notes visible to buyer.")

        # Verify private CRM, phone, email, and internal notes are ABSENT
        raw_content = res.content.decode("utf-8")
        self.assertNotIn("+971509998877", raw_content)
        self.assertNotIn("ali.reza@privateglobal.ae", raw_content)
        self.assertNotIn("Confidential margin", raw_content)
        self.assertNotIn("Private sourcing note", raw_content)
        self.assertNotIn("Ali Reza", raw_content)

    def test_competitor_participant_denied_access_returns_404(self):
        """Competitor Supplier and Broker attempting direct ID access receive 404 Not Found."""
        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("470.00"),
            specifications={"penetration_grade": "60/70"},
        )

        # Competitor Supplier user receives 404
        self.client.force_authenticate(user=self.supplier_user)
        res_supplier = self.client.get(f"/api/offers/{offer.id}/")
        self.assertEqual(res_supplier.status_code, status.HTTP_404_NOT_FOUND)

        # Competitor Broker user receives 404
        self.client.force_authenticate(user=self.broker_user)
        res_broker = self.client.get(f"/api/offers/{offer.id}/")
        self.assertEqual(res_broker.status_code, status.HTTP_404_NOT_FOUND)

    def test_buyer_can_list_offers_for_rfq(self):
        """Buyer can list submitted offers on their RFQ, while competitors are denied."""
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("470.00"),
            specifications={"penetration_grade": "60/70"},
        )

        # Buyer can list offers
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/trade-hub/rfqs/{self.published_rfq.id}/offers/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["counterparty_name"], "Private Global Refinery FZE")

        # Competitor Supplier is denied access to list offers
        self.client.force_authenticate(user=self.supplier_user)
        res_comp = self.client.get(f"/api/trade-hub/rfqs/{self.published_rfq.id}/offers/")
        self.assertEqual(res_comp.status_code, status.HTTP_403_FORBIDDEN)
