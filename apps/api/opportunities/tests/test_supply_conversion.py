import datetime
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError
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
from opportunities.exceptions import (
    OpportunityAlreadyConvertedError,
)
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
from opportunities.services_conversion import (
    convert_opportunity_to_rfq,
    convert_opportunity_to_supply_listing,
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
from trade_hub.models import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)

User = get_user_model()


class OpportunitySupplyConversionTests(TestCase):
    """
    Authoritative test suite for T0610 — Opportunity -> Supply Listing Conversion.

    Validates:
    - Successful Supply conversion into Draft SupplyListing via Epic 5 SupplyService.
    - Exact field mapping from Product Specification §§14 & 17–21.
    - Rejection of invalid direction (Demand) and unqualified states.
    - Single transaction atomic rollback on SupplyListing creation failure.
    - External counterparty policy (requires registered Supplier organization, no fake identities).
    - Internal Supplier capability validation (rejecting Buyer-only / Broker-only organizations).
    - Multi-capability organization acceptance.
    - Preservation of exact schema version, dynamic specifications, and Opportunity provenance.
    - Relational bidirectional durability (opp.converted_supply_listing <-> listing.source_opportunity).
    - Cross-conversion mutual exclusivity (no dual RFQ and Supply Listing links; DB constraint verified).
    - Historical referential protection against destructive deletions.
    - Concurrency and optimistic version control (409 on stale version or already converted).
    - Full actor authorization matrix.
    """

    def setUp(self):
        self.client = APIClient()

        # Users & System Roles
        self.operator = User.objects.create_user(email="operator_supply@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.admin = User.objects.create_user(email="admin_supply@test.local", password="password")
        SystemRoleAssignment.objects.create(
            user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        # Supplier Organization & User
        self.supplier_org = Organization.objects.create(name="Primary Supplier Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier_user@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Buyer-only Organization (No Supplier capability)
        self.buyer_org = Organization.objects.create(name="Buyer Only Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer_user@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Broker-only Organization & User
        self.broker_org = Organization.objects.create(name="Attributed Broker Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker_user@test.local", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.OWNER
        )

        # Multi-capability Organization (Buyer + Supplier)
        self.multi_org = Organization.objects.create(name="Multi Capability Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.multi_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        OrganizationCapability.objects.create(
            organization=self.multi_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )

        # Staff & Superuser without system roles
        self.staff_only_user = User.objects.create_user(
            email="staff_only@test.local", password="password", is_staff=True
        )
        self.superuser_only_user = User.objects.create_superuser(
            email="super_only@test.local", password="password"
        )

        # External Counterparty
        self.ext_counterparty = ExternalCounterparty.objects.create(
            company_name="Caspian Bitumen Refiners LLC",
            contact_name="Farhad Moradi",
            email="farhad@caspianbitumen.com",
            phone="+989121234567",
            geography="Bandar Anzali, Iran",
        )

        # Commodity & Published Schema Version
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_60_70_sup",
            name_en="Bitumen 60/70 Supply",
            name_fa="قیر ۶۰/۷۰ عرضه",
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

    def _create_qualified_supply_opportunity(self, **kwargs):
        """Helper to create and qualify a Supply Opportunity for conversion tests."""
        defaults = {
            "direction": OpportunityDirection.SUPPLY,
            "organization_id": self.supplier_org.id,
            "commodity_id": self.commodity.id,
            "quantity": Decimal("1000.000"),
            "unit": "MT",
            "indicative_price": Decimal("350.00"),
            "currency": "USD",
            "delivery_window_start": datetime.date(2026, 11, 1),
            "delivery_window_end": datetime.date(2026, 11, 30),
            "payment_terms": "Letter of Credit at sight",
            "geography": "Bandar Abbas Port, Iran",
            "notes": "Verified supply allocation from primary refinery.",
            "source": OpportunitySource.OPERATOR_SOURCING,
        }
        defaults.update(kwargs)
        opp = create_opportunity(**defaults)
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)
        return opp

    # -------------------------------------------------------------------------
    # 1. Successful Supply Conversion & Exact Field Mapping
    # -------------------------------------------------------------------------

    def test_supply_opportunity_converts_to_draft_supply_listing_successfully(self):
        """
        Confirm that a qualified Supply Opportunity converts into a real Draft SupplyListing
        with exact field mapping, single version increment, and durable link.
        """
        opp = self._create_qualified_supply_opportunity()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(opp.version, 2)  # 1 on create, 2 on qualify

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {
            "expected_version": 2,
            "schema_version_id": str(self.schema_v1.id),
            "specifications": {"penetration_grade": "60/70", "softening_point": 49.5},
            "incoterm": "FOB",
            "origin": "Bandar Abbas Terminal 1",
            "destination": "Any Safe Port",
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        # Verify Response Structure
        self.assertIn("opportunity", res.data)
        self.assertIn("supply_listing", res.data)
        listing_data = res.data["supply_listing"]
        opp_data = res.data["opportunity"]

        # Verify Created SupplyListing Aggregate
        listing_id = listing_data["id"]
        listing = SupplyListing.objects.get(id=listing_id)
        self.assertEqual(listing.status, SupplyListingStatus.DRAFT)
        self.assertEqual(listing.visibility, SupplyListingVisibility.PUBLIC)
        self.assertEqual(listing.version, 1)
        self.assertTrue(listing.created_by_operator)
        self.assertEqual(listing.created_by, self.operator)
        self.assertEqual(listing.organization, self.supplier_org)
        self.assertEqual(listing.commodity, self.commodity)
        self.assertEqual(listing.schema_version, self.schema_v1)
        self.assertEqual(listing.specifications, {"penetration_grade": "60/70", "softening_point": 49.5})
        self.assertEqual(listing.quantity, Decimal("1000.000"))
        self.assertEqual(listing.unit, "MT")
        self.assertEqual(listing.indicative_price, Decimal("350.00"))
        self.assertEqual(listing.currency, "USD")
        self.assertEqual(listing.availability_window_start, datetime.date(2026, 11, 1))
        self.assertEqual(listing.availability_window_end, datetime.date(2026, 11, 30))
        self.assertEqual(listing.origin, "Bandar Abbas Terminal 1")
        self.assertEqual(listing.destination, "Any Safe Port")
        self.assertEqual(listing.payment_terms, "Letter of Credit at sight")
        self.assertEqual(listing.incoterm, "FOB")
        self.assertIn(opp.identifier, listing.notes)
        self.assertIn("Verified supply allocation", listing.notes)

        # Verify Updated Opportunity Aggregate
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertIsNotNone(opp.converted_at)
        self.assertEqual(opp.version, 3)  # Exactly one increment from 2 -> 3
        self.assertEqual(opp.converted_supply_listing, listing)
        self.assertEqual(opp_data["converted_supply_listing_id"], str(listing.id))

    # -------------------------------------------------------------------------
    # 2. Dynamic Specifications & Schema Version Preservation
    # -------------------------------------------------------------------------

    def test_exact_schema_version_and_specifications_preserved_when_stored_on_opportunity(self):
        """
        When an Opportunity carries exact schema_version and specifications,
        conversion must preserve the exact schema version and specs without mutation.
        """
        opp = self._create_qualified_supply_opportunity()
        opp.schema_version = self.schema_v1
        opp.specifications = {"penetration_grade": "60/70", "softening_point": 48.0}
        opp.save(update_fields=["schema_version", "specifications"])

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {"expected_version": opp.version}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        self.assertEqual(listing.schema_version, self.schema_v1)
        self.assertEqual(listing.specifications, {"penetration_grade": "60/70", "softening_point": 48.0})

    def test_missing_schema_version_rejected_with_400(self):
        """
        If the Opportunity has no schema_version and the payload provides none,
        conversion must fail cleanly with 400 Bad Request.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {"expected_version": opp.version}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("schema_version_id is required", str(res.data))
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertIsNone(opp.converted_supply_listing)

    # -------------------------------------------------------------------------
    # 3. Direction Invariant (Supply Only)
    # -------------------------------------------------------------------------

    def test_demand_opportunity_rejected_for_supply_listing_conversion(self):
        """
        Confirm that a Demand Opportunity cannot be converted to a Supply Listing.
        Must return 400 Bad Request.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            unit="MT",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "supplier_organization_id": str(self.supplier_org.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only Supply opportunities", str(res.data))

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertIsNone(opp.converted_supply_listing)

    # -------------------------------------------------------------------------
    # 4. Lifecycle Status Invariants
    # -------------------------------------------------------------------------

    def test_unqualified_opportunity_statuses_rejected_for_conversion(self):
        """
        Confirm that Opportunities in Captured, Contacted, On Hold, Lost, Rejected,
        or Expired states CANNOT be converted to a Supply Listing.
        """
        self.client.force_authenticate(user=self.operator)

        # 1. Captured
        opp_captured = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        url = f"/api/opportunities/opportunities/{opp_captured.id}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": 1, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only Qualified or Matching", str(res.data))

        # 2. Contacted
        opp_contacted = self._create_qualified_supply_opportunity()
        record_contact_attempt(opp_contacted.id, type="CALL", notes="Called supplier", actor=self.operator)
        opp_contacted = Opportunity.objects.get(id=opp_contacted.id)
        # Put on hold then verify
        opp_hold = put_opportunity_on_hold(opp_contacted.id, expected_version=opp_contacted.version, reason="Waiting specs", actor=self.operator)
        url = f"/api/opportunities/opportunities/{opp_hold.id}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": opp_hold.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Lost
        opp_lost = self._create_qualified_supply_opportunity()
        opp_lost = mark_opportunity_lost(opp_lost.id, expected_version=opp_lost.version, reason="Refinery out of stock", actor=self.operator)
        url = f"/api/opportunities/opportunities/{opp_lost.id}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": opp_lost.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 4. Rejected
        opp_rej = self._create_qualified_supply_opportunity()
        opp_rej = reject_opportunity(opp_rej.id, expected_version=opp_rej.version, reason="Compliance issue", actor=self.operator)
        url = f"/api/opportunities/opportunities/{opp_rej.id}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": opp_rej.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # 5. Expired
        opp_exp = self._create_qualified_supply_opportunity()
        opp_exp = expire_opportunity(opp_exp.id, expected_version=opp_exp.version, reason="Deadline passed", actor=self.operator)
        url = f"/api/opportunities/opportunities/{opp_exp.id}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": opp_exp.version, "schema_version_id": str(self.schema_v1.id)}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_matching_opportunity_can_also_be_converted_to_supply_listing(self):
        """
        Opportunities in Matching status (having passed qualification) can also be converted.
        """
        opp = self._create_qualified_supply_opportunity()
        opp = start_opportunity_matching(opp.id, expected_version=opp.version, actor=self.operator)
        self.assertEqual(opp.status, OpportunityStatus.MATCHING)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.CONVERTED)
        self.assertIsNotNone(opp.converted_supply_listing)

    # -------------------------------------------------------------------------
    # 5. Duplicate & Cross-Conversion Guards
    # -------------------------------------------------------------------------

    def test_already_converted_opportunity_cannot_be_reconverted_to_supply_listing(self):
        """
        Attempting to convert an already converted Opportunity must return 409 Conflict
        with code='already_converted'.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        res1 = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        opp.refresh_from_db()
        # Retry with the updated version
        res2 = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res2.data.get("code"), "already_converted")

    def test_cross_conversion_integrity_rfq_already_converted_rejected(self):
        """
        An Opportunity that has already been converted to an RFQ cannot be converted
        to a Supply Listing. Must return 409 Conflict.
        """
        # Create and qualify Demand opp and convert to RFQ
        opp_demand = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            unit="MT",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp_demand = qualify_opportunity(opp_demand.id, expected_version=1, actor=self.operator)
        opp_demand, rfq = convert_opportunity_to_rfq(
            opp_demand.id,
            expected_version=opp_demand.version,
            actor=self.operator,
            data={"schema_version_id": self.schema_v1.id},
        )
        self.assertEqual(opp_demand.status, OpportunityStatus.CONVERTED)
        self.assertIsNotNone(opp_demand.converted_rfq_id)

        # Attempt to convert to supply listing via domain service -> raises OpportunityAlreadyConvertedError
        with self.assertRaises(OpportunityAlreadyConvertedError):
            convert_opportunity_to_supply_listing(
                opp_demand.id,
                expected_version=opp_demand.version,
                actor=self.operator,
                data={"schema_version_id": self.schema_v1.id, "supplier_organization_id": self.supplier_org.id},
            )

    def test_database_constraint_prevents_dual_conversion_targets(self):
        """
        Direct database constraint check: check_no_dual_conversion_targets enforces
        that converted_rfq and converted_supply_listing cannot both be non-null simultaneously.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        opp.refresh_from_db()
        self.assertIsNotNone(opp.converted_supply_listing)

        # Create a real RFQ to attempt linking as dual conversion target
        from trade_hub.services.rfq_service import RFQService
        rfq = RFQService.create_draft(
            user=self.operator,
            data={
                "organization_id": self.buyer_org.id,
                "commodity_id": self.commodity.id,
                "schema_version_id": self.schema_v1.id,
                "quantity": Decimal("100.000"),
            },
        )

        opp.converted_rfq = rfq
        with self.assertRaises(IntegrityError):
            opp.save(update_fields=["converted_rfq"])

    # -------------------------------------------------------------------------
    # 6. External Counterparty & Supplier Capability Policies
    # -------------------------------------------------------------------------

    def test_external_counterparty_requires_explicit_supplier_organization(self):
        """
        When an Opportunity references an ExternalCounterparty, conversion requires
        providing a valid internal Supplier Organization (supplier_organization_id).
        Missing supplier_organization_id must fail with 400 Bad Request.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty_id=self.ext_counterparty.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1500.000"),
            unit="MT",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"

        # 1. Missing supplier_organization_id -> 400
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("requires specifying an internal Supplier Organization", str(res.data))

        # 2. Providing valid supplier_organization_id -> 201
        res = self.client.post(
            url,
            {
                "expected_version": opp.version,
                "schema_version_id": str(self.schema_v1.id),
                "supplier_organization_id": str(self.supplier_org.id),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        self.assertEqual(listing.organization, self.supplier_org)

        # Counterparty on opportunity remains the external counterparty
        opp.refresh_from_db()
        self.assertEqual(opp.external_counterparty, self.ext_counterparty)
        self.assertIsNone(opp.organization)

    def test_non_supplier_organization_rejected_with_400(self):
        """
        If the target organization lacks Supplier capability (e.g. Buyer-only or Broker-only),
        conversion must fail cleanly with 400 Bad Request.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"

        # Attempt to use Buyer-only org as supplier
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "supplier_organization_id": str(self.buyer_org.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lacks Supplier capability", str(res.data))

        # Attempt to use Broker-only org as supplier
        payload["supplier_organization_id"] = str(self.broker_org.id)
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lacks Supplier capability", str(res.data))

    def test_internal_opportunity_with_buyer_only_org_rejected(self):
        """
        If a Supply Opportunity is captured with an internal organization that lacks
        Supplier capability, conversion must fail cleanly unless a valid Supplier org is specified.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1000.000"),
            unit="MT",
            source=OpportunitySource.OPERATOR_SOURCING,
        )
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lacks Supplier capability", str(res.data))

    def test_multi_capability_organization_accepted(self):
        """
        An organization with both Buyer and Supplier capabilities is accepted as a valid owner.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "supplier_organization_id": str(self.multi_org.id),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        self.assertEqual(listing.organization, self.multi_org)

    def test_nonexistent_or_inactive_supplier_organization_rejected(self):
        """
        Specifying a non-existent UUID or inactive organization must fail with 400 Bad Request.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"

        # 1. Non-existent UUID
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "supplier_organization_id": str(uuid.uuid4()),
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not exist or is inactive", str(res.data))

        # 2. Inactive organization
        inactive_org = Organization.objects.create(name="Inactive Supplier", country="AE", is_active=False)
        OrganizationCapability.objects.create(
            organization=inactive_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        payload["supplier_organization_id"] = str(inactive_org.id)
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not exist or is inactive", str(res.data))

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
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1200.000"),
            unit="MT",
            indicative_price=Decimal("360.00"),
            currency="USD",
            delivery_window_start=datetime.date(2026, 11, 1),
            delivery_window_end=datetime.date(2026, 11, 30),
            payment_terms="TT at sight",
            geography="Bandar Abbas, Iran",
            notes="Lead from broker referral.",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        record_contact_attempt(opp.id, type="CALL", notes="Initial discovery call", actor=self.operator)
        opp = qualify_opportunity(opp.id, expected_version=1, actor=self.operator)

        # Pre-conversion snapshot
        identifier_before = opp.identifier
        source_before = opp.source
        broker_before = opp.broker_id
        direction_before = opp.direction
        commodity_before = opp.commodity_id
        org_before = opp.organization_id
        contact_attempts_count = opp.contact_attempts.count()

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
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
    # 8. Relational Bidirectional Durability
    # -------------------------------------------------------------------------

    def test_bidirectional_relational_durability(self):
        """
        Confirm bidirectional relational navigation:
        - Opportunity -> converted Supply Listing (opp.converted_supply_listing)
        - Supply Listing -> source Opportunity (listing.source_opportunity and listing.source_opportunity_safe)
        - Both directions queryable via ORM filters.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        opp.refresh_from_db()

        self.assertEqual(opp.converted_supply_listing, listing)
        self.assertEqual(listing.source_opportunity, opp)
        self.assertEqual(listing.source_opportunity_safe, opp)

        # ORM filter queries
        self.assertTrue(SupplyListing.objects.filter(source_opportunity=opp).exists())
        self.assertTrue(Opportunity.objects.filter(converted_supply_listing=listing).exists())

    # -------------------------------------------------------------------------
    # 9. Single Transaction Atomic Rollback
    # -------------------------------------------------------------------------

    def test_atomic_rollback_on_supply_listing_creation_failure(self):
        """
        Confirm that if SupplyListing creation fails (e.g. invalid dynamic specifications),
        the whole PostgreSQL transaction rolls back:
        - No SupplyListing is created.
        - Opportunity status remains Qualified.
        - Opportunity version remains unchanged.
        - Opportunity converted_supply_listing remains None.
        """
        opp = self._create_qualified_supply_opportunity()
        initial_version = opp.version
        listing_count = SupplyListing.objects.count()

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        # Invalid spec: softening_point should be NUMBER, pass invalid string
        payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "specifications": {"penetration_grade": "60/70", "softening_point": "not_a_number"},
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Transaction rolled back completely
        self.assertEqual(SupplyListing.objects.count(), listing_count)
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(opp.version, initial_version)
        self.assertIsNone(opp.converted_supply_listing)

    # -------------------------------------------------------------------------
    # 10. Historical Referential Protection on Delete
    # -------------------------------------------------------------------------

    def test_historical_referential_protection_on_delete(self):
        """
        Confirm that neither deleting the converted SupplyListing nor deleting the converted
        Opportunity can succeed, protecting historical trade records and attribution.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        res = self.client.post(
            url,
            {"expected_version": opp.version, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        opp.refresh_from_db()

        # Attempt to delete SupplyListing -> raises ProtectedError
        with self.assertRaises(ProtectedError):
            listing.delete()

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
        Ensure clients cannot inject unauthorized lifecycle fields or bypass validation:
        status, version, activated_at, id, created_by, created_by_operator.
        """
        opp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        malicious_payload = {
            "expected_version": opp.version,
            "schema_version_id": str(self.schema_v1.id),
            "status": "active",
            "version": 999,
            "created_by_operator": False,
            "activated_at": "2026-01-01T00:00:00Z",
            "id": str(uuid.uuid4()),
        }
        res = self.client.post(url, malicious_payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        listing = SupplyListing.objects.get(id=res.data["supply_listing"]["id"])
        self.assertEqual(listing.status, SupplyListingStatus.DRAFT)
        self.assertEqual(listing.version, 1)
        self.assertTrue(listing.created_by_operator)
        self.assertIsNone(listing.activated_at)
        self.assertNotEqual(str(listing.id), malicious_payload["id"])

    # -------------------------------------------------------------------------
    # 12. Optimistic Concurrency Control
    # -------------------------------------------------------------------------

    def test_stale_expected_version_rejected_with_409_conflict(self):
        """
        Providing a stale expected_version must fail immediately with 409 Conflict.
        """
        opp = self._create_qualified_supply_opportunity()
        self.assertEqual(opp.version, 2)

        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{opp.id}/convert-to-supply-listing/"
        # Provide stale expected_version=1
        res = self.client.post(
            url,
            {"expected_version": 1, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version", str(res.data))

        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(opp.version, 2)
        self.assertIsNone(opp.converted_supply_listing)

    # -------------------------------------------------------------------------
    # 13. Authorization Matrix
    # -------------------------------------------------------------------------

    def test_conversion_authorization_matrix(self):
        """
        Verify strict authorization for Opportunity -> Supply Listing conversion:
        - Anonymous -> 401 Unauthorized
        - Buyer Owner -> 403 Forbidden
        - Supplier Owner (even of target supplier org!) -> 403 Forbidden
        - Broker Owner -> 403 Forbidden
        - Attributed Broker -> 403 Forbidden
        - Django Staff-only -> 403 Forbidden
        - Django Superuser-only -> 403 Forbidden
        - Product Admin -> 201 Created
        - Platform Operator -> 201 Created
        """
        # 1. Anonymous
        opp_anon = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=None)
        res_anon = self.client.post(
            f"/api/opportunities/opportunities/{opp_anon.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Buyer user
        opp_buyer = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.buyer_user)
        res_buyer = self.client.post(
            f"/api/opportunities/opportunities/{opp_buyer.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_buyer.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Supplier user (even though member of the supplier org)
        opp_supp = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.supplier_user)
        res_supp = self.client.post(
            f"/api/opportunities/opportunities/{opp_supp.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_supp.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Broker user
        opp_brk = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.broker_user)
        res_brk = self.client.post(
            f"/api/opportunities/opportunities/{opp_brk.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_brk.status_code, status.HTTP_403_FORBIDDEN)

        # 5. Attributed Broker
        opp_attr_brk = self._create_qualified_supply_opportunity(
            source=OpportunitySource.BROKER_REFERRAL, broker_id=self.broker_org.id
        )
        self.client.force_authenticate(user=self.broker_user)
        res_attr_brk = self.client.post(
            f"/api/opportunities/opportunities/{opp_attr_brk.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_attr_brk.status_code, status.HTTP_403_FORBIDDEN)

        # 6. Django Staff-only
        opp_staff = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.staff_only_user)
        res_staff = self.client.post(
            f"/api/opportunities/opportunities/{opp_staff.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_staff.status_code, status.HTTP_403_FORBIDDEN)

        # 7. Django Superuser-only
        opp_super = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.superuser_only_user)
        res_super = self.client.post(
            f"/api/opportunities/opportunities/{opp_super.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_super.status_code, status.HTTP_403_FORBIDDEN)

        # 8. Product Admin
        opp_admin = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.admin)
        res_admin = self.client.post(
            f"/api/opportunities/opportunities/{opp_admin.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_admin.status_code, status.HTTP_201_CREATED, res_admin.data)

        # 9. Operator
        opp_op = self._create_qualified_supply_opportunity()
        self.client.force_authenticate(user=self.operator)
        res_op = self.client.post(
            f"/api/opportunities/opportunities/{opp_op.id}/convert-to-supply-listing/",
            {"expected_version": 2, "schema_version_id": str(self.schema_v1.id)},
            format="json",
        )
        self.assertEqual(res_op.status_code, status.HTTP_201_CREATED, res_op.data)

    def test_non_existent_opportunity_returns_404(self):
        """Converting a non-existent Opportunity ID returns 404 Not Found."""
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{uuid.uuid4()}/convert-to-supply-listing/"
        res = self.client.post(url, {"expected_version": 1}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
