from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
)
from trade_hub.exceptions import RFQNotFoundError
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.visibility_service import (
    RFQVisibilityService,
    get_visible_rfq,
    get_visible_rfqs,
    has_global_visibility,
    is_rfq_visible,
    resolve_authoritative_organization,
)

User = get_user_model()


def _create_commodity(code: str, name_fa: str, name_en: str) -> tuple[CommodityDefinition, CommoditySchemaVersion]:
    commodity = CommodityDefinition.objects.create(
        code=code,
        name_fa=name_fa,
        name_en=name_en,
        is_active=True,
    )
    schema_v1 = CommoditySchemaVersion.objects.create(
        commodity=commodity,
        version=1,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT,
    )
    CommodityAttributeDefinition.objects.create(
        schema_version=schema_v1,
        key="grade",
        label_fa="درجه",
        label_en="Grade",
        data_type=CommodityAttributeDefinition.DataType.STRING,
        is_required=True,
        sort_order=1,
    )
    publish_schema(schema_v1, activate=True)
    return commodity, schema_v1


class BaseRFQVisibilityTestCase(TestCase):
    """Base test fixture setting up standard multi-commodity and multi-organization topology."""

    @classmethod
    def setUpTestData(cls):
        # 1. Multi-Commodity Setup (Generic)
        cls.bitumen, cls.bitumen_v1 = _create_commodity("bitumen", "قیر", "Bitumen")
        cls.base_oil, cls.base_oil_v1 = _create_commodity("base_oil", "روغن پایه", "Base Oil")
        cls.petrochem, cls.petrochem_v1 = _create_commodity("petrochem", "پتروشیمی", "Petrochemical")

        # 2. Owning Buyer Organization
        cls.buyer_org = Organization.objects.create(
            name="Gulf Petroleum Buyer",
            registration_identifier="REG-BUYER-001",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        cls.buyer_user = User.objects.create_user(email="buyer_owner@gulf.local", password="password123")
        cls.buyer_membership = OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        cls.buyer_viewer = User.objects.create_user(email="buyer_viewer@gulf.local", password="password123")
        OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # 3. Foreign Buyer-Only Organization
        cls.foreign_buyer_org = Organization.objects.create(
            name="Foreign Buyer Only",
            registration_identifier="REG-BUYER-002",
            country="TR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.foreign_buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        cls.foreign_buyer_user = User.objects.create_user(email="foreign_buyer@other.local", password="password123")
        OrganizationMembership.objects.create(
            organization=cls.foreign_buyer_org,
            user=cls.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 4. Supplier Organization operating in Bitumen
        cls.supplier_org = Organization.objects.create(
            name="National Bitumen Supplier",
            registration_identifier="REG-SUPPLIER-001",
            country="OM",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=cls.supplier_org,
            commodity=cls.bitumen,
        )
        cls.supplier_user = User.objects.create_user(email="supplier_owner@ombitumen.local", password="password123")
        OrganizationMembership.objects.create(
            organization=cls.supplier_org,
            user=cls.supplier_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 5. Broker Organization operating in Bitumen and Base Oil
        cls.broker_org = Organization.objects.create(
            name="Global Trade Broker",
            registration_identifier="REG-BROKER-001",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationCommodity.objects.create(
            organization=cls.broker_org,
            commodity=cls.bitumen,
        )
        OrganizationCommodity.objects.create(
            organization=cls.broker_org,
            commodity=cls.base_oil,
        )
        cls.broker_user = User.objects.create_user(email="broker_owner@globaltrade.local", password="password123")
        OrganizationMembership.objects.create(
            organization=cls.broker_org,
            user=cls.broker_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 6. Supplier operating ONLY in Base Oil
        cls.base_oil_supplier_org = Organization.objects.create(
            name="Base Oil Specialist Supplier",
            registration_identifier="REG-SUPPLIER-002",
            country="SA",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.base_oil_supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=cls.base_oil_supplier_org,
            commodity=cls.base_oil,
        )
        cls.base_oil_supplier_user = User.objects.create_user(
            email="base_oil_supplier@spec.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.base_oil_supplier_org,
            user=cls.base_oil_supplier_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 7. Multi-role organization (Both Supplier and Broker, operating in Bitumen)
        cls.multi_cap_org = Organization.objects.create(
            name="Integrated Supplier & Broker Corp",
            registration_identifier="REG-MULTI-001",
            country="QA",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.multi_cap_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCapability.objects.create(
            organization=cls.multi_cap_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationCommodity.objects.create(
            organization=cls.multi_cap_org,
            commodity=cls.bitumen,
        )
        cls.multi_cap_user = User.objects.create_user(email="multi_owner@integrated.local", password="password123")
        OrganizationMembership.objects.create(
            organization=cls.multi_cap_org,
            user=cls.multi_cap_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 8. Platform System Roles
        cls.operator_user = User.objects.create_user(email="operator@platform.local", password="password123")
        SystemRoleAssignment.objects.create(
            user=cls.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        cls.admin_user = User.objects.create_user(email="admin@platform.local", password="password123")
        SystemRoleAssignment.objects.create(
            user=cls.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # 9. Django Staff / Superuser without Platform System Roles
        cls.django_staff_user = User.objects.create_user(
            email="staff_only@platform.local", password="password123", is_staff=True
        )
        cls.django_superuser = User.objects.create_superuser(
            email="superuser_only@platform.local", password="password123"
        )

    def _create_rfq(
        self,
        *,
        organization: Organization | None = None,
        commodity: CommodityDefinition | None = None,
        schema_version: CommoditySchemaVersion | None = None,
        visibility: str = RFQVisibility.PUBLIC,
        status: str = RFQStatus.PUBLISHED,
        specifications: dict | None = None,
    ) -> RFQ:
        org = organization or self.buyer_org
        comm = commodity or self.bitumen
        s_ver = schema_version or self.bitumen_v1
        specs = specifications or {"grade": "60/70"}
        return RFQ.objects.create(
            organization=org,
            commodity=comm,
            schema_version=s_ver,
            specifications=specs,
            quantity=Decimal("500.000"),
            unit="MT",
            currency="USD",
            visibility=visibility,
            status=status,
        )


class RFQVisibilityPublicTierTests(BaseRFQVisibilityTestCase):
    """Test matrix for Public visibility tier."""

    def setUp(self):
        super().setUp()
        self.public_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.PUBLISHED,
        )

    def test_owner_can_see_public_rfq(self):
        """Owning organization can always see its own public RFQ."""
        visible = get_visible_rfqs(self.buyer_user, self.buyer_org)
        self.assertIn(self.public_rfq, visible)
        retrieved = get_visible_rfq(self.public_rfq.id, self.buyer_user, self.buyer_org)
        self.assertEqual(retrieved.id, self.public_rfq.id)
        self.assertTrue(is_rfq_visible(self.public_rfq, self.buyer_user, self.buyer_org))

    def test_supplier_can_see_public_rfq(self):
        """External organization with Supplier capability can see published public RFQ."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertIn(self.public_rfq, visible)
        retrieved = get_visible_rfq(self.public_rfq.id, self.supplier_user, self.supplier_org)
        self.assertEqual(retrieved.id, self.public_rfq.id)
        self.assertTrue(is_rfq_visible(self.public_rfq, self.supplier_user, self.supplier_org))

    def test_broker_can_see_public_rfq(self):
        """External organization with Broker capability can see published public RFQ."""
        visible = get_visible_rfqs(self.broker_user, self.broker_org)
        self.assertIn(self.public_rfq, visible)
        retrieved = get_visible_rfq(self.public_rfq.id, self.broker_user, self.broker_org)
        self.assertEqual(retrieved.id, self.public_rfq.id)
        self.assertTrue(is_rfq_visible(self.public_rfq, self.broker_user, self.broker_org))

    def test_foreign_buyer_only_cannot_see_public_rfq(self):
        """External organization with only Buyer capability cannot see external public RFQ."""
        visible = get_visible_rfqs(self.foreign_buyer_user, self.foreign_buyer_org)
        self.assertNotIn(self.public_rfq, visible)
        self.assertFalse(is_rfq_visible(self.public_rfq, self.foreign_buyer_user, self.foreign_buyer_org))
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.public_rfq.id, self.foreign_buyer_user, self.foreign_buyer_org)


class RFQVisibilityNetworkTierTests(BaseRFQVisibilityTestCase):
    """Test matrix for Network visibility tier and OrganizationCommodity matching."""

    def setUp(self):
        super().setUp()
        self.bitumen_network_rfq = self._create_rfq(
            commodity=self.bitumen,
            schema_version=self.bitumen_v1,
            visibility=RFQVisibility.NETWORK,
            status=RFQStatus.PUBLISHED,
        )
        self.base_oil_network_rfq = self._create_rfq(
            commodity=self.base_oil,
            schema_version=self.base_oil_v1,
            visibility=RFQVisibility.NETWORK,
            status=RFQStatus.PUBLISHED,
            specifications={"grade": "SN500"},
        )
        self.petrochem_network_rfq = self._create_rfq(
            commodity=self.petrochem,
            schema_version=self.petrochem_v1,
            visibility=RFQVisibility.NETWORK,
            status=RFQStatus.PUBLISHED,
            specifications={"grade": "White Spirit"},
        )

    def test_owner_can_see_network_rfq(self):
        """Owning organization can always see its own network RFQ."""
        visible = get_visible_rfqs(self.buyer_user, self.buyer_org)
        self.assertIn(self.bitumen_network_rfq, visible)
        self.assertIn(self.base_oil_network_rfq, visible)

    def test_supplier_with_matching_commodity_can_see_network_rfq(self):
        """Supplier with OrganizationCommodity matching RFQ commodity can see network RFQ."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertIn(self.bitumen_network_rfq, visible)
        retrieved = get_visible_rfq(self.bitumen_network_rfq.id, self.supplier_user, self.supplier_org)
        self.assertEqual(retrieved.id, self.bitumen_network_rfq.id)

    def test_supplier_with_wrong_commodity_cannot_see_network_rfq(self):
        """Supplier operating in Bitumen cannot see Network RFQ for Base Oil."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertNotIn(self.base_oil_network_rfq, visible)
        self.assertFalse(is_rfq_visible(self.base_oil_network_rfq, self.supplier_user, self.supplier_org))
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.base_oil_network_rfq.id, self.supplier_user, self.supplier_org)

    def test_broker_with_matching_commodity_can_see_network_rfqs(self):
        """Broker operating in Bitumen and Base Oil sees both matching network RFQs."""
        visible = get_visible_rfqs(self.broker_user, self.broker_org)
        self.assertIn(self.bitumen_network_rfq, visible)
        self.assertIn(self.base_oil_network_rfq, visible)

    def test_broker_with_unmatched_commodity_cannot_see_network_rfq(self):
        """Broker not operating in Petrochemical cannot see Petrochemical network RFQ."""
        visible = get_visible_rfqs(self.broker_user, self.broker_org)
        self.assertNotIn(self.petrochem_network_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.petrochem_network_rfq.id, self.broker_user, self.broker_org)

    def test_buyer_only_foreign_org_cannot_see_network_rfq(self):
        """Buyer-only foreign org cannot see network RFQs even if associated with commodity."""
        OrganizationCommodity.objects.create(
            organization=self.foreign_buyer_org,
            commodity=self.bitumen,
        )
        visible = get_visible_rfqs(self.foreign_buyer_user, self.foreign_buyer_org)
        self.assertNotIn(self.bitumen_network_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.bitumen_network_rfq.id, self.foreign_buyer_user, self.foreign_buyer_org)

    def test_multi_capability_and_multi_commodity_no_duplicates(self):
        """Organization with both Supplier and Broker capabilities and multiple commodities returns no duplicate RFQ rows."""
        # Ensure multi_cap_org has dual capabilities and operates in bitumen
        visible = list(get_visible_rfqs(self.multi_cap_user, self.multi_cap_org))
        ids = [rfq.id for rfq in visible]
        self.assertEqual(len(ids), len(set(ids)), "QuerySet returned duplicate RFQ rows.")
        self.assertIn(self.bitumen_network_rfq, visible)


class RFQVisibilityPrivateTierTests(BaseRFQVisibilityTestCase):
    """Test matrix for Private visibility tier."""

    def setUp(self):
        super().setUp()
        self.private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )

    def test_owner_can_see_private_rfq(self):
        """Owning buyer organization can see its own private RFQ."""
        visible = get_visible_rfqs(self.buyer_user, self.buyer_org)
        self.assertIn(self.private_rfq, visible)
        retrieved = get_visible_rfq(self.private_rfq.id, self.buyer_user, self.buyer_org)
        self.assertEqual(retrieved.id, self.private_rfq.id)

    def test_unrelated_supplier_cannot_see_private_rfq(self):
        """Unrelated supplier cannot see uninvited private RFQ."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertNotIn(self.private_rfq, visible)
        self.assertFalse(is_rfq_visible(self.private_rfq, self.supplier_user, self.supplier_org))
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.supplier_user, self.supplier_org)

    def test_unrelated_broker_cannot_see_private_rfq(self):
        """Unrelated broker cannot see uninvited private RFQ."""
        visible = get_visible_rfqs(self.broker_user, self.broker_org)
        self.assertNotIn(self.private_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.broker_user, self.broker_org)

    def test_operator_can_see_private_rfq(self):
        """Platform Operator can see private RFQs across all organizations."""
        visible = get_visible_rfqs(self.operator_user)
        self.assertIn(self.private_rfq, visible)
        retrieved = get_visible_rfq(self.private_rfq.id, self.operator_user)
        self.assertEqual(retrieved.id, self.private_rfq.id)
        self.assertTrue(is_rfq_visible(self.private_rfq, self.operator_user))

    def test_admin_can_see_private_rfq(self):
        """Product Admin can see private RFQs across all organizations."""
        visible = get_visible_rfqs(self.admin_user)
        self.assertIn(self.private_rfq, visible)
        retrieved = get_visible_rfq(self.private_rfq.id, self.admin_user)
        self.assertEqual(retrieved.id, self.private_rfq.id)


class RFQVisibilityLifecycleInteractionTests(BaseRFQVisibilityTestCase):
    """Test matrix for lifecycle status interaction (Draft, Cancelled, Closed vs External Discovery)."""

    def setUp(self):
        super().setUp()
        self.draft_public_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.DRAFT,
        )
        self.draft_network_rfq = self._create_rfq(
            visibility=RFQVisibility.NETWORK,
            status=RFQStatus.DRAFT,
        )
        self.draft_private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.DRAFT,
        )
        self.cancelled_public_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.CANCELLED,
        )
        self.closed_public_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.CLOSED,
        )

    def test_owner_can_see_own_draft_and_non_published_rfqs(self):
        """Owning buyer organization can inspect own RFQs in Draft, Cancelled, and Closed states."""
        visible = get_visible_rfqs(self.buyer_user, self.buyer_org)
        self.assertIn(self.draft_public_rfq, visible)
        self.assertIn(self.draft_network_rfq, visible)
        self.assertIn(self.draft_private_rfq, visible)
        self.assertIn(self.cancelled_public_rfq, visible)
        self.assertIn(self.closed_public_rfq, visible)

    def test_foreign_supplier_cannot_see_draft_rfq(self):
        """External Supplier cannot see Draft RFQ in list or detail lookup."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertNotIn(self.draft_public_rfq, visible)
        self.assertNotIn(self.draft_network_rfq, visible)
        self.assertNotIn(self.draft_private_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.draft_public_rfq.id, self.supplier_user, self.supplier_org)

    def test_foreign_broker_cannot_see_draft_rfq(self):
        """External Broker cannot see Draft RFQ in list or detail lookup."""
        visible = get_visible_rfqs(self.broker_user, self.broker_org)
        self.assertNotIn(self.draft_public_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.draft_public_rfq.id, self.broker_user, self.broker_org)

    def test_foreign_supplier_cannot_discover_cancelled_or_closed_rfqs(self):
        """External discovery excludes non-published (cancelled, closed) RFQs."""
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertNotIn(self.cancelled_public_rfq, visible)
        self.assertNotIn(self.closed_public_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.cancelled_public_rfq.id, self.supplier_user, self.supplier_org)

    def test_operator_can_see_draft_and_non_published_rfqs(self):
        """Operator has global visibility into Draft, Cancelled, and Closed RFQs."""
        visible = get_visible_rfqs(self.operator_user)
        self.assertIn(self.draft_public_rfq, visible)
        self.assertIn(self.draft_network_rfq, visible)
        self.assertIn(self.cancelled_public_rfq, visible)
        self.assertIn(self.closed_public_rfq, visible)

    def test_admin_can_see_draft_and_non_published_rfqs(self):
        """Product Admin has global visibility into Draft, Cancelled, and Closed RFQs."""
        visible = get_visible_rfqs(self.admin_user)
        self.assertIn(self.draft_public_rfq, visible)
        self.assertIn(self.closed_public_rfq, visible)


class RFQVisibilityRoleAndCapabilityIsolationTests(BaseRFQVisibilityTestCase):
    """Test matrix for separation of Product Roles, Django Flags, and Cross-Org Capabilities."""

    def setUp(self):
        super().setUp()
        self.public_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.PUBLISHED,
        )
        self.private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )

    def test_django_staff_without_system_role_has_no_global_authority(self):
        """Django is_staff alone does NOT grant global operational access."""
        self.assertFalse(has_global_visibility(self.django_staff_user))
        visible = get_visible_rfqs(self.django_staff_user)
        self.assertEqual(visible.count(), 0)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.django_staff_user)

    def test_django_superuser_without_system_role_has_no_global_authority(self):
        """Django is_superuser alone does NOT grant global operational access."""
        self.assertFalse(has_global_visibility(self.django_superuser))
        visible = get_visible_rfqs(self.django_superuser)
        self.assertEqual(visible.count(), 0)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.django_superuser)

    def test_capability_in_another_organization_cannot_grant_access(self):
        """
        User belonging to Org A (Buyer only) and Org B (Supplier).
        When operating in context of Org A, Org B's Supplier capability CANNOT grant access to Public RFQs.
        """
        dual_user = User.objects.create_user(email="dual_user@test.local", password="password123")
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=dual_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=dual_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Context: Org A (foreign_buyer_org - Buyer only) -> Public RFQ hidden
        visible_as_buyer = get_visible_rfqs(dual_user, self.foreign_buyer_org)
        self.assertNotIn(self.public_rfq, visible_as_buyer)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.public_rfq.id, dual_user, self.foreign_buyer_org)

        # Context: Org B (supplier_org - Supplier) -> Public RFQ visible
        visible_as_supplier = get_visible_rfqs(dual_user, self.supplier_org)
        self.assertIn(self.public_rfq, visible_as_supplier)
        self.assertEqual(get_visible_rfq(self.public_rfq.id, dual_user, self.supplier_org).id, self.public_rfq.id)

    def test_member_and_viewer_roles_do_not_expand_organization_visibility(self):
        """Viewer in a Buyer-only organization cannot see Public or Network RFQs of other orgs."""
        foreign_viewer = User.objects.create_user(email="foreign_viewer@test.local", password="password123")
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=foreign_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )
        visible = get_visible_rfqs(foreign_viewer, self.foreign_buyer_org)
        self.assertNotIn(self.public_rfq, visible)
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.public_rfq.id, foreign_viewer, self.foreign_buyer_org)

    def test_untrusted_client_organization_id_is_rejected(self):
        """Passing an organization ID where the user has no active membership returns empty scope."""
        # supplier_user tries to claim buyer_org
        authoritative_org = resolve_authoritative_organization(self.supplier_user, self.buyer_org.id)
        self.assertIsNone(authoritative_org)

        visible = get_visible_rfqs(self.supplier_user, self.buyer_org.id)
        # Should not grant buyer_org's ownership visibility
        self.assertNotIn(self.private_rfq, visible)

    def test_inactive_organization_membership_is_rejected(self):
        """Inactive membership in an organization confers no visibility."""
        inactive_user = User.objects.create_user(email="inactive_user@test.local", password="password123")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=inactive_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=False,  # Inactive
        )
        visible = get_visible_rfqs(inactive_user, self.supplier_org)
        self.assertEqual(visible.count(), 0)

    def test_inactive_organization_is_rejected(self):
        """Membership in an inactive organization confers no visibility."""
        inactive_org = Organization.objects.create(name="Inactive Org", is_active=False)
        OrganizationCapability.objects.create(
            organization=inactive_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        user = User.objects.create_user(email="user@inactive.local", password="password123")
        OrganizationMembership.objects.create(
            organization=inactive_org,
            user=user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        visible = get_visible_rfqs(user, inactive_org)
        self.assertEqual(visible.count(), 0)


class RFQVisibilityDirectLookupAndPrivacyTests(BaseRFQVisibilityTestCase):
    """Test that direct ID lookups enforce strict hidden-resource parity with list visibility."""

    def setUp(self):
        super().setUp()
        self.private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )
        self.draft_rfq = self._create_rfq(
            visibility=RFQVisibility.PUBLIC,
            status=RFQStatus.DRAFT,
        )

    def test_nonexistent_and_hidden_rfqs_raise_identical_exception(self):
        """Non-existent UUID and hidden UUID raise the exact same RFQNotFoundError."""
        random_id = uuid.uuid4()
        with self.assertRaises(RFQNotFoundError) as exc_nonexistent:
            get_visible_rfq(random_id, self.supplier_user, self.supplier_org)

        with self.assertRaises(RFQNotFoundError) as exc_hidden:
            get_visible_rfq(self.private_rfq.id, self.supplier_user, self.supplier_org)

        self.assertEqual(type(exc_nonexistent.exception), type(exc_hidden.exception))

    def test_invalid_uuid_raises_rfq_not_found_error(self):
        """Malformed UUID string raises RFQNotFoundError rather than ValueError."""
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq("not-a-valid-uuid", self.supplier_user, self.supplier_org)

    def test_unauthenticated_direct_lookup_raises_rfq_not_found(self):
        """Anonymous user direct lookup raises RFQNotFoundError."""
        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, None)


class RFQVisibilityT0506BoundaryTests(BaseRFQVisibilityTestCase):
    """Test T0506 invitation boundary hook without prematurely introducing production invitation tables."""

    def setUp(self):
        super().setUp()
        self.invited_private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )
        self.uninvited_private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )

    def tearDown(self):
        # Reset invitation resolver
        RFQVisibilityService.register_invitation_resolver(None)
        super().tearDown()

    def test_t0506_invitation_resolver_integrates_cleanly(self):
        """
        Demonstrate that when T0506 supplies an invitation collaborator,
        the visibility service includes invited Private RFQs without modifying core query structure.
        """
        # Initially, supplier cannot see either private RFQ
        self.assertFalse(is_rfq_visible(self.invited_private_rfq, self.supplier_user, self.supplier_org))
        self.assertFalse(is_rfq_visible(self.uninvited_private_rfq, self.supplier_user, self.supplier_org))

        # Register an in-memory collaborator representing T0506 invitation resolution
        def mock_invitation_resolver(organization: Organization) -> models.Q:
            if organization.id == self.supplier_org.id:
                return models.Q(id=self.invited_private_rfq.id)
            return models.Q(pk__in=[])

        RFQVisibilityService.register_invitation_resolver(mock_invitation_resolver)

        # Supplier can now see the invited private RFQ, but NOT the uninvited one
        visible = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertIn(self.invited_private_rfq, visible)
        self.assertNotIn(self.uninvited_private_rfq, visible)

        retrieved = get_visible_rfq(self.invited_private_rfq.id, self.supplier_user, self.supplier_org)
        self.assertEqual(retrieved.id, self.invited_private_rfq.id)

        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.uninvited_private_rfq.id, self.supplier_user, self.supplier_org)


class RFQVisibilityManagerAndQuerySetTests(BaseRFQVisibilityTestCase):
    """Verify RFQ.objects.visible_to QuerySet method parity."""

    def setUp(self):
        super().setUp()
        self.public_rfq = self._create_rfq(visibility=RFQVisibility.PUBLIC, status=RFQStatus.PUBLISHED)
        self.private_rfq = self._create_rfq(visibility=RFQVisibility.PRIVATE, status=RFQStatus.PUBLISHED)

    def test_rfq_objects_visible_to_matches_service(self):
        """RFQ.objects.visible_to delegates directly to RFQVisibilityService."""
        qs_via_manager = RFQ.objects.visible_to(self.supplier_user, self.supplier_org)
        qs_via_service = get_visible_rfqs(self.supplier_user, self.supplier_org)
        self.assertQuerySetEqual(qs_via_manager, qs_via_service, ordered=False)

    def test_chained_filter_with_visible_to(self):
        """visible_to works when chained with other QuerySet filters."""
        qs = RFQ.objects.filter(commodity=self.bitumen).visible_to(self.supplier_user, self.supplier_org)
        self.assertIn(self.public_rfq, qs)
        self.assertNotIn(self.private_rfq, qs)
