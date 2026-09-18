from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from geography.seed import seed_iran_geography
from identity.models import SystemRoleAssignment, User
from matching.enums import (
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalOutcome,
)
from matching.models.policy import MatchingPolicy, MatchingPolicyVersion
from matching.models.run import MatchingRun
from matching.rules.history import default_historical_registry
from matching.models.specification_rule import (
    SpecificationMatchingRule,
    SpecificationRuleOperator,
)
from matching.models.verification_rule import VerificationMatchingRule
from matching.rules.trust import DEFAULT_VERIFICATION_RULES
from matching.seed import (
    DEFAULT_POLICY_CODE,
    DEFAULT_POLICY_DESCRIPTION,
    DEFAULT_POLICY_NAME,
    DEFAULT_POLICY_V1_CONFIGURATION,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import (
    RFQ,
    RFQGeographyConstraint,
    RFQStatus,
    RFQVisibility,
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)
from trade_hub.models.rfq import GeographyConstraintMode


class APISecurityMatrixTests(APITestCase):
    """
    Comprehensive API security and privacy matrix tests for:
    - POST /api/matching/rfqs/{rfq_id}/runs/
    - GET /api/matching/rfqs/{rfq_id}/runs/
    - GET /api/matching/runs/{run_id}/
    - GET /api/matching/runs/{run_id}/candidates/
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_prov = cls.areas["IR-07"]
        cls.tehran_city = cls.areas["IR-07-THR"]

        cls.commodity = CommodityDefinition.objects.create(
            code="bitumen_api_test",
            name_en="Bitumen API Test",
            name_fa="قیر تست API",
        )
        cls.schema_version = CommoditySchemaVersion.objects.create(
            commodity=cls.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        cls.attr = CommodityAttributeDefinition.objects.create(
            schema_version=cls.schema_version,
            key="penetration_grade",
            label_en="Penetration Grade",
            label_fa="درجه نفوذ",
            data_type=CommodityAttributeDefinition.DataType.STRING,
        )
        cls.schema_version.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        cls.schema_version.save()

        policy, _ = MatchingPolicy.objects.get_or_create(
            code=DEFAULT_POLICY_CODE,
            defaults={
                "name": DEFAULT_POLICY_NAME,
                "description": DEFAULT_POLICY_DESCRIPTION,
            },
        )
        cls.policy_version = MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
            description="Default commodity matching policy v1.",
            configuration=DEFAULT_POLICY_V1_CONFIGURATION,
        )
        SpecificationMatchingRule.objects.create(
            policy_version=cls.policy_version,
            semantic_identity=cls.attr.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=False,
            relative_weight=Decimal("1.0000"),
            missing_data_policy=SignalOutcome.UNKNOWN,
        )
        for state, rule_snap in DEFAULT_VERIFICATION_RULES.items():
            VerificationMatchingRule.objects.create(
                policy_version=cls.policy_version,
                verification_state=state,
                raw_score=rule_snap.raw_score,
                hard_exclude=rule_snap.hard_exclude,
            )
        cls.policy_version.status = PolicyLifecycleStatus.PUBLISHED
        cls.policy_version.save()

    def setUp(self):
        # 1. Buyer Org A and User A
        self.buyer_org_a = Organization.objects.create(name="Buyer Org A", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org_a, capability=OrganizationCapability.CapabilityType.BUYER)
        OrganizationCommodity.objects.create(organization=self.buyer_org_a, commodity=self.commodity)
        self.buyer_user_a = User.objects.create_user(email="buyer_a@apitest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.buyer_user_a, organization=self.buyer_org_a, is_active=True)

        # 2. Buyer Org B and User B (Foreign Buyer)
        self.buyer_org_b = Organization.objects.create(name="Buyer Org B", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org_b, capability=OrganizationCapability.CapabilityType.BUYER)
        OrganizationCommodity.objects.create(organization=self.buyer_org_b, commodity=self.commodity)
        self.buyer_user_b = User.objects.create_user(email="buyer_b@apitest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.buyer_user_b, organization=self.buyer_org_b, is_active=True)

        # 3. Platform Operator User
        self.operator_user = User.objects.create_user(email="operator@apitest.com", password="testpassword")
        SystemRoleAssignment.objects.create(user=self.operator_user, role=SystemRoleAssignment.SystemRole.OPERATOR)

        # 4. Supplier User
        self.supplier_org = Organization.objects.create(name="Supplier Org", is_active=True)
        OrganizationCapability.objects.create(organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER)
        OrganizationCommodity.objects.create(organization=self.supplier_org, commodity=self.commodity)
        OrganizationVerification.objects.create(organization=self.supplier_org, status=VerificationStatus.VERIFIED)
        self.supplier_user = User.objects.create_user(email="supplier@apitest.com", password="testpassword")
        OrganizationMembership.objects.create(user=self.supplier_user, organization=self.supplier_org, is_active=True)

        # Target RFQ belonging to Buyer Org A
        self.rfq_a = RFQ.objects.create(
            organization=self.buyer_org_a,
            created_by=self.buyer_user_a,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 15),
            destination_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )
        RFQGeographyConstraint.objects.create(
            rfq=self.rfq_a,
            mode=GeographyConstraintMode.PREFERRED,
            area=self.tehran_prov,
        )

        # Supply Listing from Supplier Org
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            availability_window_start=date(2026, 10, 1),
            availability_window_end=date(2026, 10, 15),
            origin_area=self.tehran_city,
            specifications={"penetration_grade": "60/70"},
            status=SupplyListingStatus.ACTIVE,
            visibility=SupplyListingVisibility.PUBLIC,
        )

    def test_unauthenticated_request_is_rejected_with_401_or_403(self):
        """Anonymous requests to matching endpoints must be rejected."""
        res_post = self.client.post(f"/api/matching/rfqs/{self.rfq_a.id}/runs/")
        self.assertIn(res_post.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

        res_get = self.client.get(f"/api/matching/rfqs/{self.rfq_a.id}/runs/")
        self.assertIn(res_get.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_buyer_can_execute_run_for_own_rfq_with_buyer_audience(self):
        """Owner buyer can trigger a matching run for their own RFQ with audience=BUYER."""
        self.client.force_authenticate(user=self.buyer_user_a)
        response = self.client.post(
            f"/api/matching/rfqs/{self.rfq_a.id}/runs/",
            {"audience": MatchingAudience.BUYER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["rfq_id"], str(self.rfq_a.id))
        self.assertEqual(data["audience"], MatchingAudience.BUYER)
        self.assertFalse(data["is_stale"])
        self.assertGreater(data["candidate_count"], 0)

    def test_buyer_cannot_execute_run_with_operator_audience(self):
        """Buyer attempting to run matching with audience=OPERATOR must receive 403 Forbidden."""
        self.client.force_authenticate(user=self.buyer_user_a)
        response = self.client.post(
            f"/api/matching/rfqs/{self.rfq_a.id}/runs/",
            {"audience": MatchingAudience.OPERATOR},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_foreign_buyer_cannot_execute_run_for_other_rfq(self):
        """Buyer User B cannot execute a matching run on RFQ owned by Buyer Org A."""
        self.client.force_authenticate(user=self.buyer_user_b)
        response = self.client.post(
            f"/api/matching/rfqs/{self.rfq_a.id}/runs/",
            {"audience": MatchingAudience.BUYER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_can_execute_run_for_any_rfq_with_operator_audience(self):
        """Platform operator can execute a run with audience=OPERATOR for any RFQ."""
        self.client.force_authenticate(user=self.operator_user)
        response = self.client.post(
            f"/api/matching/rfqs/{self.rfq_a.id}/runs/",
            {"audience": MatchingAudience.OPERATOR},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["audience"], MatchingAudience.OPERATOR)

    def test_candidate_list_privacy_projection_for_buyer(self):
        """
        When audience is BUYER, GET /api/matching/runs/{run_id}/candidates/
        must project safe metadata (no counterparty leaks).
        """
        # Execute run as Buyer
        self.client.force_authenticate(user=self.buyer_user_a)
        post_res = self.client.post(f"/api/matching/rfqs/{self.rfq_a.id}/runs/", format="json")
        run_id = post_res.json()["id"]

        cand_res = self.client.get(f"/api/matching/runs/{run_id}/candidates/")
        self.assertEqual(cand_res.status_code, status.HTTP_200_OK)
        candidates = cand_res.json()
        self.assertGreater(len(candidates), 0)

        for c in candidates:
            # Must have safe projection fields
            self.assertIn("lane", c)
            self.assertIn("rank", c)
            self.assertIn("signals", c)
            self.assertIn("source", c)

    def test_candidate_filtering_by_lane_and_eligible(self):
        """Query parameters ?lane=direct_supply and ?eligible=true filter candidates correctly."""
        self.client.force_authenticate(user=self.buyer_user_a)
        post_res = self.client.post(f"/api/matching/rfqs/{self.rfq_a.id}/runs/", format="json")
        run_id = post_res.json()["id"]

        filtered_res = self.client.get(f"/api/matching/runs/{run_id}/candidates/?lane=direct_supply&eligible=true")
        self.assertEqual(filtered_res.status_code, status.HTTP_200_OK)
        for c in filtered_res.json():
            self.assertEqual(c["lane"], CandidateLane.DIRECT_SUPPLY.value)
            self.assertTrue(c["eligible"])

    def test_provider_runtime_exception_returns_controlled_500_without_exposing_internals(self):
        """
        When a historical provider raises a runtime exception, the API must:
        - Return HTTP 500 Internal Server Error
        - Return standardized error payload {"code": "historical_provider_failure", "detail": "..."}
        - NOT expose raw python exception, internal traceback, or SQL error details
        - Roll back completely, leaving 0 matching runs.
        """
        class FailingHistoryProvider:
            code = "history.network_down"

            def supports_candidate_kind(self, candidate_kind: str) -> bool:
                return True

            def evaluate(self, candidate, context, policy_version=None):
                raise RuntimeError("PostgreSQL socket connection closed unexpectedly at /var/run/postgresql")

        default_historical_registry.register(FailingHistoryProvider())
        try:
            initial_runs = MatchingRun.objects.count()
            self.client.force_authenticate(user=self.buyer_user_a)
            response = self.client.post(
                f"/api/matching/rfqs/{self.rfq_a.id}/runs/",
                {"audience": MatchingAudience.BUYER},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            data = response.json()
            self.assertEqual(data.get("code"), "historical_provider_failure")
            self.assertEqual(data.get("detail"), "A historical signal provider encountered an operational failure.")
            # Verify raw Python/internal details are completely hidden from the client
            self.assertNotIn("PostgreSQL socket connection closed", str(data))
            self.assertNotIn("Traceback", str(data))
            self.assertNotIn("RuntimeError", str(data))

            # Verify atomicity at the API layer
            self.assertEqual(MatchingRun.objects.count(), initial_runs)
        finally:
            default_historical_registry.clear()
