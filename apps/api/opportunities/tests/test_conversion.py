import datetime
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    record_contact_attempt,
)
from opportunities.services_lifecycle import (
    expire_opportunity,
    mark_opportunity_lost,
    put_opportunity_on_hold,
    qualify_opportunity,
    reject_opportunity,
    start_opportunity_matching,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class OpportunityConversionTests(TestCase):
    """
    Authoritative test suite for T0609 — Opportunity -> RFQ Conversion.

    Validates:
    - Successful Demand conversion into Draft RFQ.
    - Exact field mapping from Product Specification §§12 & 17–21.
    - Rejection of invalid direction (Supply) and unqualified states.
    - Single transaction atomic rollback on RFQ failure.
    - External counterparty policy (requires registered Buyer organization, no fake orgs).
    - Preservation of schema version, dynamic specifications, and Opportunity provenance.
    - Relational bidirectional traceability (opp.converted_rfq <-> rfq.source_opportunity).
    - Historical referential protection against destructive deletions.
    - Concurrency and optimistic version control (409 on stale version or already converted).
    - Full actor authorization matrix.
    """

    def setUp(self):
        self.client = APIClient()

        # Users & System Roles
        self.operator = User.objects.create_user(email="operator@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.admin = User.objects.create_user(email="admin@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        # Buyer Organization & User
        self.buyer_org = Organization.objects.create(name="Primary Buyer Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Non-Buyer Organization (Supplier only)
        self.supplier_org = Organization.objects.create(name="Supplier Only Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Broker Organization & User
        self.broker_org = Organization.objects.create(name="Attributed Broker Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Staff & Superuser without system roles
        self.staff_only_user = User.objects.create_user(
            email="staff@test.local", password="password", is_staff=True
        )
        self.superuser_only_user = User.objects.create_superuser(
            email="super@test.local", password="password"
        )

        # External Counterparty
        self.ext_counterparty = ExternalCounterparty.objects.create(
            company_name="Gulf Bitumen Traders LLC",
            contact_name="Ahmad Reza",
            email="ahmad@gulfbitumen.com",
            phone="+971501234567",
            geography="Jebel Ali, UAE",
        )

        # Commodity & Published Schema Version
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_60_70_conv",
            name_en="Bitumen 60/70 Conversion",
            name_fa="قیر ۶۰/۷۰ تبدیل",
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
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_v1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=False,
            sort_order=2,
        )
        publish_schema(self.schema_v1, activate=True)

    def _create_qualified_demand_opportunity(self, **kwargs):
        """Helper to create and qualify a Demand Opportunity for conversion tests."""
        defaults = {
            "direction": OpportunityDirection.DEMAND,
            "organization_id": self.buyer_org.id,
            "commodity_id": self.commodity.id,
            "quantity": Decimal("1000.000"),
            "unit": "MT",
            "indicative_price": Decimal("350.00"),
            "currency": "USD",
            "delivery_window_start": datetime.date(2026, 11, 1),
            "delivery_window_end": datetime.date(2026, 11, 30),
            "payment_terms": "Letter of Credit at sight",
            "geography": "Jebel Ali Port, UAE",
            "notes": "Urgent procurement lead for road paving project.",
            "source": OpportunitySource.OPERATOR_SOURCING,
        }
        defaults.update(kwargs)
        opp = create_opportunity(**defaults)
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        return opp

    # -------------------------------------------------------------------------
    # 1. Successful Demand Conversion & Exact Field Mapping
    # -------------------------------------------------------------------------

    def test_demand_opportunity_converts_to_draft_rfq_successfully(self):
        """
        Confirm that a qualified Demand Opportunity converts into a real Draft RFQ
        with exact field mapping, single version increment, and durable link.
        """
        opp = self._create_qualified_demand_opportunity()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(opp.version, 2)  # 1 on create, 2 on qualify

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": 2,
            "schema_version_id": str(self.schema_v1.id),
            "specifications": {"penetration_grade": "60/70", "softening_point": 49.5},
            "incoterm": "FOB",
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        # Verify Response Structure
        self.assertIn("opportunity", res.data)
        self.assertIn("rfq", res.data)
        rfq_data = res.data["rfq"]
        opp_data = res.data["opportunity"]

        # Verify Created RFQ Aggregate
        rfq_id = rfq_data["id"]
        rfq = RFQ.objects.get(id=rfq_id)
        self.assertEqual(rfq.status, RFQStatus.DRAFT)
        self.assertEqual(rfq.visibility, RFQVisibility.PRIVATE)
        self.assertEqual(rfq.version, 1)
        self.assertTrue(rfq.created_by_operator)
        self.assertEqual(rfq.created_by, self.operator)
        self.assertEqual(rfq.organization, self.buyer_org)
        self.assertEqual(rfq.commodity, self.commodity)
        self.assertEqual(rfq.schema_version, self.schema_v1)
        self.assertEqual(rfq.specifications, {"penetration_grade": "60/70", "softening_point": 49.5})
        self.assertEqual(rfq.quantity, Decimal("1000.000"))
        self.assertEqual(rfq.unit, "MT")
        self.assertEqual(rfq.target_price, Decimal("350.00"))
        self.assertEqual(rfq.currency, "USD")
        self.assertEqual(rfq.delivery_window_start, datetime.date(2026, 11, 1))
        self.assertEqual(rfq.delivery_window_end, datetime.date(2026, 11, 30))
        self.assertEqual(rfq.destination, "Jebel Ali Port, UAE")
        self.assertEqual(rfq.payment_terms, "Letter of Credit at sight")
        self.assertEqual(rfq.incoterm, "FOB")
        self.assertIn(opp.identifier, rfq.notes)
        self.assertIn("Urgent procurement lead", rfq.notes)

        # Verify Updated Opportunity Aggregate
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertIsNotNone(opp.converted_at)
        self.assertEqual(opp.version, 3)  # Exactly one increment from 2 -> 3
        self.assertEqual(opp.converted_rfq, rfq)
        self.assertEqual(opp_data["converted_rfq_id"], str(rfq.id))

    # -------------------------------------------------------------------------
    # 2. Dynamic Specifications & Schema Version Preservation
    # -------------------------------------------------------------------------

    def test_exact_schema_version_and_specifications_preserved_when_stored_on_opportunity(self):
        """
        When an Opportunity carries exact schema_version and specifications,
        conversion must preserve the exact schema version and specs without mutation.
        """
        opp = self._create_qualified_demand_opportunity()
        opp.schema_version = self.schema_v1
        opp.specifications = {"penetration_grade": "60/70", "softening_point": 51.0}
        opp.version += 1
        opp.save(update_fields=["schema_version", "specifications", "version"])

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        # Payload does not need schema_version_id because opportunity carries it
        payload = {"expected_version": opp.version}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        rfq = RFQ.objects.get(id=res.data["rfq"]["id"])
        self.assertEqual(rfq.schema_version, self.schema_v1)
        self.assertEqual(rfq.specifications, {"penetration_grade": "60/70", "softening_point": 51.0})

    def test_missing_schema_version_rejected_without_mapping_to_today_active(self):
        """
        If Opportunity does not store a schema version, caller must provide it explicitly.
        System must NEVER silently map to today's active schema.
        """
        opp = self._create_qualified_demand_opportunity()

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {"expected_version": opp.version}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("schema_version_id", str(res.data))

        # Opportunity remains unchanged
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertIsNone(opp.converted_rfq)

    # -------------------------------------------------------------------------
    # 3. Direction Invariant (Demand Only)
    # -------------------------------------------------------------------------

    def test_supply_direction_rejected_from_conversion(self):
        """
        Confirm that Supply Opportunities cannot be converted to RFQ under any circumstances.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("320.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="TT in advance",
            geography="Bandar Abbas, Iran",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        self.assertEqual(opp.direction, OpportunityDirection.SUPPLY)
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Demand", res.data["detail"])

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertIsNone(opp.converted_rfq)

    # -------------------------------------------------------------------------
    # 4. State Invariants (Qualified or Matching Only)
    # -------------------------------------------------------------------------

    def test_unqualified_states_rejected(self):
        """
        Confirm that Captured, Contacted, On Hold, Lost, Rejected, and Expired
        opportunities are strictly rejected from RFQ conversion.
        """
        # Captured
        opp_captured = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("100.000"),
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp_captured.id}/convert-to-rfq/"
        payload = {"expected_version": 1, "schema_version_id": str(self.schema_v1.id)}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Contacted
        opp_contacted = self._create_qualified_demand_opportunity()
        opp_contacted.status = OpportunityStatus.CONTACTED
        opp_contacted.version += 1
        opp_contacted.save(update_fields=["status", "version"])
        url = f"/api/opportunities/opportunities/{opp_contacted.id}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": opp_contacted.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # On Hold
        opp_hold = self._create_qualified_demand_opportunity()
        opp_hold = put_opportunity_on_hold(opp_hold.id, expected_version=opp_hold.version, reason="Awaiting confirmation")
        url = f"/api/opportunities/opportunities/{opp_hold.id}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": opp_hold.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Lost
        opp_lost = self._create_qualified_demand_opportunity()
        opp_lost = mark_opportunity_lost(opp_lost.id, expected_version=opp_lost.version, reason="Client chose competitor")
        url = f"/api/opportunities/opportunities/{opp_lost.id}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": opp_lost.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Rejected
        opp_rej = self._create_qualified_demand_opportunity()
        opp_rej = reject_opportunity(opp_rej.id, expected_version=opp_rej.version, reason="Invalid specifications")
        url = f"/api/opportunities/opportunities/{opp_rej.id}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": opp_rej.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Expired
        opp_exp = self._create_qualified_demand_opportunity()
        opp_exp = expire_opportunity(opp_exp.id, expected_version=opp_exp.version, reason="Past window")
        url = f"/api/opportunities/opportunities/{opp_exp.id}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": opp_exp.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_matching_state_allowed_to_convert(self):
        """
        Confirm that an Opportunity in Matching status (post-qualified) can also convert to RFQ.
        """
        opp = self._create_qualified_demand_opportunity()
        opp = start_opportunity_matching(opp.id, expected_version=opp.version, actor=self.operator)
        self.assertEqual(opp.status, OpportunityStatus.MATCHING)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)

    # -------------------------------------------------------------------------
    # 5. Idempotency & Duplicate Conversion Protection
    # -------------------------------------------------------------------------

    def test_already_converted_opportunity_rejected_with_409(self):
        """
        A second conversion attempt on an already converted Opportunity must be rejected
        with HTTP 409 Conflict, without creating a duplicate RFQ.
        """
        opp = self._create_qualified_demand_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
        }
        res1 = self.client.post(url, payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        rfq_count = RFQ.objects.count()

        # Retry conversion with new version
        opp.refresh_from_db()
        res2 = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res2.data.get("code"), "already_converted")
        self.assertEqual(RFQ.objects.count(), rfq_count)

    def test_stale_expected_version_rejected_with_409(self):
        """
        Providing an outdated or mismatched expected_version returns 409 Conflict.
        """
        opp = self._create_qualified_demand_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": 999,
            "schema_version_id": str(self.schema_v1.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version error", res.data["detail"])

    # -------------------------------------------------------------------------
    # 6. External Counterparty Policy
    # -------------------------------------------------------------------------

    def test_external_counterparty_without_buyer_org_blocked(self):
        """
        An External Counterparty cannot own an RFQ directly.
        Attempting conversion without buyer_organization_id must be blocked.
        No fake Organization is created.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            external_counterparty_id=self.ext_counterparty.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("750.000"),
            unit="MT",
            indicative_price=Decimal("340.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="Letter of Credit",
            geography="Dubai, UAE",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        org_count = Organization.objects.count()

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("buyer_organization_id", res.data["detail"])
        # No fake organization created
        self.assertEqual(Organization.objects.count(), org_count)

    def test_external_counterparty_with_buyer_org_creates_rfq_on_behalf(self):
        """
        When Operator provides a real registered Buyer organization for an external
        counterparty Demand Opportunity, conversion succeeds with that Buyer organization
        owning the RFQ.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            external_counterparty_id=self.ext_counterparty.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("750.000"),
            unit="MT",
            indicative_price=Decimal("340.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="Letter of Credit",
            geography="Dubai, UAE",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "buyer_organization_id": str(self.buyer_org.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        rfq = RFQ.objects.get(id=res.data["rfq"]["id"])
        self.assertEqual(rfq.organization, self.buyer_org)
        self.assertTrue(rfq.created_by_operator)

        # Opportunity counterparty remains the external counterparty
        opp.refresh_from_db()
        self.assertEqual(opp.external_counterparty, self.ext_counterparty)
        self.assertIsNone(opp.organization)

    def test_internal_org_lacking_buyer_capability_rejected(self):
        """
        Attempting conversion where the referenced organization lacks Buyer capability
        must be rejected.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.supplier_org.id,  # Supplier Org lacks BUYER capability
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("330.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="Letter of Credit",
            geography="Dubai, UAE",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Buyer capability", str(res.data))

    # -------------------------------------------------------------------------
    # 7. Provenance & Attribution Preservation
    # -------------------------------------------------------------------------

    def test_provenance_and_attribution_preserved_unchanged(self):
        """
        After conversion, confirm that Opportunity human identifier, source, broker
        attribution, counterparty, direction, commodity, notes, and contact history
        are completely unchanged.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1200.000"),
            unit="MT",
            indicative_price=Decimal("360.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="TT at sight",
            geography="Sharjah, UAE",
            notes="Lead from broker referral.",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        # Record contact history before qualification
        record_contact_attempt(opp.id, type="CALL", notes="Initial discovery call", actor=self.operator)
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        # Snapshot pre-conversion state
        identifier_before = opp.identifier
        source_before = opp.source
        broker_before = opp.broker_id
        direction_before = opp.direction
        commodity_before = opp.commodity_id
        org_before = opp.organization_id
        contact_attempts_count = opp.contact_attempts.count()

        # Convert
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        opp.refresh_from_db()
        self.assertEqual(opp.identifier, identifier_before)
        self.assertEqual(opp.source, source_before)
        self.assertEqual(opp.broker_id, broker_before)
        self.assertEqual(opp.direction, direction_before)
        self.assertEqual(opp.commodity_id, commodity_before)
        self.assertEqual(opp.organization_id, org_before)
        self.assertEqual(opp.contact_attempts.count(), contact_attempts_count)

    # -------------------------------------------------------------------------
    # 8. Relational Bidirectional Traceability
    # -------------------------------------------------------------------------

    def test_bidirectional_relational_traceability(self):
        """
        Verify both query directions:
        - Opportunity -> converted RFQ (opp.converted_rfq)
        - RFQ -> source Opportunity (rfq.source_opportunity and rfq.source_opportunity_safe)
        - Relational ORM lookups work without text ID reliance.
        """
        opp = self._create_qualified_demand_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        rfq_id = res.data["rfq"]["id"]
        rfq = RFQ.objects.get(id=rfq_id)
        opp.refresh_from_db()

        # Forward query
        self.assertEqual(opp.converted_rfq, rfq)

        # Reverse query
        self.assertEqual(rfq.source_opportunity, opp)
        self.assertEqual(rfq.source_opportunity_safe, opp)

        # ORM filter queries
        self.assertTrue(RFQ.objects.filter(source_opportunity=opp).exists())
        self.assertTrue(Opportunity.objects.filter(converted_rfq=rfq).exists())

    # -------------------------------------------------------------------------
    # 9. Single Transaction Atomic Rollback
    # -------------------------------------------------------------------------

    def test_atomic_rollback_on_rfq_creation_failure(self):
        """
        Confirm that if RFQ creation fails (e.g. invalid dynamic specifications),
        the whole PostgreSQL transaction rolls back:
        - No RFQ is created.
        - Opportunity status remains Qualified.
        - Opportunity version remains unchanged.
        - Opportunity converted_rfq remains None.
        """
        opp = self._create_qualified_demand_opportunity()
        initial_version = opp.version
        rfq_count = RFQ.objects.count()

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        # Invalid spec: softening_point should be NUMBER, pass invalid string
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "specifications": {"penetration_grade": "60/70", "softening_point": "not_a_number"},
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Transaction rolled back completely
        self.assertEqual(RFQ.objects.count(), rfq_count)
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(opp.version, initial_version)
        self.assertIsNone(opp.converted_rfq)

    # -------------------------------------------------------------------------
    # 10. Historical Referential Protection on Delete
    # -------------------------------------------------------------------------

    def test_historical_referential_protection_on_delete(self):
        """
        Confirm that neither deleting the converted RFQ nor deleting the converted
        Opportunity can succeed, protecting historical trade records and attribution.
        """
        opp = self._create_qualified_demand_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        rfq = RFQ.objects.get(id=res.data["rfq"]["id"])
        opp.refresh_from_db()

        # Attempt to delete RFQ -> raises ProtectedError
        with self.assertRaises(ProtectedError):
            rfq.delete()

        # Attempt to delete Opportunity -> raises ProtectedError
        with self.assertRaises(ProtectedError):
            opp.delete()

        # Attempt to delete via API -> 405 Method Not Allowed
        res_delete = self.client.delete(f"/api/opportunities/opportunities/{opp.id}/")
        self.assertEqual(res_delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    # -------------------------------------------------------------------------
    # 11. Mass Assignment Guard
    # -------------------------------------------------------------------------

    def test_mass_assignment_protection(self):
        """
        Confirm that client cannot inject status, version, or created_by_operator
        in the request payload to tamper with the RFQ or Opportunity state.
        """
        opp = self._create_qualified_demand_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-rfq/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "status": "published",
            "version": 999,
            "created_by_operator": False,
            "converted_rfq": str(uuid.uuid4()),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        rfq = RFQ.objects.get(id=res.data["rfq"]["id"])
        self.assertEqual(rfq.status, RFQStatus.DRAFT)
        self.assertEqual(rfq.version, 1)
        self.assertTrue(rfq.created_by_operator)

    # -------------------------------------------------------------------------
    # 12. Full Authorization Matrix
    # -------------------------------------------------------------------------

    def test_authorization_matrix(self):
        """
        Verify conversion authorization across all required actors:
        - Operator: 201 Created
        - Admin: 201 Created
        - Buyer: 403 Forbidden
        - Supplier: 403 Forbidden
        - Broker: 403 Forbidden
        - Attributed Broker: 403 Forbidden
        - Staff-only (no system role): 403 Forbidden
        - Superuser-only (no system role): 403 Forbidden
        - Anonymous: 401 Unauthorized
        """
        def make_opp(broker=None):
            return self._create_qualified_demand_opportunity(
                source=OpportunitySource.BROKER_REFERRAL if broker else OpportunitySource.OPERATOR_SOURCING,
                broker_id=broker.id if broker else None,
            )

        # Anonymous
        self.client.logout()
        opp_anon = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_anon.id}/convert-to-rfq/",
            {"expected_version": opp_anon.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # Buyer
        self.client.force_authenticate(user=self.buyer_user)
        opp_buyer = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_buyer.id}/convert-to-rfq/",
            {"expected_version": opp_buyer.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Supplier
        self.client.force_authenticate(user=self.supplier_user)
        opp_supp = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_supp.id}/convert-to-rfq/",
            {"expected_version": opp_supp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Broker (unattributed)
        self.client.force_authenticate(user=self.broker_user)
        opp_brk = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_brk.id}/convert-to-rfq/",
            {"expected_version": opp_brk.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Attributed Broker
        opp_attr_brk = make_opp(broker=self.broker_org)
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_attr_brk.id}/convert-to-rfq/",
            {"expected_version": opp_attr_brk.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Staff-only (no system role)
        self.client.force_authenticate(user=self.staff_only_user)
        opp_staff = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_staff.id}/convert-to-rfq/",
            {"expected_version": opp_staff.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Superuser-only (no system role)
        self.client.force_authenticate(user=self.superuser_only_user)
        opp_super = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_super.id}/convert-to-rfq/",
            {"expected_version": opp_super.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Product Admin -> 201 Created
        self.client.force_authenticate(user=self.admin)
        opp_admin = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_admin.id}/convert-to-rfq/",
            {"expected_version": opp_admin.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Operator -> 201 Created
        self.client.force_authenticate(user=self.operator)
        opp_op = make_opp()
        res = self.client.post(
            f"/api/opportunities/opportunities/{opp_op.id}/convert-to-rfq/",
            {"expected_version": opp_op.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    # -------------------------------------------------------------------------
    # 13. Non-Existent Opportunity (404)
    # -------------------------------------------------------------------------

    def test_non_existent_opportunity_returns_404(self):
        """Random non-existent UUID returns 404."""
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{uuid.uuid4()}/convert-to-rfq/"
        res = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
