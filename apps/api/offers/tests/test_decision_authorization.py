from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status

from rest_framework.test import APIClient

from offers.enums import OfferorRole, OfferVersionStatus
from offers.exceptions import DecisionPermissionDeniedError
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from offers.services.decision_service import create_decision_run_foundation
from offers.services.policy_seed import seed_decision_profile_v1
from offers.tests.base import BaseOffersTestCase
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class DecisionAuthorizationTests(BaseOffersTestCase):
    """
    Complete actor matrix tests for Decision Support (T0808):
    - Authorized Buyer actor
    - Foreign Buyer
    - Operator
    - Product Admin
    - Supplier
    - Broker
    - Staff-only
    - Superuser-only
    - Anonymous
    Competitor confidentiality guard: Suppliers/Brokers cannot view competitor decision metadata.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.profile_v1 = seed_decision_profile_v1()

        # Create a submitted offer on the RFQ
        self.offer = Offer.objects.create(
            rfq=self.published_rfq,
            offering_organization=self.supplier_org,
            offeror_role=OfferorRole.SUPPLIER,
            created_by=self.supplier_user,
        )
        self.version = OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.published_rfq.schema_version,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("450.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )


        self.offer.current_submitted_version = self.version
        self.offer.save(update_fields=["current_submitted_version"])

        # Foreign Buyer Organization & User
        self.foreign_buyer_org = Organization.objects.create(
            name="Foreign Buyer Inc",
            country="DE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.foreign_buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.foreign_buyer_user = User.objects.create_user(
            email="foreign@buyer.de",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=self.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Baseline decision run
        self.decision_run = create_decision_run_foundation(
            self.published_rfq,
            actor=self.buyer_user,
        )

    # --- Service-level matrix ---

    def test_service_authorized_buyer_actor_allowed(self):
        run = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)
        self.assertIsNotNone(run.pk)

    def test_service_foreign_buyer_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=self.foreign_buyer_user)

    def test_service_operator_allowed(self):
        run = create_decision_run_foundation(self.published_rfq, actor=self.operator_user)
        self.assertIsNotNone(run.pk)

    def test_service_product_admin_allowed(self):
        run = create_decision_run_foundation(self.published_rfq, actor=self.admin_user)
        self.assertIsNotNone(run.pk)

    def test_service_supplier_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=self.supplier_user)

    def test_service_broker_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=self.broker_user)

    def test_service_staff_only_without_role_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=self.staff_only_user)

    def test_service_superuser_only_without_role_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=self.superuser_only_user)

    def test_service_anonymous_forbidden(self):
        with self.assertRaises(DecisionPermissionDeniedError):
            create_decision_run_foundation(self.published_rfq, actor=None)

    # --- API-level matrix: POST /rfqs/{rfq_id}/decision-runs/ ---

    def test_api_create_run_authorized_buyer_201(self):
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("input_fingerprint", response.data)
        self.assertEqual(response.data["total_candidates"], 1)

    def test_api_create_run_operator_201(self):
        self.client.force_authenticate(user=self.operator_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_api_create_run_product_admin_201(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_api_create_run_foreign_buyer_403(self):
        self.client.force_authenticate(user=self.foreign_buyer_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_create_run_supplier_403(self):
        self.client.force_authenticate(user=self.supplier_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_create_run_broker_403(self):
        self.client.force_authenticate(user=self.broker_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_create_run_staff_only_without_role_403(self):
        self.client.force_authenticate(user=self.staff_only_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_create_run_superuser_only_without_role_403(self):
        self.client.force_authenticate(user=self.superuser_only_user)
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_create_run_anonymous_401(self):
        response = self.client.post(f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


    # --- API-level matrix: GET /decision-runs/{id}/ ---

    def test_api_get_run_authorized_buyer_200(self):
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.decision_run.id))
        self.assertEqual(len(response.data["candidates"]), 1)

    def test_api_get_run_operator_200(self):
        self.client.force_authenticate(user=self.operator_user)
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_api_get_run_foreign_buyer_403(self):
        self.client.force_authenticate(user=self.foreign_buyer_user)
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_get_run_supplier_cannot_view_competitor_decision_metadata_403(self):
        """Supplier cannot access DecisionRun detail (competitor confidentiality protection)."""
        self.client.force_authenticate(user=self.supplier_user)
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_get_run_broker_cannot_view_competitor_decision_metadata_403(self):
        """Broker cannot access DecisionRun detail (competitor confidentiality protection)."""
        self.client.force_authenticate(user=self.broker_user)
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_get_run_anonymous_401(self):
        response = self.client.get(f"/api/offers/decision-runs/{self.decision_run.id}/")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

