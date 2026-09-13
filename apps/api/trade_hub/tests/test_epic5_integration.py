from decimal import Decimal

from django.test import TestCase
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
    OrganizationCommodity,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification
from trade_hub.models import (
    RFQ,
    RFQInvitation,
    RFQInvitationStatus,
    RFQStatus,
    RFQVisibility,
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)


class Epic5IntegrationTests(TestCase):
    """
    Comprehensive Epic 5 integration test suite.
    Validates end-to-end Hero Slices (Scenarios A through E), multi-commodity genericity,
    historical schema preservation, privacy/IDOR attacks, query performance (N+1 safety),
    and detail/list parity across Demand and Supply domains.
    """

    def setUp(self):
        self.client = APIClient()

        # 1. Commodities setup: Bitumen & Base Oil
        self.bitumen = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen",
            is_active=True,
        )
        self.bitumen_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.bitumen_v1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=False,
            sort_order=2,
        )
        publish_schema(self.bitumen_v1, activate=True)

        self.base_oil = CommodityDefinition.objects.create(
            code="base_oil",
            name_fa="روغن پایه",
            name_en="Base Oil",
            is_active=True,
        )
        self.base_oil_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.base_oil,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.base_oil_v1,
            key="viscosity_index",
            label_fa="شاخص گرانروی",
            label_en="Viscosity Index",
            data_type=CommodityAttributeDefinition.DataType.INTEGER,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.base_oil_v1, activate=True)

        # 2. Organizations & Capabilities
        # Buyer Org
        self.buyer_org = Organization.objects.create(
            name="Pars Procurement Co",
            registration_identifier="REG-BUYER-01",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationVerification.objects.create(
            organization=self.buyer_org,
            status="verified",
        )

        # Invited Supplier Org
        self.invited_supplier_org = Organization.objects.create(
            name="National Bitumen Supply",
            registration_identifier="REG-SUPP-INVITED-02",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.invited_supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=self.invited_supplier_org,
            commodity=self.bitumen,
        )
        OrganizationVerification.objects.create(
            organization=self.invited_supplier_org,
            status="verified",
        )

        # Uninvited Supplier Org
        self.uninvited_supplier_org = Organization.objects.create(
            name="Caspian Petroleum Trade",
            registration_identifier="REG-SUPP-UNINV-03",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.uninvited_supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=self.uninvited_supplier_org,
            commodity=self.bitumen,
        )

        # Broker Org
        self.broker_org = Organization.objects.create(
            name="Gulf Commodity Brokers",
            registration_identifier="REG-BROKER-04",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        # 3. Users & Memberships
        # Buyer Owner
        self.buyer_user = User.objects.create_user(
            email="buyer_owner@parsprocure.com",
            password="TestPassword123!",
        )
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Buyer Member (Read-only / No mutation)
        self.buyer_member = User.objects.create_user(
            email="buyer_member@parsprocure.com",
            password="TestPassword123!",
        )
        OrganizationMembership.objects.create(
            user=self.buyer_member,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # Invited Supplier Owner
        self.invited_supplier_user = User.objects.create_user(
            email="invited@natbitumen.com",
            password="TestPassword123!",
        )
        OrganizationMembership.objects.create(
            user=self.invited_supplier_user,
            organization=self.invited_supplier_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Uninvited Supplier Owner
        self.uninvited_supplier_user = User.objects.create_user(
            email="uninvited@caspianpetro.com",
            password="TestPassword123!",
        )
        OrganizationMembership.objects.create(
            user=self.uninvited_supplier_user,
            organization=self.uninvited_supplier_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Broker User
        self.broker_user = User.objects.create_user(
            email="broker@gulfbrokers.com",
            password="TestPassword123!",
        )
        OrganizationMembership.objects.create(
            user=self.broker_user,
            organization=self.broker_org,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Platform Operator
        self.operator_user = User.objects.create_user(
            email="operator@platform.internal",
            password="TestPassword123!",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # Django Staff Only (No Operator/Admin SystemRole)
        self.staff_only_user = User.objects.create_user(
            email="staff@internal.test",
            password="TestPassword123!",
            is_staff=True,
        )

    # -------------------------------------------------------------------------
    # Scenario A: Buyer / RFQ
    # -------------------------------------------------------------------------
    def test_scenario_a_buyer_creates_and_publishes_private_rfq(self):
        """
        Scenario A:
        1. Buyer Owner logs in.
        2. Creates RFQ Draft with dynamic Bitumen specs.
        3. Configures commercial & delivery terms, sets Private visibility.
        4. Invites Supplier Organization.
        5. Publishes RFQ (advancing version 1 -> 2).
        Assert persisted authoritative state.
        """
        self.client.force_authenticate(user=self.buyer_user)

        # 1 & 2 & 3: Create RFQ Draft
        rfq_payload = {
            "commodity_id": str(self.bitumen.id),
            "schema_version_id": str(self.bitumen_v1.id),
            "quantity": "1200.000",
            "unit": "MT",
            "specifications": {
                "penetration_grade": "60/70",
                "softening_point": 49.5,
            },
            "target_price": "460.00",
            "currency": "USD",
            "payment_terms": "LC at sight",
            "incoterm": "FOB",
            "origin": "Bandar Abbas",
            "destination": "Jebel Ali",
            "delivery_window_start": "2026-10-10",
            "delivery_window_end": "2026-10-25",
            "submission_deadline": "2026-10-01T12:00:00Z",
            "visibility": "private",
        }

        create_res = self.client.post(
            "/api/trade-hub/rfqs/",
            rfq_payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        rfq_id = create_res.data["id"]
        self.assertEqual(create_res.data["status"], "draft")
        self.assertEqual(create_res.data["version"], 1)

        # 4: Invite Supplier
        invite_res = self.client.post(
            f"/api/trade-hub/rfqs/{rfq_id}/invitations/",
            {"organization_id": str(self.invited_supplier_org.id)},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(invite_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(invite_res.data["organization"]["id"], str(self.invited_supplier_org.id))
        self.assertEqual(invite_res.data["status"], "invited")

        # 5: Publish RFQ
        publish_res = self.client.post(
            f"/api/trade-hub/rfqs/{rfq_id}/publish/",
            {"expected_version": 1},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(publish_res.status_code, status.HTTP_200_OK)
        self.assertEqual(publish_res.data["status"], "published")
        self.assertEqual(publish_res.data["version"], 2)

        # Assert authoritative DB state
        rfq = RFQ.objects.get(id=rfq_id)
        self.assertEqual(rfq.status, RFQStatus.PUBLISHED)
        self.assertEqual(rfq.version, 2)
        self.assertEqual(rfq.visibility, RFQVisibility.PRIVATE)
        self.assertIsNotNone(rfq.published_at)
        self.assertEqual(rfq.specifications["penetration_grade"], "60/70")
        self.assertEqual(Decimal(str(rfq.quantity)), Decimal("1200.000"))

    # -------------------------------------------------------------------------
    # Scenario B: Invited Supplier Discovery & Detail
    # -------------------------------------------------------------------------
    def test_scenario_b_invited_supplier_access_and_privacy(self):
        """
        Scenario B:
        1. Authenticate as Invited Supplier.
        2. Assert Private RFQ appears in Demand discovery.
        3. Assert direct UUID detail/workspace succeeds.
        4. Assert dynamic specifications serialize correctly.
        5. Assert Invited Supplier CANNOT enumerate competing invitees.
        """
        # Create published private RFQ with 2 invitees
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.0},
            quantity=Decimal("1500.000"),
            unit="MT",
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
            version=2,
            created_by=self.buyer_user,
        )
        RFQInvitation.objects.create(
            rfq=rfq,
            organization=self.invited_supplier_org,
            status=RFQInvitationStatus.INVITED,
            invited_by=self.buyer_user,
        )
        # Add a competing invitee
        competing_org = Organization.objects.create(
            name="Competing Supplier",
            registration_identifier="REG-COMP-99",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=competing_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        RFQInvitation.objects.create(
            rfq=rfq,
            organization=competing_org,
            status=RFQInvitationStatus.INVITED,
            invited_by=self.buyer_user,
        )

        # Authenticate as Invited Supplier
        self.client.force_authenticate(user=self.invited_supplier_user)

        # 2: Demand discovery list
        list_res = self.client.get(
            "/api/trade-hub/rfqs/",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in list_res.data["results"]]
        self.assertIn(str(rfq.id), ids)

        # 3 & 4: Direct UUID detail and dynamic specs
        detail_res = self.client.get(
            f"/api/trade-hub/rfqs/{rfq.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data["specifications"]["penetration_grade"], "60/70")
        self.assertEqual(detail_res.data["commodity_code"], "bitumen")

        # 5: Privacy attack: Supplier cannot enumerate participants
        invitations_res = self.client.get(
            f"/api/trade-hub/rfqs/{rfq.id}/invitations/",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(invitations_res.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # Scenario C: Uninvited Supplier Discovery & Detail Exclusion
    # -------------------------------------------------------------------------
    def test_scenario_c_uninvited_supplier_excluded(self):
        """
        Scenario C:
        1. Private RFQ exists without invitation to uninvited supplier.
        2. Authenticate as Uninvited Supplier.
        3. Assert Private RFQ is excluded from Demand discovery.
        4. Assert direct guessed UUID detail returns 404 (detail/list parity).
        """
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
            version=2,
            created_by=self.buyer_user,
        )

        self.client.force_authenticate(user=self.uninvited_supplier_user)

        # 3: List exclusion
        list_res = self.client.get(
            "/api/trade-hub/rfqs/",
            HTTP_X_ORGANIZATION_ID=str(self.uninvited_supplier_org.id),
        )
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in list_res.data["results"]]
        self.assertNotIn(str(rfq.id), ids)

        # 4: Direct guessed detail returns 404
        detail_res = self.client.get(
            f"/api/trade-hub/rfqs/{rfq.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.uninvited_supplier_org.id),
        )
        self.assertEqual(detail_res.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # Scenario D: Supply Listing Creation & Activation
    # -------------------------------------------------------------------------
    def test_scenario_d_supplier_creates_and_activates_supply_listing(self):
        """
        Scenario D:
        1. Authenticate as Supplier Owner.
        2. Create Draft Supply Listing with dynamic Bitumen specs.
        3. Activate Supply Listing with optimistic concurrency.
        Assert persisted state is active with version 2.
        """
        self.client.force_authenticate(user=self.invited_supplier_user)

        supply_payload = {
            "commodity_id": str(self.bitumen.id),
            "schema_version_id": str(self.bitumen_v1.id),
            "quantity": "2500.000",
            "unit": "MT",
            "specifications": {
                "penetration_grade": "60/70",
                "softening_point": 50.0,
            },
            "indicative_price": "470.00",
            "currency": "USD",
            "payment_terms": "TT 30 days",
            "incoterm": "FOB",
            "origin": "Bandar Abbas",
            "availability_window_start": "2026-10-15",
            "availability_window_end": "2026-11-15",
            "visibility": "public",
        }

        create_res = self.client.post(
            "/api/trade-hub/supply-listings/",
            supply_payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        listing_id = create_res.data["id"]
        self.assertEqual(create_res.data["status"], "draft")
        self.assertEqual(create_res.data["version"], 1)

        # Activate listing
        activate_res = self.client.post(
            f"/api/trade-hub/supply-listings/{listing_id}/activate/",
            {"expected_version": 1},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(activate_res.status_code, status.HTTP_200_OK)
        self.assertEqual(activate_res.data["status"], "active")
        self.assertEqual(activate_res.data["version"], 2)

        listing = SupplyListing.objects.get(id=listing_id)
        self.assertEqual(listing.status, SupplyListingStatus.ACTIVE)
        self.assertEqual(listing.version, 2)
        self.assertIsNotNone(listing.activated_at)

    # -------------------------------------------------------------------------
    # Scenario E: Buyer / Broker Supply Discovery
    # -------------------------------------------------------------------------
    def test_scenario_e_buyer_and_broker_supply_discovery_parity(self):
        """
        Scenario E:
        1. Active Public Supply Listing and Draft Supply Listing exist.
        2. Buyer views Supply discovery: sees active listing, not draft.
        3. Direct detail parity: active listing returns 200, draft returns 404.
        4. Broker views Supply discovery: sees active listing.
        """
        active_listing = SupplyListing.objects.create(
            organization=self.invited_supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("2000.000"),
            unit="MT",
            visibility=SupplyListingVisibility.PUBLIC,
            status=SupplyListingStatus.ACTIVE,
            version=2,
            created_by=self.invited_supplier_user,
        )
        draft_listing = SupplyListing.objects.create(
            organization=self.invited_supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            visibility=SupplyListingVisibility.PUBLIC,
            status=SupplyListingStatus.DRAFT,
            version=1,
            created_by=self.invited_supplier_user,
        )

        # Buyer discovery
        self.client.force_authenticate(user=self.buyer_user)
        list_res = self.client.get(
            "/api/trade-hub/supply-listings/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in list_res.data["results"]]
        self.assertIn(str(active_listing.id), ids)
        self.assertNotIn(str(draft_listing.id), ids)

        # Buyer direct detail parity
        detail_active = self.client.get(
            f"/api/trade-hub/supply-listings/{active_listing.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(detail_active.status_code, status.HTTP_200_OK)

        detail_draft = self.client.get(
            f"/api/trade-hub/supply-listings/{draft_listing.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(detail_draft.status_code, status.HTTP_404_NOT_FOUND)

        # Broker discovery
        self.client.force_authenticate(user=self.broker_user)
        broker_list = self.client.get(
            "/api/trade-hub/supply-listings/",
            HTTP_X_ORGANIZATION_ID=str(self.broker_org.id),
        )
        self.assertEqual(broker_list.status_code, status.HTTP_200_OK)
        broker_ids = [item["id"] for item in broker_list.data["results"]]
        self.assertIn(str(active_listing.id), broker_ids)

    # -------------------------------------------------------------------------
    # Multi-Commodity Integration
    # -------------------------------------------------------------------------
    def test_multi_commodity_demand_and_supply_genericity(self):
        """
        Test that both Demand and Supply handle multiple commodities generically.
        Uses Base Oil (viscosity_index attribute) and Bitumen (penetration_grade attribute).
        Verifies no hard-coded Bitumen branches exist.
        """
        self.client.force_authenticate(user=self.buyer_user)

        # Buyer creates Base Oil RFQ
        baseoil_rfq_res = self.client.post(
            "/api/trade-hub/rfqs/",
            {
                "commodity_id": str(self.base_oil.id),
                "schema_version_id": str(self.base_oil_v1.id),
                "quantity": "500.000",
                "unit": "Barrels",
                "specifications": {"viscosity_index": 95},
                "visibility": "public",
            },
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(baseoil_rfq_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(baseoil_rfq_res.data["commodity_code"], "base_oil")
        self.assertEqual(baseoil_rfq_res.data["specifications"]["viscosity_index"], 95)

        # Publish Base Oil RFQ
        pub_res = self.client.post(
            f"/api/trade-hub/rfqs/{baseoil_rfq_res.data['id']}/publish/",
            {"expected_version": 1},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(pub_res.status_code, status.HTTP_200_OK)

        # Filter Demand discovery by commodity UUID
        filter_res = self.client.get(
            f"/api/trade-hub/rfqs/?commodity={self.base_oil.id}",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(filter_res.status_code, status.HTTP_200_OK)
        for item in filter_res.data["results"]:
            self.assertEqual(item["commodity_id"], str(self.base_oil.id))

    # -------------------------------------------------------------------------
    # Historical Schema Regression
    # -------------------------------------------------------------------------
    def test_historical_schema_regression(self):
        """
        Historical schema regression test:
        1. RFQ and Supply Listing are created against Bitumen Schema v1.
        2. Bitumen Schema v2 is published with new required attribute.
        3. Trade Hub discovery and direct detail continue to use and serialize v1.
        """
        # Create published RFQ under v1
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 48.0},
            quantity=Decimal("1000.000"),
            unit="MT",
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.PUBLISHED,
            version=2,
            created_by=self.buyer_user,
        )

        # Create active Supply Listing under v1
        listing = SupplyListing.objects.create(
            organization=self.invited_supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70", "softening_point": 49.0},
            quantity=Decimal("2000.000"),
            unit="MT",
            visibility=SupplyListingVisibility.PUBLIC,
            status=SupplyListingStatus.ACTIVE,
            version=2,
            created_by=self.invited_supplier_user,
        )

        # Create and publish Bitumen Schema v2
        bitumen_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.bitumen,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=bitumen_v2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=bitumen_v2,
            key="flash_point",
            label_fa="نقطه اشتعال",
            label_en="Flash Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=2,
        )
        publish_schema(bitumen_v2, activate=True)

        # Verify RFQ still preserves v1 schema binding
        self.client.force_authenticate(user=self.buyer_user)
        rfq_detail = self.client.get(
            f"/api/trade-hub/rfqs/{rfq.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(rfq_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(rfq_detail.data["schema_version_number"], 1)
        self.assertEqual(rfq_detail.data["schema_version_id"], str(self.bitumen_v1.id))

        # Verify Supply Listing still preserves v1 schema binding
        listing_detail = self.client.get(
            f"/api/trade-hub/supply-listings/{listing.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(listing_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(listing_detail.data["schema_version_number"], 1)
        self.assertEqual(listing_detail.data["schema_version_id"], str(self.bitumen_v1.id))

    # -------------------------------------------------------------------------
    # Privacy & Adversarial Probes
    # -------------------------------------------------------------------------
    def test_privacy_attacks_and_role_confusion(self):
        """
        Adversarial privacy probes:
        1. Foreign org cannot edit/publish an RFQ.
        2. Uninvited org cannot see Private RFQs in count or search filters.
        3. External drafts are completely invisible.
        4. Django staff user without Operator role cannot see private listings.
        """
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.DRAFT,
            version=1,
            created_by=self.buyer_user,
        )

        # 1. Foreign edit attempt
        self.client.force_authenticate(user=self.invited_supplier_user)
        patch_res = self.client.patch(
            f"/api/trade-hub/rfqs/{rfq.id}/",
            {"expected_version": 1, "quantity": "9999.000"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertIn(patch_res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # 2. Search leak attempt on private RFQ by uninvited organization
        RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
            version=2,
            origin="TopSecretPort",
            created_by=self.buyer_user,
        )

        self.client.force_authenticate(user=self.uninvited_supplier_user)
        search_res = self.client.get(
            "/api/trade-hub/rfqs/?search=TopSecretPort",
            HTTP_X_ORGANIZATION_ID=str(self.uninvited_supplier_org.id),
        )
        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        self.assertEqual(search_res.data["count"], 0)
        self.assertEqual(len(search_res.data["results"]), 0)

        # 3. External draft invisibility
        draft_supply = SupplyListing.objects.create(
            organization=self.invited_supplier_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            visibility=SupplyListingVisibility.PUBLIC,
            status=SupplyListingStatus.DRAFT,
            version=1,
            created_by=self.invited_supplier_user,
        )
        self.client.force_authenticate(user=self.buyer_user)
        draft_detail = self.client.get(
            f"/api/trade-hub/supply-listings/{draft_supply.id}/",
            HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
        )
        self.assertEqual(draft_detail.status_code, status.HTTP_404_NOT_FOUND)

        # 4. Django staff-only user confusion (staff != Operator/Admin)
        self.client.force_authenticate(user=self.staff_only_user)
        staff_res = self.client.get(f"/api/trade-hub/rfqs/{rfq.id}/")
        self.assertIn(staff_res.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # -------------------------------------------------------------------------
    # Query Performance (N+1 Safety)
    # -------------------------------------------------------------------------
    def test_trade_hub_discovery_query_efficiency(self):
        """
        Verify that Trade Hub discovery endpoints use set-based ORM queries (select_related,
        prefetch_related) and avoid N+1 query proliferation.
        """
        # Create 10 published RFQs
        for i in range(10):
            RFQ.objects.create(
                organization=self.buyer_org,
                commodity=self.bitumen,
                schema_version=self.bitumen_v1,
                specifications={"penetration_grade": "60/70"},
                quantity=Decimal("100.000") * (i + 1),
                unit="MT",
                visibility=RFQVisibility.PUBLIC,
                status=RFQStatus.PUBLISHED,
                version=2,
                origin=f"Port_{i}",
                created_by=self.buyer_user,
            )

        self.client.force_authenticate(user=self.invited_supplier_user)

        # Measure query count for 10 items (O(1) set-based query efficiency)
        with self.assertNumQueries(9):
            res = self.client.get(
                "/api/trade-hub/rfqs/",
                HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
            )
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertGreaterEqual(len(res.data["results"]), 10)

        # Create 10 active Supply Listings
        for i in range(10):
            SupplyListing.objects.create(
                organization=self.invited_supplier_org,
                commodity=self.bitumen,
                schema_version=self.bitumen_v1,
                specifications={"penetration_grade": "60/70"},
                quantity=Decimal("50.000") * (i + 1),
                unit="MT",
                visibility=SupplyListingVisibility.PUBLIC,
                status=SupplyListingStatus.ACTIVE,
                version=2,
                created_by=self.invited_supplier_user,
            )

        self.client.force_authenticate(user=self.buyer_user)
        with self.assertNumQueries(9):
            supply_res = self.client.get(
                "/api/trade-hub/supply-listings/",
                HTTP_X_ORGANIZATION_ID=str(self.buyer_org.id),
            )
            self.assertEqual(supply_res.status_code, status.HTTP_200_OK)
            self.assertGreaterEqual(len(supply_res.data["results"]), 10)

    # -------------------------------------------------------------------------
    # Discovery Filtering Test
    # -------------------------------------------------------------------------
    def test_discovery_filtering(self):
        """
        Verify search, status, origin, destination, and commodity filters
        on discovery endpoints.
        """
        rfq_bandar = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.PUBLISHED,
            version=2,
            origin="Bandar Abbas",
            destination="Jebel Ali",
            created_by=self.buyer_user,
        )
        rfq_singapore = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("2000.000"),
            unit="MT",
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.PUBLISHED,
            version=2,
            origin="Singapore",
            destination="Mumbai",
            created_by=self.buyer_user,
        )

        self.client.force_authenticate(user=self.invited_supplier_user)

        # Filter by origin
        res = self.client.get(
            "/api/trade-hub/rfqs/?origin=Bandar",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(rfq_bandar.id))

        # Filter by destination
        res_dest = self.client.get(
            "/api/trade-hub/rfqs/?destination=Mumbai",
            HTTP_X_ORGANIZATION_ID=str(self.invited_supplier_org.id),
        )
        self.assertEqual(res_dest.status_code, status.HTTP_200_OK)
        dest_results = res_dest.data["results"]
        self.assertEqual(len(dest_results), 1)
        self.assertEqual(dest_results[0]["id"], str(rfq_singapore.id))
