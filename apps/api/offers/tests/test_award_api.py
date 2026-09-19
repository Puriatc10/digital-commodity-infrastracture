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
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from offers.enums import AwardStatus, LogisticsCostStatus, OfferorRole
from offers.models import Award, AwardAllocation
from offers.services.creation import create_offer
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class AwardAPITests(TestCase):
    """
    Comprehensive REST API & Authorization Matrix tests for T0813 Award Offer:
    - RFQAwardDetailView (GET, POST)
    - AwardDetailView (GET)
    - AwardAllocationCreateView (POST)
    - AwardAllocationDetailView (PATCH, DELETE)
    - AwardFinalizeView (POST)
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_api_{uuid.uuid4().hex[:6]}",
            name_fa="قیر صنعتی",
            name_en="Industrial Bitumen",
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

        # Buyer Organization & Users
        self.buyer_org = Organization.objects.create(
            name="Buyer Alpha Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email="buyer@alphacorp.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Foreign Buyer (Different Organization)
        self.foreign_buyer_org = Organization.objects.create(
            name="Foreign Buyer Beta",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.foreign_buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.foreign_buyer_user = User.objects.create_user(
            email="buyer@foreignbeta.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=self.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Supplier Organization & Users
        self.supplier_org = Organization.objects.create(
            name="Supplier Refinery Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationVerification.objects.update_or_create(
            organization=self.supplier_org,
            defaults={"status": VerificationStatus.VERIFIED, "version": 1},
        )
        self.supplier_user = User.objects.create_user(
            email="supplier@refinery.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Broker Organization & User
        self.broker_org = Organization.objects.create(
            name="Broker Trade Agency",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.broker_user = User.objects.create_user(
            email="broker@tradeagency.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Platform Operator & Admin
        self.operator_user = User.objects.create_user(
            email="operator@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )
        self.admin_user = User.objects.create_user(
            email="admin@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Staff-only user (Django is_staff=True without system role assignment)
        self.staff_user = User.objects.create_user(
            email="staff@djangoadmin.com",
            password="testpassword123",
            is_staff=True,
        )

        # Published RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier Offer & Submitted V1 (400 MT)
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer.id,
            offered_quantity=Decimal("400.000"),
            quantity_unit="MT",
            unit_price=Decimal("320.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=7),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.offer.refresh_from_db()
        self.v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

    # -------------------------------------------------------------------------
    # 1. Unauthenticated & Permission Boundaries
    # -------------------------------------------------------------------------

    def test_unauthenticated_requests_return_401(self):
        """Unauthenticated requests are rejected with 401 or 403."""
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"
        resp = self.client.get(rfq_url)
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        resp = self.client.post(rfq_url, {}, format="json")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_foreign_buyer_forbidden_403(self):
        """Buyer from a different organization cannot view or create award (403 Forbidden)."""
        self.client.force_authenticate(user=self.foreign_buyer_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        resp = self.client.get(rfq_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.post(rfq_url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_and_broker_forbidden_403(self):
        """Suppliers and Brokers cannot view deliberation or manipulate awards (403 Forbidden)."""
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        for actor in [self.supplier_user, self.broker_user]:
            self.client.force_authenticate(user=actor)
            resp = self.client.get(rfq_url)
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
            resp = self.client.post(rfq_url, {}, format="json")
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_only_without_system_role_forbidden_403(self):
        """Django is_staff user without SystemRoleAssignment is forbidden (403)."""
        self.client.force_authenticate(user=self.staff_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        resp = self.client.get(rfq_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 2. Draft Award Creation & Retrieval
    # -------------------------------------------------------------------------

    def test_buyer_can_create_and_retrieve_draft_award(self):
        """Authorized buyer can initialize a draft award and retrieve it."""
        self.client.force_authenticate(user=self.buyer_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        # 1. Before creation: GET returns 404
        resp = self.client.get(rfq_url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # 2. POST to initialize draft award
        resp = self.client.post(rfq_url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], AwardStatus.DRAFT)
        self.assertEqual(resp.data["version"], 1)
        self.assertEqual(Decimal(str(resp.data["total_awarded_quantity"])), Decimal("0"))
        award_id = resp.data["id"]

        # 3. Subsequent GET returns the draft award
        resp = self.client.get(rfq_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], award_id)

        # 4. Detail endpoint by UUID
        award_url = f"/api/offers/awards/{award_id}/"
        resp = self.client.get(award_url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], award_id)

    def test_operator_and_admin_can_manage_award(self):
        """Platform Operator and Admin have full authorization over awards."""
        self.client.force_authenticate(user=self.operator_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        resp = self.client.post(rfq_url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        award_id = resp.data["id"]

        # Admin can view the award
        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get(f"/api/offers/awards/{award_id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mass_assignment_protection_status_cannot_be_injected(self):
        """Passing status='FINALIZED' in POST is ignored; draft remains DRAFT."""
        self.client.force_authenticate(user=self.buyer_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"

        resp = self.client.post(rfq_url, {"status": "FINALIZED"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], AwardStatus.DRAFT)

        award = Award.objects.get(pk=resp.data["id"])
        self.assertEqual(award.status, AwardStatus.DRAFT)

    # -------------------------------------------------------------------------
    # 3. Allocations Management (Add, Update, Remove)
    # -------------------------------------------------------------------------

    def test_allocation_crud_workflow(self):
        """Full CRUD flow for award allocations via REST API."""
        self.client.force_authenticate(user=self.buyer_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"
        resp = self.client.post(rfq_url, {}, format="json")
        award_id = resp.data["id"]
        award_version = resp.data["version"]

        alloc_url = f"/api/offers/awards/{award_id}/allocations/"

        # 1. Validation error: Over-allocation (> offered_quantity 400 MT)
        resp = self.client.post(
            alloc_url,
            {
                "offer_version_id": str(self.v1.id),
                "awarded_quantity": "450.000",
                "expected_version": award_version,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Add valid allocation (300 MT)
        resp = self.client.post(
            alloc_url,
            {
                "offer_version_id": str(self.v1.id),
                "awarded_quantity": "300.000",
                "expected_version": award_version,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        alloc_id = resp.data["id"]
        self.assertEqual(resp.data["awarded_quantity"], "300.000")

        # Award version was incremented to 2
        award = Award.objects.get(pk=award_id)
        self.assertEqual(award.version, 2)

        # 3. PATCH allocation quantity (update to 350 MT)
        detail_alloc_url = f"/api/offers/awards/allocations/{alloc_id}/"
        resp = self.client.patch(
            detail_alloc_url,
            {
                "awarded_quantity": "350.000",
                "expected_version": 2,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["awarded_quantity"], "350.000")

        # Award version was incremented to 3
        award.refresh_from_db()
        self.assertEqual(award.version, 3)

        # 4. DELETE allocation with expected_version
        resp = self.client.delete(
            detail_alloc_url,
            {"expected_version": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(AwardAllocation.objects.filter(pk=alloc_id).count(), 0)

    # -------------------------------------------------------------------------
    # 4. Finalization & Immutability
    # -------------------------------------------------------------------------

    def test_finalize_award_endpoint_success_and_immutability(self):
        """Finalizing award transitions RFQ to AWARDED and enforces immutability."""
        self.client.force_authenticate(user=self.buyer_user)
        rfq_url = f"/api/rfqs/{self.rfq.id}/award/"
        resp = self.client.post(rfq_url, {}, format="json")
        award_id = resp.data["id"]

        # Add allocation
        alloc_url = f"/api/offers/awards/{award_id}/allocations/"
        resp = self.client.post(
            alloc_url,
            {
                "offer_version_id": str(self.v1.id),
                "awarded_quantity": "400.000",
                "expected_version": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        alloc_id = resp.data["id"]

        # Finalize
        fin_url = f"/api/offers/awards/{award_id}/finalize/"

        # Stale expected_version returns 409
        resp = self.client.post(fin_url, {"expected_version": 1}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

        # Valid finalization with expected_version=2
        resp = self.client.post(fin_url, {"expected_version": 2}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], AwardStatus.FINALIZED)
        self.assertIsNotNone(resp.data["finalized_at"])

        # Check DB state
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.AWARDED)

        # Attempt to add another allocation -> 409 Conflict
        resp = self.client.post(
            alloc_url,
            {
                "offer_version_id": str(self.v1.id),
                "awarded_quantity": "50.000",
                "expected_version": 3,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

        # Attempt to delete allocation -> 409 Conflict
        detail_alloc_url = f"/api/offers/awards/allocations/{alloc_id}/"
        resp = self.client.delete(
            detail_alloc_url,
            {"expected_version": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
