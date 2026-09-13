from decimal import Decimal
import threading
import time
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

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
from trade_hub.exceptions import (
    DuplicateInvitationError,
    InvalidInvitationStatusError,
    InvalidTransitionError,
    InviteeIneligibleError,
    InvitationNotFoundError,
    InvitationPermissionDeniedError,
    RFQNotFoundError,
)
from trade_hub.models import (
    RFQ,
    RFQInvitation,
    RFQInvitationStatus,
    RFQStatus,
    RFQVisibility,
)
from trade_hub.services import (
    close_rfq,
    create_invitation,
    decline_invitation,
    get_visible_rfq,
    get_visible_rfqs,
    mark_invitation_viewed,
)

User = get_user_model()


def _create_commodity(
    code: str = "bitumen",
) -> tuple[CommodityDefinition, CommoditySchemaVersion]:
    commodity, _ = CommodityDefinition.objects.get_or_create(
        code=code,
        defaults={"name_fa": "قیر", "name_en": "Bitumen", "is_active": True},
    )
    schema_v1, _ = CommoditySchemaVersion.objects.get_or_create(
        commodity=commodity,
        version=1,
        defaults={"status": CommoditySchemaVersion.SchemaStatus.DRAFT},
    )
    CommodityAttributeDefinition.objects.get_or_create(
        schema_version=schema_v1,
        key="penetration_grade",
        defaults={
            "label_fa": "درجه نفوذ",
            "label_en": "Penetration Grade",
            "data_type": CommodityAttributeDefinition.DataType.STRING,
            "is_required": True,
            "sort_order": 1,
        },
    )
    if schema_v1.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
        publish_schema(schema_v1, activate=True)
    return commodity, schema_v1


class BaseInvitationTestCase(TestCase):
    """Base test fixture setting up buyer, supplier, broker, and foreign organizations."""

    @classmethod
    def setUpTestData(cls):
        cls.commodity, cls.schema_version = _create_commodity("bitumen")

        # 1. Owning Buyer Organization
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

        cls.buyer_owner = User.objects.create_user(
            email="buyer_owner@gulf.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        cls.buyer_manager = User.objects.create_user(
            email="buyer_mgr@gulf.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_manager,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        cls.buyer_member = User.objects.create_user(
            email="buyer_mem@gulf.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        cls.buyer_viewer = User.objects.create_user(
            email="buyer_view@gulf.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.buyer_org,
            user=cls.buyer_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # 2. Supplier Organization
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
        cls.supplier_owner = User.objects.create_user(
            email="supplier_owner@om.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.supplier_org,
            user=cls.supplier_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        cls.supplier_member = User.objects.create_user(
            email="supplier_mem@om.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.supplier_org,
            user=cls.supplier_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # 3. Broker Organization
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
        cls.broker_owner = User.objects.create_user(
            email="broker_owner@trade.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.broker_org,
            user=cls.broker_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 4. Foreign Buyer-Only Organization
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
        cls.foreign_buyer_owner = User.objects.create_user(
            email="foreign_owner@turk.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.foreign_buyer_org,
            user=cls.foreign_buyer_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 5. Competitor Supplier Organization
        cls.competitor_org = Organization.objects.create(
            name="Competitor Bitumen Corp",
            registration_identifier="REG-COMPETITOR-001",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=cls.competitor_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        cls.competitor_owner = User.objects.create_user(
            email="competitor_owner@rival.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=cls.competitor_org,
            user=cls.competitor_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # 6. Platform Operator
        cls.operator_user = User.objects.create_user(
            email="operator@platform.local", password="password123"
        )
        SystemRoleAssignment.objects.create(
            user=cls.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # 7. Django Staff / Superuser without system roles
        cls.django_staff = User.objects.create_user(
            email="staff_only@platform.local",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )

    def _create_rfq(
        self, visibility=RFQVisibility.PRIVATE, status=RFQStatus.PUBLISHED, **kwargs
    ) -> RFQ:
        params = {
            "organization": self.buyer_org,
            "created_by": self.buyer_owner,
            "commodity": self.commodity,
            "schema_version": self.schema_version,
            "specifications": {"penetration_grade": "60/70"},
            "quantity": Decimal("1000.000"),
            "unit": "MT",
            "status": status,
            "visibility": visibility,
        }
        params.update(kwargs)
        return RFQ.objects.create(**params)


class RFQInvitationModelTests(BaseInvitationTestCase):
    """Test model constraints, identity, and PostgreSQL integrity rules."""

    def test_invitation_creation_and_defaults(self):
        rfq = self._create_rfq()
        invitation = RFQInvitation.objects.create(
            rfq=rfq,
            organization=self.supplier_org,
            invited_by=self.buyer_owner,
        )
        self.assertIsInstance(invitation.id, uuid.UUID)
        self.assertEqual(invitation.status, RFQInvitationStatus.INVITED)
        self.assertFalse(invitation.invited_by_operator)
        self.assertIsNotNone(invitation.created_at)
        self.assertIsNotNone(invitation.updated_at)
        self.assertIsNone(invitation.viewed_at)
        self.assertIsNone(invitation.declined_at)

    def test_unique_rfq_organization_constraint(self):
        """PostgreSQL unique(rfq, organization) constraint prevents duplicate rows."""
        rfq = self._create_rfq()
        RFQInvitation.objects.create(rfq=rfq, organization=self.supplier_org)

        with self.assertRaises(IntegrityError):
            RFQInvitation.objects.create(rfq=rfq, organization=self.supplier_org)

    def test_invalid_status_check_constraint(self):
        """CheckConstraint check_valid_rfq_invitation_status enforces valid status choices."""
        rfq = self._create_rfq()
        invitation = RFQInvitation(
            rfq=rfq, organization=self.supplier_org, status="invalid_status"
        )
        with self.assertRaises(Exception):
            invitation.save()

    def test_rfq_deletion_cascades_invitations(self):
        rfq = self._create_rfq()
        RFQInvitation.objects.create(rfq=rfq, organization=self.supplier_org)
        rfq_id = rfq.id
        rfq.delete()
        self.assertFalse(RFQInvitation.objects.filter(rfq_id=rfq_id).exists())

    def test_organization_protect_prevents_deletion(self):
        rfq = self._create_rfq()
        RFQInvitation.objects.create(rfq=rfq, organization=self.supplier_org)
        with self.assertRaises(Exception):
            self.supplier_org.delete()


class RFQInvitationEligibilityTests(BaseInvitationTestCase):
    """Test eligibility rules for invited organizations."""

    def setUp(self):
        super().setUp()
        self.rfq = self._create_rfq()

    def test_supplier_invitation_is_eligible(self):
        inv = create_invitation(self.rfq, self.supplier_org, self.buyer_owner)
        self.assertEqual(inv.organization, self.supplier_org)
        self.assertEqual(inv.status, RFQInvitationStatus.INVITED)

    def test_broker_invitation_is_eligible(self):
        inv = create_invitation(self.rfq, self.broker_org, self.buyer_owner)
        self.assertEqual(inv.organization, self.broker_org)
        self.assertEqual(inv.status, RFQInvitationStatus.INVITED)

    def test_buyer_only_organization_is_rejected(self):
        with self.assertRaises(InviteeIneligibleError) as ctx:
            create_invitation(self.rfq, self.foreign_buyer_org, self.buyer_owner)
        self.assertIn("must possess Supplier or Broker capability", str(ctx.exception))

    def test_rfq_owner_self_invitation_is_rejected(self):
        with self.assertRaises(InviteeIneligibleError) as ctx:
            create_invitation(self.rfq, self.buyer_org, self.buyer_owner)
        self.assertIn("self-invitation prohibited", str(ctx.exception))

    def test_inactive_organization_is_rejected(self):
        inactive_supplier = Organization.objects.create(
            name="Inactive Supplier",
            registration_identifier="REG-INACTIVE-001",
            country="OM",
            is_active=False,
        )
        OrganizationCapability.objects.create(
            organization=inactive_supplier,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        with self.assertRaises(InviteeIneligibleError) as ctx:
            create_invitation(self.rfq, inactive_supplier, self.buyer_owner)
        self.assertIn("inactive", str(ctx.exception))

    def test_invitation_does_not_require_commodity_association(self):
        """Private invitation grants access without requiring OrganizationCommodity."""
        self.assertFalse(
            OrganizationCommodity.objects.filter(
                organization=self.supplier_org,
                commodity=self.commodity,
            ).exists()
        )
        inv = create_invitation(self.rfq, self.supplier_org, self.buyer_owner)
        self.assertIsNotNone(inv)


class RFQInvitationAuthorizationTests(BaseInvitationTestCase):
    """Test the complete actor authorization matrix for invitation management."""

    def setUp(self):
        super().setUp()
        self.rfq = self._create_rfq()

    def test_buyer_owner_allowed(self):
        inv = create_invitation(self.rfq, self.supplier_org, self.buyer_owner)
        self.assertIsNotNone(inv)

    def test_buyer_manager_allowed(self):
        inv = create_invitation(self.rfq, self.supplier_org, self.buyer_manager)
        self.assertIsNotNone(inv)

    def test_buyer_member_denied(self):
        with self.assertRaises(InvitationPermissionDeniedError):
            create_invitation(self.rfq, self.supplier_org, self.buyer_member)

    def test_buyer_viewer_denied(self):
        with self.assertRaises(InvitationPermissionDeniedError):
            create_invitation(self.rfq, self.supplier_org, self.buyer_viewer)

    def test_foreign_buyer_denied(self):
        with self.assertRaises(InvitationPermissionDeniedError):
            create_invitation(self.rfq, self.supplier_org, self.foreign_buyer_owner)

    def test_invited_supplier_cannot_invite_competitor(self):
        create_invitation(self.rfq, self.supplier_org, self.buyer_owner)
        with self.assertRaises(InvitationPermissionDeniedError):
            create_invitation(self.rfq, self.competitor_org, self.supplier_owner)

    def test_django_staff_superuser_alone_denied(self):
        with self.assertRaises(InvitationPermissionDeniedError):
            create_invitation(self.rfq, self.supplier_org, self.django_staff)

    def test_platform_operator_allowed(self):
        inv = create_invitation(self.rfq, self.supplier_org, self.operator_user)
        self.assertIsNotNone(inv)
        self.assertTrue(inv.invited_by_operator)


class RFQInvitationLifecycleBoundaryTests(BaseInvitationTestCase):
    """Test RFQ lifecycle states vs. invitations."""

    def test_invitation_allowed_on_draft_rfq(self):
        draft_rfq = self._create_rfq(status=RFQStatus.DRAFT)
        inv = create_invitation(draft_rfq, self.supplier_org, self.buyer_owner)
        self.assertIsNotNone(inv)

    def test_invitation_allowed_on_published_rfq(self):
        published_rfq = self._create_rfq(status=RFQStatus.PUBLISHED)
        inv = create_invitation(published_rfq, self.supplier_org, self.buyer_owner)
        self.assertIsNotNone(inv)

    def test_invitation_rejected_on_closed_rfq(self):
        closed_rfq = self._create_rfq(status=RFQStatus.CLOSED)
        with self.assertRaises(InvalidTransitionError) as ctx:
            create_invitation(closed_rfq, self.supplier_org, self.buyer_owner)
        self.assertIn("closed", str(ctx.exception).lower())

    def test_invitation_rejected_on_cancelled_rfq(self):
        cancelled_rfq = self._create_rfq(status=RFQStatus.CANCELLED)
        with self.assertRaises(InvalidTransitionError) as ctx:
            create_invitation(cancelled_rfq, self.supplier_org, self.buyer_owner)
        self.assertIn("cancelled", str(ctx.exception).lower())


class RFQInvitationActionsAndTransitionsTests(BaseInvitationTestCase):
    """Test mark viewed and decline transitions."""

    def setUp(self):
        super().setUp()
        self.rfq = self._create_rfq()
        self.invitation = create_invitation(
            self.rfq, self.supplier_org, self.buyer_owner
        )

    def test_mark_invitation_viewed(self):
        inv = mark_invitation_viewed(self.invitation.id, self.supplier_owner)
        self.assertEqual(inv.status, RFQInvitationStatus.VIEWED)
        self.assertIsNotNone(inv.viewed_at)

    def test_decline_invitation_by_invitee_owner(self):
        inv = decline_invitation(
            self.invitation.id,
            self.supplier_owner,
            reason="Capacity reached for requested delivery window.",
        )
        self.assertEqual(inv.status, RFQInvitationStatus.DECLINED)
        self.assertIsNotNone(inv.declined_at)
        self.assertEqual(
            inv.decline_reason, "Capacity reached for requested delivery window."
        )

    def test_decline_invitation_by_invitee_member_denied(self):
        with self.assertRaises(InvitationPermissionDeniedError):
            decline_invitation(
                self.invitation.id, self.supplier_member, reason="Cannot fulfill"
            )

    def test_decline_invitation_by_competitor_denied(self):
        with self.assertRaises(InvitationNotFoundError):
            decline_invitation(self.invitation.id, self.competitor_owner)

    def test_cannot_decline_expired_invitation(self):
        self.invitation.status = RFQInvitationStatus.EXPIRED
        self.invitation.save()
        with self.assertRaises(InvalidInvitationStatusError):
            decline_invitation(self.invitation.id, self.supplier_owner)


class RFQInvitationVisibilityIntegrationTests(BaseInvitationTestCase):
    """Test integration between RFQInvitation and RFQVisibilityService."""

    def setUp(self):
        super().setUp()
        self.private_rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE,
            status=RFQStatus.PUBLISHED,
        )

    def test_uninvited_supplier_cannot_see_private_rfq(self):
        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertNotIn(self.private_rfq, visible)

        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.supplier_owner, self.supplier_org)

    def test_invited_supplier_sees_private_rfq(self):
        create_invitation(self.private_rfq, self.supplier_org, self.buyer_owner)

        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertIn(self.private_rfq, visible)

        retrieved = get_visible_rfq(
            self.private_rfq.id, self.supplier_owner, self.supplier_org
        )
        self.assertEqual(retrieved.id, self.private_rfq.id)

    def test_viewed_supplier_retains_visibility(self):
        inv = create_invitation(self.private_rfq, self.supplier_org, self.buyer_owner)
        mark_invitation_viewed(inv.id, self.supplier_owner)

        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertIn(self.private_rfq, visible)

    def test_responded_supplier_retains_visibility(self):
        inv = create_invitation(self.private_rfq, self.supplier_org, self.buyer_owner)
        inv.status = RFQInvitationStatus.RESPONDED
        inv.save()

        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertIn(self.private_rfq, visible)

    def test_declined_invitation_revokes_private_visibility(self):
        """Documented conservative access rule: declined invitations revoke Private RFQ access."""
        inv = create_invitation(self.private_rfq, self.supplier_org, self.buyer_owner)
        decline_invitation(inv.id, self.supplier_owner, reason="No stock")

        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertNotIn(self.private_rfq, visible)

        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.supplier_owner, self.supplier_org)

    def test_expired_invitation_does_not_grant_visibility(self):
        inv = create_invitation(self.private_rfq, self.supplier_org, self.buyer_owner)
        inv.status = RFQInvitationStatus.EXPIRED
        inv.save()

        visible = get_visible_rfqs(self.supplier_owner, self.supplier_org)
        self.assertNotIn(self.private_rfq, visible)

        with self.assertRaises(RFQNotFoundError):
            get_visible_rfq(self.private_rfq.id, self.supplier_owner, self.supplier_org)


class RFQInvitationCompetitorPrivacyAPITests(BaseInvitationTestCase):
    """Test competitor isolation and API protection against enumeration."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.rfq = self._create_rfq(
            visibility=RFQVisibility.PRIVATE, status=RFQStatus.PUBLISHED
        )
        self.supplier_inv = create_invitation(
            self.rfq, self.supplier_org, self.buyer_owner
        )
        self.competitor_inv = create_invitation(
            self.rfq, self.competitor_org, self.buyer_owner
        )

    def test_buyer_can_list_all_participants(self):
        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.get(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/",
            headers={"X-Organization-Id": str(self.buyer_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)
        org_names = [item["organization"]["name"] for item in res.data]
        self.assertIn("National Bitumen Supplier", org_names)
        self.assertIn("Competitor Bitumen Corp", org_names)

    def test_supplier_cannot_list_all_participants(self):
        """Competitor enumeration prevention: invitee receives 403 when attempting to list participants."""
        self.client.force_authenticate(user=self.supplier_owner)
        res = self.client.get(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/",
            headers={"X-Organization-Id": str(self.supplier_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_can_retrieve_own_invitation(self):
        """Invitee accesses its own invitation via /invitations/me/."""
        self.client.force_authenticate(user=self.supplier_owner)
        res = self.client.get(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/me/",
            headers={"X-Organization-Id": str(self.supplier_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], str(self.supplier_inv.id))
        self.assertEqual(res.data["organization"]["name"], self.supplier_org.name)

    def test_supplier_cannot_retrieve_competitor_invitation_by_uuid(self):
        """Guessed UUID attack on competitor invitation returns 404 Not Found."""
        self.client.force_authenticate(user=self.supplier_owner)
        res = self.client.get(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/{self.competitor_inv.id}/",
            headers={"X-Organization-Id": str(self.supplier_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_uninvited_organization_receives_404_on_me(self):
        self.client.force_authenticate(user=self.foreign_buyer_owner)
        res = self.client.get(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/me/",
            headers={"X-Organization-Id": str(self.foreign_buyer_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_invitation_api_decline(self):
        self.client.force_authenticate(user=self.supplier_owner)
        res = self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/{self.supplier_inv.id}/decline/",
            data={"reason": "Cannot meet delivery timeline"},
            format="json",
            headers={"X-Organization-Id": str(self.supplier_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "declined")
        self.assertEqual(res.data["decline_reason"], "Cannot meet delivery timeline")

    def test_invitation_api_view(self):
        self.client.force_authenticate(user=self.supplier_owner)
        res = self.client.post(
            f"/api/trade-hub/rfqs/{self.rfq.id}/invitations/{self.supplier_inv.id}/view/",
            headers={"X-Organization-Id": str(self.supplier_org.id)},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "viewed")
        self.assertIsNotNone(res.data["viewed_at"])


class RFQInvitationConcurrencyTests(TransactionTestCase):
    """
    Test concurrent race conditions using real PostgreSQL.
    1. Concurrent duplicate invite race -> exactly one invitation created.
    2. Concurrent invite vs close race -> row lock prevents invitation on closed RFQ.
    """

    def setUp(self):
        super().setUp()
        self.commodity, self.schema_version = _create_commodity("bitumen_concurrency")

        self.buyer_org = Organization.objects.create(
            name="Concurrent Buyer Corp",
            registration_identifier="REG-CONC-001",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email="conc_buyer@corp.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.supplier_org = Organization.objects.create(
            name="Concurrent Supplier Corp",
            registration_identifier="REG-CONC-002",
            country="OM",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user = User.objects.create_user(
            email="conc_supplier@corp.local", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PRIVATE,
        )

    def test_concurrent_duplicate_invitation_race(self):
        """
        Two concurrent threads attempt to invite the same organization to the same RFQ simultaneously.
        PostgreSQL unique constraint guarantees that exactly one invitation row is persisted.
        """
        errors = []
        successes = []

        def attempt_invite():
            # Close connection to ensure independent DB transaction
            connection.close()
            try:
                inv = create_invitation(
                    self.rfq.id, self.supplier_org.id, self.buyer_user
                )
                successes.append(inv)
            except DuplicateInvitationError as exc:
                errors.append(exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=attempt_invite)
        t2 = threading.Thread(target=attempt_invite)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # In total, exactly one invitation created in DB
        db_invitations = list(
            RFQInvitation.objects.filter(rfq=self.rfq, organization=self.supplier_org)
        )
        self.assertEqual(len(db_invitations), 1)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)

    def test_concurrent_invite_vs_close_race(self):
        """
        Thread 1 attempts to invite an organization while Thread 2 closes the RFQ.
        Row-locking ensures that if close commits first, invite is rejected;
        and an invitation cannot be persisted for a closed RFQ.
        """
        invite_result = []
        close_result = []

        def thread_close():
            connection.close()
            try:
                time.sleep(0.02)  # Brief pause to let thread_invite reach row lock
                closed = close_rfq(
                    self.rfq.id, expected_version=1, actor=self.buyer_user
                )
                close_result.append(closed)
            except Exception as exc:
                close_result.append(exc)
            finally:
                connection.close()

        def thread_invite():
            connection.close()
            try:
                inv = create_invitation(
                    self.rfq.id, self.supplier_org.id, self.buyer_user
                )
                invite_result.append(inv)
            except Exception as exc:
                invite_result.append(exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_invite)
        t2 = threading.Thread(target=thread_close)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.CLOSED)

        # Invariant check: if RFQ is closed, no invitation could have been added after close.
        # If invite succeeded first, invitation exists and close succeeded afterwards.
        # If close succeeded first, invite failed with InvalidTransitionError.
        if len(invite_result) == 1 and isinstance(invite_result[0], RFQInvitation):
            # Invitation was created before close
            self.assertTrue(
                RFQInvitation.objects.filter(
                    rfq=self.rfq, organization=self.supplier_org
                ).exists()
            )
        else:
            # Invitation was rejected because RFQ was closed
            self.assertIsInstance(invite_result[0], InvalidTransitionError)
            self.assertFalse(
                RFQInvitation.objects.filter(
                    rfq=self.rfq, organization=self.supplier_org
                ).exists()
            )
