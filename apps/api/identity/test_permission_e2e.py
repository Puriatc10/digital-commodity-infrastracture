"""
T1306 — Permission E2E Tests (P0 Validation Suite).

Validates authoritative server-side authorization boundaries, controlled transparency,
cross-organization direct-ID attack isolation, demo persona switcher integration,
and negative product system role invariants across Buyer, Supplier, Broker, Operator,
and Anonymous actors (Epic 13 Contract §17-§20; Roadmap §1563).
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityDefinition,
    CommoditySchemaVersion,
)
from deals.models import (
    DealAttribution,
    DealAttributionStatus,
)
from deals.services.materialization import materialize_deals_from_award
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
)
from identity.seed_hero import seed_hero_scenario
from offers.enums import OfferorRole
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    create_offer,
    create_revised_draft_offer_version,
    create_revision_request,
    finalize_award,
    submit_internal_offer_version,
    submit_operator_external_offer,
)
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQVisibility
from trade_hub.services.rfq_lifecycle import RFQLifecycleService
from trade_hub.services.rfq_service import RFQService

User = get_user_model()


@override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
class BasePermissionE2ETestCase(TestCase):
    """
    Shared test fixture establishing realistic multi-organization topology
    and canonical Demo personas for Buyer, Supplier, Broker, and Operator.
    """

    @classmethod
    def setUpTestData(cls):
        # 1. Seed canonical Hero Scenario foundation (prerequisites, personas, bitumen 60/70)
        seed_hero_scenario()

        # 2. Retrieve canonical personas from seed
        cls.buyer_user = User.objects.get(email="buyer@demo.local")
        cls.buyer_org = Organization.objects.get(name="Demo Buyer Corp")

        cls.supplier_user = User.objects.get(email="supplier@demo.local")
        cls.supplier_org = Organization.objects.get(name="Demo Supplier LLC")

        cls.supplier2_user = User.objects.get(email="supplier.isfahan@demo.local")
        cls.supplier2_org = Organization.objects.get(name="Isfahan Bitumen Refining Co.")

        cls.broker_user = User.objects.get(email="broker@demo.local")
        cls.broker_org = Organization.objects.get(name="Demo Brokerage")

        cls.operator_user = User.objects.get(email="operator@demo.local")
        cls.admin_user = User.objects.get(email="admin@demo.local")

        # 3. Create independent second Buyer Organization and User (Buyer B)
        cls.buyer_b_org = Organization.objects.create(
            name="Zagros Asphalt Buyer Ltd",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.buyer_b_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        cls.buyer_b_user = User.objects.create_user(
            email="buyer.zagros.indep@demo.local",
            password="testpassword123",
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=cls.buyer_b_org,
            user=cls.buyer_b_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # 4. Create second Broker Organization and User (Broker B)
        cls.broker_b_org = Organization.objects.create(
            name="Silk Road Brokerage Co",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.broker_b_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        cls.broker_b_user = User.objects.create_user(
            email="broker.silkroad.indep@demo.local",
            password="testpassword123",
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=cls.broker_b_org,
            user=cls.broker_b_user,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # 5. Non-role users for negative regression tests
        cls.staff_only_user = User.objects.create_user(
            email="staff.no.role@platform.test",
            password="testpassword123",
            is_staff=True,
            is_active=True,
        )
        cls.superuser_only_user = User.objects.create_superuser(
            email="superuser.no.role@platform.test",
            password="testpassword123",
            is_active=True,
        )

        # 6. Resolve commodity and schema
        cls.bitumen = CommodityDefinition.objects.get(code="bitumen")
        cls.bitumen_schema = CommoditySchemaVersion.objects.filter(
            commodity=cls.bitumen, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
        ).order_by("-version").first()

        # 7. Seed Bitumen Workflow v1 for execution tests
        cls.bitumen_wf_v1 = seed_bitumen_workflow_v1(actor=cls.operator_user)

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def get_csrf_headers(self):
        self.client.get("/api/auth/csrf")
        csrftoken = self.client.cookies.get("csrftoken")
        return {"HTTP_X_CSRFTOKEN": csrftoken.value} if csrftoken else {}

    def create_sample_rfq(self, buyer_user, buyer_org, visibility=RFQVisibility.PUBLIC, is_published=True):
        """Helper to create and optionally publish an RFQ."""
        rfq = RFQService.create_draft(
            user=buyer_user,
            data={
                "commodity_id": self.bitumen.id,
                "schema_version_id": self.bitumen_schema.id,
                "specifications": {"penetration_grade": "60/70"},
                "quantity": Decimal("500.000"),
                "unit": "MT",
                "target_price": Decimal("380.00"),
                "currency": "USD",
                "payment_terms": "LC 30 Days",
                "incoterm": "FOB",
                "origin": "Iran",
                "destination": "Bandar Abbas",
                "delivery_window_start": date(2026, 11, 1),
                "delivery_window_end": date(2026, 11, 30),
                "submission_deadline": timezone.now() + timedelta(days=30),
                "inspection_required": True,
                "visibility": visibility,
                "notes": "Test RFQ Notes",
                "internal_notes": "Confidential Buyer Internal Notes",
            },
            organization_hint=buyer_org.id,
        )
        if is_published:
            rfq = RFQLifecycleService.publish(rfq.id, expected_version=rfq.version, actor=buyer_user)
        return rfq

    def create_sample_offer(self, rfq, supplier_user, supplier_org, unit_price=Decimal("370.00"), is_submitted=True):
        """Helper to create an offer with version."""
        offer = create_offer(
            actor=supplier_user,
            rfq=rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=supplier_org,
        )
        draft = create_draft_offer_version(
            actor=supplier_user,
            offer=offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=unit_price,
            currency="USD",
            incoterm="FOB",
            payment_terms="LC 30 Days",
            delivery_terms="Bandar Abbas",
            specifications={"penetration_grade": "60/70"},
            notes="Commercial proposal",
        )
        if is_submitted:
            offer.refresh_from_db()
            v = submit_internal_offer_version(
                actor=supplier_user,
                offer_version=draft,
                expected_version=offer.aggregate_version,
            )
            offer.refresh_from_db()
            return offer, v
        return offer, draft

    def create_sample_finalized_deal(self, buyer_user, buyer_org, supplier_user, supplier_org):
        """Helper to create a fully finalized Award and materialized Deal."""
        rfq = self.create_sample_rfq(buyer_user, buyer_org, is_published=True)
        offer, version = self.create_sample_offer(rfq, supplier_user, supplier_org, is_submitted=True)

        award = create_draft_award(rfq.id, actor=buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=version.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=buyer_user,
        )
        award.refresh_from_db()
        final_award = finalize_award(award.id, expected_version=award.version, actor=buyer_user)
        deals, _ = materialize_deals_from_award(final_award.id, actor=buyer_user)
        return deals[0], rfq, offer


class DemoPersonaSwitcherE2ETests(BasePermissionE2ETestCase):
    """
    Validates Demo Persona Switcher HTTP endpoint, session establishment,
    CSRF enforcement, and flag-gated isolation.
    """

    def test_persona_switch_flow_across_all_roles(self):
        """Prove demo-switch establishes valid authenticated sessions for all 5 demo personas."""
        personas = [
            ("buyer", "buyer@demo.local", "buyer"),
            ("supplier", "supplier@demo.local", "supplier"),
            ("broker", "broker@demo.local", "broker"),
            ("operator", "operator@demo.local", None),
            ("admin", "admin@demo.local", None),
        ]

        for persona_code, expected_email, expected_cap in personas:
            with self.subTest(persona=persona_code):
                headers = self.get_csrf_headers()
                res = self.client.post(
                    "/api/auth/demo-switch",
                    {"persona": persona_code},
                    format="json",
                    **headers,
                )
                self.assertEqual(res.status_code, status.HTTP_200_OK)
                self.assertEqual(res.data["email"], expected_email)

                # Verify MeView returns matching authoritative context
                me_res = self.client.get("/api/auth/me")
                self.assertEqual(me_res.status_code, status.HTTP_200_OK)
                self.assertEqual(me_res.data["email"], expected_email)

                if expected_cap:
                    caps = [
                        c
                        for org_ctx in me_res.data["organizations"]
                        for c in org_ctx["capabilities"]
                    ]
                    self.assertIn(expected_cap, caps)

                if persona_code in ["operator", "admin"]:
                    self.assertIn(persona_code, me_res.data["system_roles"])

    def test_persona_switch_requires_csrf(self):
        """Mutating demo-switch without CSRF token is rejected with 403 Forbidden."""
        client_no_csrf = APIClient(enforce_csrf_checks=True)
        res = client_no_csrf.post(
            "/api/auth/demo-switch",
            {"persona": "buyer"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=False)
    def test_persona_switch_disabled_returns_404(self):
        """When DEMO_PERSONA_SWITCHER_ENABLED is False, switcher endpoints return 404."""
        headers = self.get_csrf_headers()
        res_get = self.client.get("/api/auth/demo-switch")
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        res_post = self.client.post(
            "/api/auth/demo-switch",
            {"persona": "buyer"},
            format="json",
            **headers,
        )
        self.assertEqual(res_post.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_persona_name_rejected(self):
        """Invalid persona choice returns 400 Bad Request."""
        headers = self.get_csrf_headers()
        res = self.client.post(
            "/api/auth/demo-switch",
            {"persona": "trader"},  # Trader is strictly prohibited
            format="json",
            **headers,
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class BuyerPersonaPermissionE2ETests(BasePermissionE2ETestCase):
    """
    Validates Buyer authorization scope:
    - Allowed: procurement workflows, owned RFQ builder projection, offer comparison,
      revision requests, award flow, owned deals.
    - Denied: competitor supplier unsubmitted drafts, external counterparty CRM data,
      operator verification queue & desk, cross-organization buyer RFQs and deals.
    """

    def test_buyer_can_create_and_manage_own_rfq_draft(self):
        """Buyer can create draft RFQ, view in Builder projection with internal notes, and update."""
        self.client.force_authenticate(user=self.buyer_user)

        # 1. Create draft RFQ
        payload = {
            "commodity_id": str(self.bitumen.id),
            "schema_version_id": str(self.bitumen_schema.id),
            "specifications": {"penetration_grade": "60/70"},
            "quantity": "250.000",
            "unit": "MT",
            "target_price": "360.00",
            "currency": "USD",
            "payment_terms": "LC 30 Days",
            "incoterm": "FOB",
            "origin": "Iran",
            "destination": "Bandar Abbas",
            "delivery_window_start": "2026-11-01",
            "delivery_window_end": "2026-11-30",
            "submission_deadline": (timezone.now() + timedelta(days=20)).isoformat(),
            "visibility": "public",
            "notes": "Confidential Buyer Target",
        }
        res_create = self.client.post("/api/trade-hub/rfqs/", payload, format="json")
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        rfq_id = res_create.data["id"]

        # 2. Retrieve owned RFQ detail: Builder projection includes notes
        res_get = self.client.get(f"/api/trade-hub/rfqs/{rfq_id}/")
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(res_get.data["notes"], "Confidential Buyer Target")
        self.assertEqual(res_get.data["organization"]["id"], str(self.buyer_org.id))

        # 3. Update owned draft RFQ
        res_patch = self.client.patch(
            f"/api/trade-hub/rfqs/{rfq_id}/",
            {"target_price": "365.00", "expected_version": res_get.data["version"]},
            format="json",
        )
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch.data["target_price"], "365.00")

    def test_buyer_can_view_comparison_and_negotiation_history(self):
        """Buyer can view commercial comparison and offer negotiation history on owned RFQ."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        offer1, v1 = self.create_sample_offer(rfq, self.supplier_user, self.supplier_org, unit_price=Decimal("370.00"))
        offer2, v2 = self.create_sample_offer(rfq, self.supplier2_user, self.supplier2_org, unit_price=Decimal("365.00"))

        self.client.force_authenticate(user=self.buyer_user)

        # 1. Commercial comparison endpoint
        res_comp = self.client.get(f"/api/offers/rfqs/{rfq.id}/comparison/")
        self.assertEqual(res_comp.status_code, status.HTTP_200_OK)
        self.assertIn("items", res_comp.data)
        self.assertEqual(len(res_comp.data["items"]), 2)

        # 2. Offer negotiation history
        res_hist = self.client.get(f"/api/offers/{offer1.id}/history/")
        self.assertEqual(res_hist.status_code, status.HTTP_200_OK)
        self.assertEqual(res_hist.data["offer_id"], str(offer1.id))
        self.assertEqual(res_hist.data["counterparty_name"], self.supplier_org.name)
        self.assertEqual(len(res_hist.data["versions"]), 1)

    def test_buyer_can_request_revision_and_complete_award(self):
        """Buyer can request offer revision and execute complete award lifecycle."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        offer, v1 = self.create_sample_offer(rfq, self.supplier_user, self.supplier_org, unit_price=Decimal("375.00"))

        self.client.force_authenticate(user=self.buyer_user)

        # 1. Request revision
        res_rev = self.client.post(
            f"/api/offers/{offer.id}/revision-requests/",
            {
                "base_offer_version": str(v1.id),
                "requested_fields": ["unit_price"],
                "message": "Target is 365 USD",
                "expected_version": offer.aggregate_version,
            },
            format="json",
        )
        self.assertEqual(res_rev.status_code, status.HTTP_201_CREATED)

        # 2. Create draft award
        res_award = self.client.post(f"/api/rfqs/{rfq.id}/awards/", {}, format="json")
        self.assertEqual(res_award.status_code, status.HTTP_201_CREATED)
        award_id = res_award.data["id"]

        # 3. Add allocation
        res_alloc = self.client.post(
            f"/api/awards/{award_id}/allocations/",
            {
                "offer_version_id": str(v1.id),
                "awarded_quantity": "500.000",
                "quantity_unit": "MT",
                "expected_version": res_award.data["version"],
            },
            format="json",
        )
        self.assertEqual(res_alloc.status_code, status.HTTP_201_CREATED)

        # 4. Finalize award with updated aggregate version
        res_award_latest = self.client.get(f"/api/awards/{award_id}/")
        self.assertEqual(res_award_latest.status_code, status.HTTP_200_OK)

        res_final = self.client.post(
            f"/api/awards/{award_id}/finalize/",
            {"expected_version": res_award_latest.data["version"]},
            format="json",
        )
        self.assertEqual(res_final.status_code, status.HTTP_200_OK)
        self.assertEqual(res_final.data["status"], "FINALIZED")

    def test_buyer_can_access_own_deals(self):
        """Buyer can list and retrieve own materialized Deals."""
        deal, rfq, offer = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )

        self.client.force_authenticate(user=self.buyer_user)

        # List contains owned deal
        res_list = self.client.get("/api/deals/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        deal_ids = [d["id"] for d in res_list.data]
        self.assertIn(str(deal.id), deal_ids)

        # Detail returns 200
        res_detail = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data["id"], str(deal.id))

    def test_buyer_denied_supplier_unsubmitted_draft_versions(self):
        """Buyer cannot see supplier's in-progress unsubmitted draft version in negotiation history."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        offer, v1 = self.create_sample_offer(rfq, self.supplier_user, self.supplier_org, is_submitted=True)

        # Supplier creates revised draft but does NOT submit it
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=offer,
            base_offer_version=v1,
            requested_fields=["unit_price"],
            message="Discount please",
            expected_version=offer.aggregate_version,
        )
        offer.refresh_from_db()
        create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=offer.aggregate_version,
        )

        # Buyer inspects negotiation history: sees ONLY submitted v1
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/offers/{offer.id}/history/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["versions"]), 1)
        self.assertEqual(res.data["versions"][0]["status"], "SUBMITTED")

    def test_buyer_denied_external_counterparty_crm_details(self):
        """Controlled transparency: external counterparty CRM phone/email/notes never leak to Buyer."""
        ext_party = ExternalCounterparty.objects.create(
            company_name="Confidential Middle East Refining",
            geography="AE",
            phone="+971559876543",
            email="direct.sales@confidential.ae",
            notes="Private sourcing strategy: 15% margin threshold.",
        )
        opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=ext_party,
            commodity=self.bitumen,
            schema_version=self.bitumen_schema,
            status=OpportunityStatus.QUALIFIED,
            notes="Operator sourcing note",
            created_by=self.operator_user,
        )
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        ext_offer, ext_v1 = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=rfq,
            opportunity=opp,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Operator submitted commercial terms",
            external_counterparty=ext_party,
        )

        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/offers/{ext_offer.id}/history/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        resp_str = str(res.data)
        self.assertNotIn("+971559876543", resp_str)
        self.assertNotIn("direct.sales@confidential.ae", resp_str)
        self.assertNotIn("Private sourcing strategy", resp_str)

    def test_buyer_denied_operator_internal_surfaces(self):
        """Buyer cannot access Operator verification queue, desk endpoints, or attribution resolution."""
        self.client.force_authenticate(user=self.buyer_user)

        # 1. Verification queue
        res_verif = self.client.get("/api/organizations/verification/cases/")
        self.assertEqual(res_verif.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Opportunity external counterparty management
        res_cp = self.client.post(
            "/api/opportunities/external-counterparties/",
            {"company_name": "Forbidden Sourcing Corp"},
            format="json",
        )
        self.assertEqual(res_cp.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Opportunity desk list/create
        res_opp = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res_opp.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Deal attribution resolution
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        res_attr = self.client.post(
            f"/api/deals/{deal.id}/attribution/resolve/",
            {"primary_channel": "PLATFORM_NETWORK", "reason": "Buyer tampering"},
            format="json",
        )
        self.assertEqual(res_attr.status_code, status.HTTP_403_FORBIDDEN)

    def test_buyer_denied_cross_organization_direct_id_rfq_and_deal(self):
        """Horizontal isolation: Buyer A cannot access Buyer B's draft RFQ (404) or Deal (403)."""
        # Buyer B creates a private draft RFQ and has a Deal
        buyer_b_draft = self.create_sample_rfq(self.buyer_b_user, self.buyer_b_org, is_published=False)
        buyer_b_deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_b_user, self.buyer_b_org, self.supplier_user, self.supplier_org
        )

        self.client.force_authenticate(user=self.buyer_user)

        # 1. Buyer A direct ID GET on Buyer B draft RFQ -> 404 Not Found
        res_rfq_get = self.client.get(f"/api/trade-hub/rfqs/{buyer_b_draft.id}/")
        self.assertEqual(res_rfq_get.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Buyer A direct ID PATCH on Buyer B draft RFQ -> 403 Forbidden
        res_rfq_patch = self.client.patch(
            f"/api/trade-hub/rfqs/{buyer_b_draft.id}/",
            {"target_price": "340.00", "expected_version": buyer_b_draft.version},
            format="json",
        )
        self.assertEqual(res_rfq_patch.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Buyer A direct ID GET on Buyer B Deal -> 403 Forbidden
        res_deal_get = self.client.get(f"/api/deals/{buyer_b_deal.id}/")
        self.assertEqual(res_deal_get.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Buyer B Deal excluded from Buyer A Deal list
        res_deal_list = self.client.get("/api/deals/")
        deal_ids = [d["id"] for d in res_deal_list.data]
        self.assertNotIn(str(buyer_b_deal.id), deal_ids)


class SupplierPersonaPermissionE2ETests(BasePermissionE2ETestCase):
    """
    Validates Supplier authorization scope:
    - Allowed: public RFQ discovery, submit offer & version, view own negotiation history,
      view own deal where participating seller.
    - Denied: competitor supplier offers (404), comparison table (403), decision runs (403),
      award action (403), buyer internal notes on RFQ, operator internal surfaces.
    """

    def test_supplier_can_view_published_rfq_in_safe_public_projection(self):
        """Supplier receives safe Public projection of published RFQ; internal_notes omitted."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)

        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get(f"/api/trade-hub/rfqs/{rfq.id}/")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], str(rfq.id))
        self.assertEqual(res.data["commodity_code"], "bitumen")
        # Internal notes are strictly excluded in RFQPublicResponseSerializer
        self.assertNotIn("internal_notes", res.data)

    def test_supplier_can_manage_own_offers_and_negotiation_history(self):
        """Supplier can submit offers and see own versions in negotiation history (including drafts)."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        offer, v1 = self.create_sample_offer(rfq, self.supplier_user, self.supplier_org, unit_price=Decimal("370.00"))

        # Create unsubmitted revised draft
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=offer,
            base_offer_version=v1,
            requested_fields=["unit_price"],
            message="Discount needed",
            expected_version=offer.aggregate_version,
        )
        offer.refresh_from_db()
        create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=offer.aggregate_version,
        )

        self.client.force_authenticate(user=self.supplier_user)

        # Supplier sees own offer detail
        res_detail = self.client.get(f"/api/offers/{offer.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)

        # Supplier sees both submitted and draft version in own history
        res_hist = self.client.get(f"/api/offers/{offer.id}/history/")
        self.assertEqual(res_hist.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_hist.data["versions"]), 2)
        version_statuses = {v["status"] for v in res_hist.data["versions"]}
        self.assertIn("SUBMITTED", version_statuses)
        self.assertIn("DRAFT", version_statuses)

    def test_supplier_can_access_own_deal_when_seller(self):
        """Supplier can list and retrieve Deals where its organization is the seller."""
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )

        self.client.force_authenticate(user=self.supplier_user)

        res_list = self.client.get("/api/deals/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        deal_ids = [d["id"] for d in res_list.data]
        self.assertIn(str(deal.id), deal_ids)

        res_detail = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)

    def test_supplier_cannot_see_competitor_offers_or_history(self):
        """Supplier A attempting direct ID access to Supplier B's offer receives 404 Not Found."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        competitor_offer, _ = self.create_sample_offer(
            rfq, self.supplier2_user, self.supplier2_org, unit_price=Decimal("360.00")
        )

        self.client.force_authenticate(user=self.supplier_user)

        # Direct GET on competitor offer detail -> 404 Not Found
        res_offer = self.client.get(f"/api/offers/{competitor_offer.id}/")
        self.assertEqual(res_offer.status_code, status.HTTP_404_NOT_FOUND)

        # Direct GET on competitor offer history -> 404 Not Found
        res_hist = self.client.get(f"/api/offers/{competitor_offer.id}/history/")
        self.assertEqual(res_hist.status_code, status.HTTP_404_NOT_FOUND)

    def test_supplier_cannot_access_buyer_commercial_intelligence_or_award(self):
        """Supplier cannot access comparison table (403), decision runs (403), or award APIs (403)."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)

        self.client.force_authenticate(user=self.supplier_user)

        # 1. Commercial comparison table
        res_comp = self.client.get(f"/api/offers/rfqs/{rfq.id}/comparison/")
        self.assertEqual(res_comp.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Decision run execution
        res_dec = self.client.post(f"/api/offers/rfqs/{rfq.id}/decision-runs/", {}, format="json")
        self.assertEqual(res_dec.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Award creation
        res_award = self.client.post(f"/api/rfqs/{rfq.id}/awards/", {}, format="json")
        self.assertEqual(res_award.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_cannot_access_unrelated_deals(self):
        """Supplier cannot access Deals where it is neither buyer nor seller (403 Forbidden)."""
        unrelated_deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_b_user, self.buyer_b_org, self.supplier2_user, self.supplier2_org
        )

        self.client.force_authenticate(user=self.supplier_user)

        res_detail = self.client.get(f"/api/deals/{unrelated_deal.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_403_FORBIDDEN)

        res_list = self.client.get("/api/deals/")
        deal_ids = [d["id"] for d in res_list.data]
        self.assertNotIn(str(unrelated_deal.id), deal_ids)


class BrokerPersonaPermissionE2ETests(BasePermissionE2ETestCase):
    """
    Validates Broker authorization scope:
    - Allowed: public RFQ discovery, submit offer as Broker, view own negotiation history.
    - Denied: competitor commercial offers (404), comparison table (403), award APIs (403),
      opportunity qualification/conversion (403), deal attribution resolution (403).
    """

    def test_broker_can_view_public_rfqs_and_submit_broker_offer(self):
        """Broker can discover published RFQ and submit offer under Broker role."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)

        self.client.force_authenticate(user=self.broker_user)

        # 1. View published RFQ (Public projection)
        res_rfq = self.client.get(f"/api/trade-hub/rfqs/{rfq.id}/")
        self.assertEqual(res_rfq.status_code, status.HTTP_200_OK)
        self.assertNotIn("internal_notes", res_rfq.data)

        # 2. Broker creates offer under BROKER role
        offer = create_offer(
            actor=self.broker_user,
            rfq=rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        draft = create_draft_offer_version(
            actor=self.broker_user,
            offer=offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("368.00"),
            currency="USD",
            incoterm="FOB",
            payment_terms="LC at sight",
            delivery_terms="Bandar Abbas",
            specifications={"penetration_grade": "60/70"},
            notes="Broker referred commercial terms",
        )
        offer.refresh_from_db()
        submit_internal_offer_version(
            actor=self.broker_user,
            offer_version=draft,
            expected_version=offer.aggregate_version,
        )

        # 3. View own offer history
        res_hist = self.client.get(f"/api/offers/{offer.id}/history/")
        self.assertEqual(res_hist.status_code, status.HTTP_200_OK)
        self.assertEqual(res_hist.data["counterparty_name"], self.broker_org.name)

    def test_broker_cannot_see_competitor_offers_or_buyer_intelligence(self):
        """Broker cannot see competitor offers (404) or Buyer comparison (403)."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        supplier_offer, _ = self.create_sample_offer(
            rfq, self.supplier_user, self.supplier_org, unit_price=Decimal("370.00")
        )

        self.client.force_authenticate(user=self.broker_user)

        # Competitor offer detail -> 404 Not Found
        res_offer = self.client.get(f"/api/offers/{supplier_offer.id}/")
        self.assertEqual(res_offer.status_code, status.HTTP_404_NOT_FOUND)

        # Commercial comparison -> 403 Forbidden
        res_comp = self.client.get(f"/api/offers/rfqs/{rfq.id}/comparison/")
        self.assertEqual(res_comp.status_code, status.HTTP_403_FORBIDDEN)

        # Award creation -> 403 Forbidden
        res_award = self.client.post(f"/api/rfqs/{rfq.id}/awards/", {}, format="json")
        self.assertEqual(res_award.status_code, status.HTTP_403_FORBIDDEN)

    def test_broker_cannot_mutate_opportunity_or_resolve_deal_attribution(self):
        """Broker cannot perform Operator desk mutations or resolve attribution."""
        opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            commodity=self.bitumen,
            schema_version=self.bitumen_schema,
            status=OpportunityStatus.CAPTURED,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            organization=self.supplier_org,
            created_by=self.operator_user,
        )
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        self.client.force_authenticate(user=self.broker_user)

        # Opportunity desk qualify -> 403 Forbidden
        res_qual = self.client.post(
            f"/api/opportunities/opportunities/{opp.id}/qualify/",
            {"expected_version": opp.version},
            format="json",
        )
        self.assertEqual(res_qual.status_code, status.HTTP_403_FORBIDDEN)

        # Deal attribution resolve -> 403 Forbidden
        res_attr = self.client.post(
            f"/api/deals/{deal.id}/attribution/resolve/",
            {"primary_channel": "BROKER", "reason": "Broker attempt"},
            format="json",
        )
        self.assertEqual(res_attr.status_code, status.HTTP_403_FORBIDDEN)


class OperatorPersonaPermissionE2ETests(BasePermissionE2ETestCase):
    """
    Validates Operator authorization scope and strict Product System Role invariants:
    - Allowed: global operational surfaces (verification queue, opportunity desk,
      external counterparty, external offer submission, deal attribution resolution,
      global deal visibility).
    - Invariants: Django is_staff, is_superuser, or Org membership ALONE do not grant
      Operator powers without explicit SystemRoleAssignment.
    """

    def test_operator_can_access_operational_surfaces_globally(self):
        """Platform Operator can access verification queue, desk, and resolve attribution."""
        self.client.force_authenticate(user=self.operator_user)

        # 1. Verification queue
        res_verif = self.client.get("/api/organizations/verification/cases/")
        self.assertEqual(res_verif.status_code, status.HTTP_200_OK)

        # 2. Opportunity desk list
        res_opp = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res_opp.status_code, status.HTTP_200_OK)

        # 3. Create external counterparty
        res_cp = self.client.post(
            "/api/opportunities/external-counterparties/",
            {"company_name": "Operator Managed Petroleum FZE", "geography": "UAE"},
            format="json",
        )
        self.assertEqual(res_cp.status_code, status.HTTP_201_CREATED)

        # 4. Resolve Deal attribution manually
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        res_attr = self.client.post(
            f"/api/deals/{deal.id}/attribution/resolve/",
            {"primary_channel": "PLATFORM_NETWORK", "reason": "Operator verified channel"},
            format="json",
        )
        self.assertEqual(res_attr.status_code, status.HTTP_200_OK)
        self.assertEqual(res_attr.data["primary_channel"], "PLATFORM_NETWORK")
        self.assertEqual(res_attr.data["status"], "RESOLVED")

        # 5. Global Deal access: Operator sees all Deals
        res_deal = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(res_deal.status_code, status.HTTP_200_OK)

    def test_operator_receives_full_operational_offer_projection(self):
        """Operator retrieving an offer receives OperatorOfferDetailResponseSerializer with CRM link."""
        ext_party = ExternalCounterparty.objects.create(
            company_name="Global Bitumen Sourcing",
            geography="OM",
            phone="+96891234567",
            email="sales@omanbitumen.om",
        )
        opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=ext_party,
            commodity=self.bitumen,
            schema_version=self.bitumen_schema,
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        ext_offer, _ = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=rfq,
            opportunity=opp,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Operator terms",
            external_counterparty=ext_party,
        )

        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get(f"/api/offers/{ext_offer.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Operator projection includes full external counterparty CRM details
        self.assertEqual(res.data["counterparty_name"], "Global Bitumen Sourcing")
        self.assertEqual(str(res.data["external_counterparty_id"]), str(ext_party.id))
        self.assertEqual(res.data["source_opportunity_identifier"], opp.identifier)
        self.assertTrue(res.data["is_external"])
        self.assertTrue(res.data["entered_by_operator"])

    def test_django_staff_without_system_role_denied_operator_powers(self):
        """INVARIANT: Django is_staff=True alone has ZERO Product Operator authority."""
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        self.client.force_authenticate(user=self.staff_only_user)

        self.assertEqual(
            self.client.get("/api/organizations/verification/cases/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/opportunities/opportunities/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                "/api/opportunities/external-counterparties/",
                {"company_name": "Staff Attack Corp"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"/api/deals/{deal.id}/attribution/resolve/",
                {"primary_channel": "PLATFORM_NETWORK", "reason": "Staff bypass attempt"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(f"/api/deals/{deal.id}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_django_superuser_without_system_role_denied_operator_powers(self):
        """INVARIANT: Django is_superuser=True alone has ZERO Product Operator authority."""
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        self.client.force_authenticate(user=self.superuser_only_user)

        self.assertEqual(
            self.client.get("/api/organizations/verification/cases/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get("/api/opportunities/opportunities/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                "/api/opportunities/external-counterparties/",
                {"company_name": "Superuser Attack Corp"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"/api/deals/{deal.id}/attribution/resolve/",
                {"primary_channel": "PLATFORM_NETWORK", "reason": "Superuser bypass attempt"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(f"/api/deals/{deal.id}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_organization_capability_or_membership_alone_denied_operator_powers(self):
        """INVARIANT: Organization Owner/Manager role does not confer Product Operator authority."""
        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        DealAttribution.objects.filter(deal=deal).update(
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            resolution_method=None,
        )

        # Buyer Manager / Owner
        self.client.force_authenticate(user=self.buyer_user)
        self.assertEqual(
            self.client.get("/api/organizations/verification/cases/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                f"/api/deals/{deal.id}/attribution/resolve/",
                {"primary_channel": "PLATFORM_NETWORK", "reason": "Org owner attempt"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Supplier Owner
        self.client.force_authenticate(user=self.supplier_user)
        self.assertEqual(
            self.client.get("/api/organizations/verification/cases/").status_code,
            status.HTTP_403_FORBIDDEN,
        )


class CrossOrganizationDirectIdSecurityTests(BasePermissionE2ETestCase):
    """
    Mandatory horizontal penetration regressions:
    Prove that direct object IDs cannot bypass server-side authorization boundaries
    between distinct Organizations (Epic 13 Contract §20).
    """

    def test_cross_org_rfq_isolation(self):
        """Actor from Org A attempting direct ID access to Org B's draft RFQ receives 404/403."""
        draft_b = self.create_sample_rfq(self.buyer_b_user, self.buyer_b_org, is_published=False)

        self.client.force_authenticate(user=self.buyer_user)

        # Direct GET -> 404
        res_get = self.client.get(f"/api/trade-hub/rfqs/{draft_b.id}/")
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        # Direct PATCH -> 403 Forbidden
        res_patch = self.client.patch(
            f"/api/trade-hub/rfqs/{draft_b.id}/",
            {"target_price": "300.00", "expected_version": draft_b.version},
            format="json",
        )
        self.assertEqual(res_patch.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_offer_isolation(self):
        """Supplier A attempting direct ID access to Supplier B's offer receives 404."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)
        offer_b, _ = self.create_sample_offer(
            rfq, self.supplier2_user, self.supplier2_org, unit_price=Decimal("360.00")
        )

        self.client.force_authenticate(user=self.supplier_user)

        res_get = self.client.get(f"/api/offers/{offer_b.id}/")
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        res_hist = self.client.get(f"/api/offers/{offer_b.id}/history/")
        self.assertEqual(res_hist.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_org_deal_isolation(self):
        """Actor from Org A attempting direct ID access to Org B's Deal receives 403."""
        deal_b, _, _ = self.create_sample_finalized_deal(
            self.buyer_b_user, self.buyer_b_org, self.supplier2_user, self.supplier2_org
        )

        self.client.force_authenticate(user=self.buyer_user)

        # Direct GET on deal aggregate -> 403 Forbidden
        res_deal = self.client.get(f"/api/deals/{deal_b.id}/")
        self.assertEqual(res_deal.status_code, status.HTTP_403_FORBIDDEN)

        # Direct GET on deal terms snapshot -> 403 Forbidden
        res_terms = self.client.get(f"/api/deals/{deal_b.id}/terms/")
        self.assertEqual(res_terms.status_code, status.HTTP_403_FORBIDDEN)

        # Direct GET on deal parties snapshot -> 403 Forbidden
        res_parties = self.client.get(f"/api/deals/{deal_b.id}/parties/")
        self.assertEqual(res_parties.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_execution_milestone_tampering_rejected(self):
        """Milestone from Deal A cannot be mutated under Deal B execution scope."""
        deal_a, _, _ = self.create_sample_finalized_deal(
            self.buyer_user, self.buyer_org, self.supplier_user, self.supplier_org
        )
        deal_b, _, _ = self.create_sample_finalized_deal(
            self.buyer_b_user, self.buyer_b_org, self.supplier2_user, self.supplier2_org
        )

        exec_a = create_or_get_execution_for_deal(deal_id=deal_a.id, actor=self.operator_user)
        exec_b = create_or_get_execution_for_deal(deal_id=deal_b.id, actor=self.operator_user)

        m_a = ExecutionMilestone.objects.filter(execution=exec_a).first()
        self.assertIsNotNone(m_a)

        self.client.force_authenticate(user=self.operator_user)

        # Tampering attempt: mutate Milestone A under Execution B route
        url_attack = f"/api/execution/{exec_b.id}/milestones/{m_a.id}/complete/"
        res = self.client.post(url_attack, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Tampering attempt: mutate Milestone A under Deal B route
        url_deal_attack = f"/api/deals/{deal_b.id}/execution/milestones/{m_a.id}/complete/"
        res_deal = self.client.post(url_deal_attack, {"expected_version": 1}, format="json")
        self.assertEqual(res_deal.status_code, status.HTTP_400_BAD_REQUEST)


class AnonymousAndUnauthorizedSecurityTests(BasePermissionE2ETestCase):
    """
    Validates Anonymous, deactivated user, and error state boundaries:
    - Anonymous calls to protected APIs receive 401 or 403.
    - Deactivated user session revoked.
    - Unauthorized access is NEVER represented as a successful empty dataset.
    """

    def test_anonymous_requests_denied_across_protected_apis(self):
        """Anonymous callers receive 401 or 403 on all protected endpoints."""
        rfq = self.create_sample_rfq(self.buyer_user, self.buyer_org, is_published=True)

        endpoints = [
            ("GET", "/api/auth/me"),
            ("GET", "/api/trade-hub/rfqs/"),
            ("GET", "/api/deals/"),
            ("GET", "/api/opportunities/opportunities/"),
            ("GET", "/api/organizations/verification/cases/"),
            ("GET", f"/api/offers/rfqs/{rfq.id}/comparison/"),
        ]

        self.client.logout()

        for method, endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                if method == "GET":
                    res = self.client.get(endpoint)
                else:
                    res = self.client.post(endpoint, {}, format="json")
                self.assertIn(
                    res.status_code,
                    [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
                    f"Anonymous request to {endpoint} must be denied with 401 or 403",
                )

    def test_deactivated_user_session_revoked(self):
        """Deactivated user cannot access protected endpoints (403 Forbidden)."""
        self.client.force_login(self.buyer_user)
        self.buyer_user.is_active = False
        self.buyer_user.save()

        res = self.client.get("/api/auth/me")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        res_rfq = self.client.get("/api/trade-hub/rfqs/")
        self.assertEqual(res_rfq.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthorized_state_is_never_represented_as_successful_empty_dataset(self):
        """Security invariant: 403 or auth failure is NEVER returned as 200 OK with empty list."""
        self.client.logout()
        res_anon = self.client.get("/api/deals/")
        self.assertNotEqual(res_anon.status_code, status.HTTP_200_OK)
        self.assertIn(res_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        deal, _, _ = self.create_sample_finalized_deal(
            self.buyer_b_user, self.buyer_b_org, self.supplier2_user, self.supplier2_org
        )

        # Buyer A accessing foreign deal aggregate directly receives 403, NOT empty object
        self.client.force_authenticate(user=self.buyer_user)
        res_deal = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(res_deal.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", res_deal.data)
