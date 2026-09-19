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
from commodities.services import clone_schema_to_draft, publish_schema
from identity.models import SystemRoleAssignment
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.models import OfferCostComponent
from offers.services.comparison import (
    CostComparability,
    TechnicalComplianceStatus,
)
from offers.services.creation import create_offer
from offers.services.normalization import normalize_offer_version
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class RFQComparisonAPITests(TestCase):
    """
    Comprehensive tests for T0806 — Comparison API:
    - GET /api/rfqs/<rfq_id>/comparison/
    - GET /api/offers/rfqs/<rfq_id>/comparison/
    - GET /api/trade-hub/rfqs/<rfq_id>/comparison/
    """

    def setUp(self):
        self.client = APIClient()

        # Commodity & Schema S1
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_comp_{uuid.uuid4().hex[:6]}",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.schema_s1 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        self.attr_pen = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_s1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        self.attr_soft = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_s1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=False,
            sort_order=2,
        )
        publish_schema(self.schema_s1, activate=True)

        # Buyer Organization & User
        self.buyer_org = Organization.objects.create(name="Primary Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@test.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Foreign Buyer Organization & User (Unauthorized to access self.published_rfq)
        self.foreign_buyer_org = Organization.objects.create(name="Foreign Buyer Org", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.foreign_buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.foreign_buyer_user = User.objects.create_user(email="foreign_buyer@test.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=self.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Published RFQ (1000 MT, USD)
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_s1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
            quantity=Decimal("1000.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Platform Operator User
        self.operator_user = User.objects.create_user(email="operator@test.com", password="pw")
        SystemRoleAssignment.objects.create(
            user=self.operator_user, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        # Supplier A Org & User
        self.supplier_a_org = Organization.objects.create(name="Supplier A Petrochemical", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.supplier_a_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        OrganizationVerification.objects.create(
            organization=self.supplier_a_org, status=VerificationStatus.VERIFIED
        )
        self.supplier_a_user = User.objects.create_user(email="supplier_a@test.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_a_org,
            user=self.supplier_a_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Supplier B Org & User (Unverified)
        self.supplier_b_org = Organization.objects.create(name="Supplier B Energy", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.supplier_b_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_b_user = User.objects.create_user(email="supplier_b@test.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_b_org,
            user=self.supplier_b_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Broker Org & User
        self.broker_org = Organization.objects.create(name="Premier Commodity Brokers", is_active=True)
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        OrganizationVerification.objects.create(
            organization=self.broker_org, status=VerificationStatus.BASIC_VERIFIED
        )
        self.broker_user = User.objects.create_user(email="broker@test.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # External Counterparty & Supply Opportunity
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Gulf Bitumen FZE",
            contact_name="Farhad K.",
            phone="+971501112233",
            email="farhad@gulfbitumen.ae",
            notes="Confidential margin note: $20/MT. Private source.",
        )
        self.opportunity = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6].upper()}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_s1,
            quantity=Decimal("500.000"),
            unit="MT",
            created_by=self.operator_user,
        )

    def _create_submitted_offer(
        self,
        user,
        org,
        role,
        quantity,
        price,
        currency="USD",
        specifications=None,
        logistics_cost_status=LogisticsCostStatus.UNKNOWN,
        logistics_cost_amount=None,
        valid_until=None,
        payment_terms="",
        delivery_terms="",
        incoterm="",
    ):
        offer = create_offer(
            rfq=self.rfq,
            actor=user,
            offering_organization=org,
            offeror_role=role,
        )
        v = create_draft_offer_version(
            actor=user,
            offer=offer,
            offered_quantity=quantity,
            quantity_unit="MT",
            unit_price=price,
            currency=currency,
            specifications=(
                specifications
                if specifications is not None
                else {"penetration_grade": "60/70", "softening_point": 49.5}
            ),
            logistics_cost_status=logistics_cost_status,
            logistics_cost_amount=logistics_cost_amount,
            valid_until=valid_until,
            payment_terms=payment_terms,
            delivery_terms=delivery_terms,
            incoterm=incoterm,
        )
        offer.refresh_from_db()
        submitted = submit_internal_offer_version(
            actor=user,
            offer_version=v,
            expected_version=offer.aggregate_version,
        )
        return offer, submitted

    # -------------------------------------------------------------------------
    # 1. Current version: V1 + V2 Submitted → V2 only
    # -------------------------------------------------------------------------
    def test_current_version_v1_and_v2_submitted_returns_v2_only(self):
        """When an offer has V1 submitted and subsequently V2 submitted, only V2 appears in comparison."""
        offer, v1 = self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("400.000"),
            price=Decimal("350.00"),
        )

        # V2: 600 MT @ $340
        v2 = create_draft_offer_version(
            actor=self.supplier_a_user,
            offer=offer,
            offered_quantity=Decimal("600.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )
        offer.refresh_from_db()
        submit_internal_offer_version(
            actor=self.supplier_a_user,
            offer_version=v2,
            expected_version=offer.aggregate_version,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()

        self.assertEqual(data["total_offers"], 1)
        items = data["items"]
        self.assertEqual(len(items), 1)
        # Active row must be V2, not V1
        self.assertEqual(items[0]["offer_version_id"], str(v2.id))
        self.assertEqual(items[0]["version_number"], 2)
        self.assertEqual(Decimal(items[0]["offered_quantity"]), Decimal("600.000"))
        self.assertEqual(Decimal(items[0]["unit_price"]), Decimal("340.00"))

    # -------------------------------------------------------------------------
    # 2. Draft: V1 Submitted + V2 Draft → V1; unsubmitted draft-only offers excluded
    # -------------------------------------------------------------------------
    def test_draft_v1_submitted_and_v2_draft_returns_v1_only(self):
        """V1 submitted with in-progress V2 draft returns V1. Unsubmitted offers are excluded."""
        offer, v1 = self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("400.000"),
            price=Decimal("350.00"),
        )

        # Unsubmitted V2 draft
        create_draft_offer_version(
            actor=self.supplier_a_user,
            offer=offer,
            offered_quantity=Decimal("700.000"),
            quantity_unit="MT",
            unit_price=Decimal("320.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        # Another offer that only has a Draft (never submitted)
        draft_only_offer = create_offer(
            rfq=self.rfq,
            actor=self.supplier_b_user,
            offering_organization=self.supplier_b_org,
            offeror_role=OfferorRole.SUPPLIER,
        )
        create_draft_offer_version(
            actor=self.supplier_b_user,
            offer=draft_only_offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("360.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()

        # Only 1 offer has a submitted version; draft-only offer is completely excluded
        self.assertEqual(data["total_offers"], 1)
        self.assertEqual(data["items"][0]["offer_version_id"], str(v1.id))
        self.assertEqual(data["items"][0]["version_number"], 1)
        self.assertEqual(Decimal(data["items"][0]["offered_quantity"]), Decimal("400.000"))

    # -------------------------------------------------------------------------
    # 3. Mixed parties: Supplier + Broker + External Counterparty
    # -------------------------------------------------------------------------
    def test_mixed_parties_supplier_broker_external(self):
        """Comparison correctly returns Supplier, Broker, and External Counterparty offers side-by-side."""
        # 1. Supplier A Offer
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("380.00"),
        )

        # 2. Broker Offer
        self._create_submitted_offer(
            user=self.broker_user,
            org=self.broker_org,
            role=OfferorRole.BROKER,
            quantity=Decimal("400.000"),
            price=Decimal("375.00"),
        )

        # 3. External Offer entered by Operator on behalf
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("360.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()

        self.assertEqual(data["total_offers"], 3)
        roles = {item["offeror_role"] for item in data["items"]}
        self.assertEqual(roles, {"SUPPLIER", "BROKER"})
        ext_count = sum(1 for item in data["items"] if item["is_external"])
        self.assertEqual(ext_count, 1)

    # -------------------------------------------------------------------------
    # 4. Partial quantity: 400 / 1000 → coverage 0.4, surplus 0
    # -------------------------------------------------------------------------
    def test_partial_quantity_coverage_and_surplus(self):
        """Offered 400 MT on 1000 MT RFQ derives coverage 0.4000 and surplus 0.000."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("400.000"),
            price=Decimal("350.00"),
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(Decimal(item["quantity_coverage"]), Decimal("0.4000"))
        self.assertEqual(Decimal(item["surplus_quantity"]), Decimal("0.000"))

    # -------------------------------------------------------------------------
    # 5. Surplus quantity: 1200 / 1000 → coverage 1.0, surplus 200
    # -------------------------------------------------------------------------
    def test_surplus_quantity_coverage_and_surplus(self):
        """Offered 1200 MT on 1000 MT RFQ derives coverage 1.0000 and surplus 200.000 without bonus score."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("1200.000"),
            price=Decimal("350.00"),
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(Decimal(item["quantity_coverage"]), Decimal("1.0000"))
        self.assertEqual(Decimal(item["surplus_quantity"]), Decimal("200.000"))

    # -------------------------------------------------------------------------
    # 6. Normalization: T0805 exact values reused
    # -------------------------------------------------------------------------
    def test_normalization_exact_values_reused_from_t0805(self):
        """T0805 normalization output values are exactly preserved in the comparison row."""
        offer = create_offer(
            rfq=self.rfq,
            actor=self.supplier_a_user,
            offering_organization=self.supplier_a_org,
            offeror_role=OfferorRole.SUPPLIER,
        )
        v = create_draft_offer_version(
            actor=self.supplier_a_user,
            offer=offer,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("300.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("5000.00"),
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )
        OfferCostComponent.objects.create(
            offer_version=v,
            kind=CostComponentKind.OTHER,
            amount=Decimal("1000.00"),
            currency="USD",
            description="Inspection fee",
        )
        offer.refresh_from_db()
        submit_internal_offer_version(
            actor=self.supplier_a_user,
            offer_version=v,
            expected_version=offer.aggregate_version,
        )

        norm_direct = normalize_offer_version(v)

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(Decimal(item["product_cost"]), norm_direct.product_cost)
        self.assertEqual(Decimal(item["known_cost_total"]), norm_direct.known_cost_total)
        self.assertEqual(Decimal(item["landed_cost"]), norm_direct.landed_cost)
        self.assertEqual(Decimal(item["landed_unit_cost"]), norm_direct.landed_unit_cost)
        self.assertTrue(item["normalization_complete"])
        self.assertEqual(item["missing_components"], [])

    # -------------------------------------------------------------------------
    # 7. Unknown logistics: landed values strictly null (never zero)
    # -------------------------------------------------------------------------
    def test_unknown_logistics_landed_values_null_not_zero(self):
        """When logistics is UNKNOWN, landed_cost and landed_unit_cost are strictly null."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("300.00"),
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertIsNone(item["landed_cost"])
        self.assertIsNone(item["landed_unit_cost"])
        self.assertFalse(item["normalization_complete"])
        self.assertIn("LOGISTICS", item["missing_components"])
        self.assertEqual(item["cost_comparability"], CostComparability.INCOMPLETE_COST.value)

    # -------------------------------------------------------------------------
    # 8. Same currency: facts comparable, no rank
    # -------------------------------------------------------------------------
    def test_same_currency_facts_comparable_no_rank(self):
        """Offers in same currency with known costs are COMPARABLE; no ranking or score is returned."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("300.00"),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(item["cost_comparability"], CostComparability.COMPARABLE.value)
        for forbidden in ("rank", "score", "decision_score", "effective_score", "recommended", "winner"):
            self.assertNotIn(forbidden, item)
            self.assertNotIn(forbidden, resp.json())

    # -------------------------------------------------------------------------
    # 9. Cross currency: USD vs EUR explicitly CROSS_CURRENCY_UNKNOWN
    # -------------------------------------------------------------------------
    def test_cross_currency_incomparable(self):
        """Offers with currency differing from RFQ are explicitly marked CROSS_CURRENCY_UNKNOWN without fake FX."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("280.00"),
            currency="EUR",  # RFQ is USD
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(item["currency"], "EUR")
        self.assertEqual(item["cost_comparability"], CostComparability.CROSS_CURRENCY_UNKNOWN.value)

    # -------------------------------------------------------------------------
    # 10. Technical compliance: PASS / FAIL / UNKNOWN
    # -------------------------------------------------------------------------
    def test_technical_compliance_pass_fail_unknown(self):
        """Evaluation produces PASS, FAIL, or UNKNOWN; non-compliant offers remain visible in comparison."""
        # Offer 1: Exact match -> PASS
        offer1, _ = self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("300.00"),
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        # Offer 2: Value mismatch -> FAIL
        offer2, _ = self._create_submitted_offer(
            user=self.supplier_b_user,
            org=self.supplier_b_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("290.00"),
            specifications={"penetration_grade": "85/100", "softening_point": 49.5},
        )

        # Offer 3: Missing required specification -> UNKNOWN
        offer3, _ = self._create_submitted_offer(
            user=self.broker_user,
            org=self.broker_org,
            role=OfferorRole.BROKER,
            quantity=Decimal("300.000"),
            price=Decimal("310.00"),
            specifications={"penetration_grade": "60/70"},  # softening_point missing
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        items = resp.json()["items"]
        self.assertEqual(len(items), 3)

        compliance_map = {item["offer_id"]: item["technical_compliance"] for item in items}
        self.assertEqual(compliance_map[str(offer1.id)], TechnicalComplianceStatus.PASS.value)
        self.assertEqual(compliance_map[str(offer2.id)], TechnicalComplianceStatus.FAIL.value)
        self.assertEqual(compliance_map[str(offer3.id)], TechnicalComplianceStatus.UNKNOWN.value)

        # Confirm failing offer was NOT hidden
        self.assertIn(str(offer2.id), compliance_map)

    # -------------------------------------------------------------------------
    # 11. Trust: Internal Org verification state vs ExternalCounterparty UNKNOWN
    # -------------------------------------------------------------------------
    def test_trust_internal_org_vs_external_unknown(self):
        """Internal Org reflects authoritative verification status; External Counterparty is UNKNOWN with no broker transfer."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("300.00"),
        )

        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("400.000"),
            quantity_unit="MT",
            unit_price=Decimal("310.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        items = resp.json()["items"]

        sup_item = next(i for i in items if not i["is_external"])
        ext_item = next(i for i in items if i["is_external"])

        self.assertEqual(sup_item["trust_status"], "VERIFIED")
        self.assertEqual(ext_item["trust_status"], "UNKNOWN")

    # -------------------------------------------------------------------------
    # 12. Active schema attack regression: changing active schema does not mutate comparison
    # -------------------------------------------------------------------------
    def test_active_schema_attack_regression(self):
        """Creating and activating Schema S2 does not change historical S1 comparison results."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("300.00"),
        )

        # Evaluate comparison under initial S1
        self.client.force_authenticate(user=self.buyer_user)
        resp_before = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_before.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp_before.json()["items"][0]["technical_compliance"],
            TechnicalComplianceStatus.PASS.value,
        )

        # Attack: Clone S1 to S2, add a new required attribute, activate S2 on Commodity
        schema_s2 = clone_schema_to_draft(self.schema_s1)
        CommodityAttributeDefinition.objects.create(
            schema_version=schema_s2,
            key="breaking_point",
            label_fa="نقطه شکست",
            label_en="Breaking Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
        )
        publish_schema(schema_s2, activate=True)
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version, schema_s2)

        # Re-evaluate comparison: must strictly use historical rfq.schema_version (S1)
        resp_after = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_after.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp_after.json()["items"][0]["technical_compliance"],
            TechnicalComplianceStatus.PASS.value,
        )

    # -------------------------------------------------------------------------
    # 13. Expiry: derived only without mutating OfferVersion
    # -------------------------------------------------------------------------
    def test_expiry_derived_only_no_mutation(self):
        """Proposal expiry is computed dynamically from valid_until without mutating the database record."""
        past_time = timezone.now() - timedelta(days=2)
        offer, v = self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("300.00"),
            valid_until=past_time,
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertTrue(item["is_expired"])
        v.refresh_from_db()
        self.assertEqual(v.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(v.valid_until, past_time)

    # -------------------------------------------------------------------------
    # 14. Buyer authorization: own vs foreign RFQ
    # -------------------------------------------------------------------------
    def test_buyer_authorization_own_vs_foreign_rfq(self):
        """Buyer can access comparison for its own RFQ; foreign Buyer receives 403 Forbidden."""
        self.client.force_authenticate(user=self.buyer_user)
        resp_own = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_own.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=self.foreign_buyer_user)
        resp_foreign = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_foreign.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 15. Participant privacy: Supplier/Broker denied
    # -------------------------------------------------------------------------
    def test_participant_privacy_supplier_broker_denied(self):
        """Competitor Supplier, Broker, unauthenticated users, and Django staff without product role receive 403/401."""
        self.client.force_authenticate(user=self.supplier_a_user)
        resp_sup = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_sup.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.broker_user)
        resp_brk = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_brk.status_code, status.HTTP_403_FORBIDDEN)

        self.client.logout()
        resp_anon = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertIn(resp_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        staff_user = User.objects.create_user(email="staff@test.com", password="pw", is_staff=True)
        self.client.force_authenticate(user=staff_user)
        resp_staff = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_staff.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 16. External projection: no CRM/private fields leaked to Buyer
    # -------------------------------------------------------------------------
    def test_external_projection_no_crm_private_fields_leaked_to_buyer(self):
        """Buyer sees safe company_name and is_external=True; phone, email, notes, CRM attempts are NEVER exposed."""
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.json()["items"][0]

        self.assertEqual(item["safe_offeror_identity"], "Gulf Bitumen FZE")
        self.assertEqual(item["offeror_name"], "Gulf Bitumen FZE")
        self.assertTrue(item["is_external"])

        resp_text = resp.content.decode("utf-8")
        self.assertNotIn("+971501112233", resp_text)
        self.assertNotIn("farhad@gulfbitumen.ae", resp_text)
        self.assertNotIn("Confidential margin note", resp_text)
        self.assertNotIn("Farhad K.", resp_text)

    # -------------------------------------------------------------------------
    # 17. Neutral deterministic ordering: no ranking by price/cost/trust
    # -------------------------------------------------------------------------
    def test_ordering_neutral_deterministic_not_sorted_by_price(self):
        """Offers are returned in deterministic creation order, NOT sorted by cheapest price or landed cost."""
        offer1, _ = self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("400.00"),
        )
        offer2, _ = self._create_submitted_offer(
            user=self.supplier_b_user,
            org=self.supplier_b_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("500.000"),
            price=Decimal("250.00"),
        )

        self.client.force_authenticate(user=self.buyer_user)
        resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        items = resp.json()["items"]

        self.assertEqual(items[0]["offer_id"], str(offer1.id))
        self.assertEqual(Decimal(items[0]["unit_price"]), Decimal("400.00"))
        self.assertEqual(items[1]["offer_id"], str(offer2.id))
        self.assertEqual(Decimal(items[1]["unit_price"]), Decimal("250.00"))

    # -------------------------------------------------------------------------
    # 18. Security attack: Supplier A cannot learn competitor commercial fields
    # -------------------------------------------------------------------------
    def test_security_attack_supplier_a_cannot_learn_competitor_data(self):
        """Supplier A cannot learn competitor existence, count, prices, or provenance through comparison."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("390.00"),
        )
        self._create_submitted_offer(
            user=self.supplier_b_user,
            org=self.supplier_b_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("370.00"),
        )
        self._create_submitted_offer(
            user=self.broker_user,
            org=self.broker_org,
            role=OfferorRole.BROKER,
            quantity=Decimal("400.000"),
            price=Decimal("360.00"),
        )
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.supplier_a_user)
        for endpoint in (
            f"/api/offers/rfqs/{self.rfq.id}/comparison/",
            f"/api/trade-hub/rfqs/{self.rfq.id}/comparison/",
            f"/api/rfqs/{self.rfq.id}/comparison/",
        ):
            resp = self.client.get(endpoint)
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
            body = resp.content.decode("utf-8")
            self.assertNotIn("Supplier B", body)
            self.assertNotIn("Premier Commodity", body)
            self.assertNotIn("Gulf Bitumen", body)
            self.assertNotIn("total_offers", body)

    # -------------------------------------------------------------------------
    # 19. T0804 Privacy Regression: Opportunity provenance internal to Operator only
    # -------------------------------------------------------------------------
    def test_t0804_privacy_regression_opportunity_provenance_operator_only(self):
        """Buyer never receives source_opportunity details; Operator caller receives safe provenance."""
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        # 1. Buyer projection
        self.client.force_authenticate(user=self.buyer_user)
        resp_buyer = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_buyer.status_code, status.HTTP_200_OK)
        buyer_item = resp_buyer.json()["items"][0]
        self.assertNotIn("source_opportunity_id", buyer_item)
        self.assertNotIn("source_opportunity_identifier", buyer_item)
        self.assertNotIn("entered_by_operator", buyer_item)

        # 2. Operator projection
        self.client.force_authenticate(user=self.operator_user)
        resp_op = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
        self.assertEqual(resp_op.status_code, status.HTTP_200_OK)
        op_item = resp_op.json()["items"][0]
        self.assertEqual(op_item["source_opportunity_id"], str(self.opportunity.id))
        self.assertEqual(op_item["source_opportunity_identifier"], self.opportunity.identifier)
        self.assertTrue(op_item["entered_by_operator"])

    # -------------------------------------------------------------------------
    # 20. Query efficiency: O(1) constant queries regardless of offer count
    # -------------------------------------------------------------------------
    def test_query_efficiency_constant_queries(self):
        """Comparison evaluation performs a constant number of queries without per-row N+1 queries."""
        self._create_submitted_offer(
            user=self.supplier_a_user,
            org=self.supplier_a_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("380.00"),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self._create_submitted_offer(
            user=self.supplier_b_user,
            org=self.supplier_b_org,
            role=OfferorRole.SUPPLIER,
            quantity=Decimal("300.000"),
            price=Decimal("370.00"),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self._create_submitted_offer(
            user=self.broker_user,
            org=self.broker_org,
            role=OfferorRole.BROKER,
            quantity=Decimal("300.000"),
            price=Decimal("360.00"),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.rfq,
            opportunity=self.opportunity,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            specifications={"penetration_grade": "60/70", "softening_point": 49.5},
        )

        self.client.force_authenticate(user=self.buyer_user)
        with self.assertNumQueries(8):
            resp = self.client.get(f"/api/offers/rfqs/{self.rfq.id}/comparison/")
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.json()["total_offers"], 4)
