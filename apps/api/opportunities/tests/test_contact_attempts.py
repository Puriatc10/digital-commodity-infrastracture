import datetime
from decimal import Decimal
import uuid

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment, User
from opportunities.api.serializers import (
    OpportunityDetailSerializer,
    OpportunityExternalCounterpartyProjectionSerializer,
    OpportunityOrganizationProjectionSerializer,
)
from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    OpportunityContactAttempt,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    get_contact_attempt,
    list_contact_attempts,
    record_contact_attempt,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)


class ContactAttemptTests(TestCase):
    """
    Comprehensive tests for T0606 Opportunity Contact Attempts.
    """

    def setUp(self):
        self.client = APIClient()

        # Actors
        self.operator = User.objects.create_user(email="operator@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.admin = User.objects.create_user(email="admin@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN
        )

        self.buyer_org = Organization.objects.create(name="Buyer Org")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.buyer_user = User.objects.create_user(email="buyer@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        self.supplier_org = Organization.objects.create(name="Supplier Org")
        OrganizationCapability.objects.create(
            organization=self.supplier_org, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.supplier_user = User.objects.create_user(email="supplier@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.supplier_org, user=self.supplier_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        self.broker_org = Organization.objects.create(name="Broker Org")
        OrganizationCapability.objects.create(
            organization=self.broker_org, capability=OrganizationCapability.CapabilityType.BROKER
        )
        self.broker_user = User.objects.create_user(email="broker@org.com", password="password")
        OrganizationMembership.objects.create(
            organization=self.broker_org, user=self.broker_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        self.staff_only = User.objects.create_user(email="staff@platform.com", password="password", is_staff=True)
        self.superuser_only = User.objects.create_superuser(
            email="superuser@platform.com", password="password"
        )

        self.other_operator = User.objects.create_user(email="other_operator@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=self.other_operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_ca_test",
            name_en="Bitumen CA Test",
            name_fa="قیر تست تماس",
        )

        # Opportunity with BuyerOrg as counterparty and BrokerOrg as broker
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("150.000"),
            indicative_price=Decimal("400.00"),
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
            created_by=self.operator,
        )

        # Opportunity B for cross-resource isolation checks
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Second Counterparty",
            contact_name="Sara Smith",
        )
        self.opp_b = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty_id=self.external_cp.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("200.000"),
            source=OpportunitySource.OPERATOR_SOURCING,
            created_by=self.operator,
        )

        self.base_url = f"/api/opportunities/opportunities/{self.opp.id}/contact-attempts/"

    # -------------------------------------------------------------------------
    # 1. All Five Contact Types
    # -------------------------------------------------------------------------

    def test_all_five_contact_types_via_service(self):
        """All five defined types (CALL, MESSAGE, EMAIL, MEETING, NOTE) persist successfully."""
        expected_types = [
            ContactAttemptType.CALL,
            ContactAttemptType.MESSAGE,
            ContactAttemptType.EMAIL,
            ContactAttemptType.MEETING,
            ContactAttemptType.NOTE,
        ]
        for ctype in expected_types:
            attempt = record_contact_attempt(
                self.opp.id,
                type=ctype,
                notes=f"Test interaction for {ctype}",
                actor=self.operator,
            )
            self.assertEqual(attempt.type, ctype)
            self.assertEqual(attempt.opportunity_id, self.opp.id)
            self.assertEqual(attempt.recorded_by, self.operator)

    def test_list_and_get_contact_attempts_service(self):
        """Domain service functions list_contact_attempts and get_contact_attempt behave correctly."""
        a1 = record_contact_attempt(self.opp.id, type="CALL", notes="S1", actor=self.operator)
        a2 = record_contact_attempt(self.opp.id, type="NOTE", notes="S2", actor=self.operator)

        attempts = list(list_contact_attempts(self.opp.id))
        self.assertEqual(len(attempts), 2)
        self.assertIn(a2.id, [a.id for a in attempts])

        fetched = get_contact_attempt(self.opp.id, a1.id)
        self.assertEqual(fetched.id, a1.id)
        self.assertEqual(fetched.notes, "S1")

    def test_all_five_contact_types_via_api(self):
        """All five contact types can be created through the API."""
        self.client.force_authenticate(user=self.operator)
        for ctype in ["CALL", "MESSAGE", "EMAIL", "MEETING", "NOTE"]:
            res = self.client.post(
                self.base_url,
                {"type": ctype, "notes": f"API recorded {ctype}"},
                format="json",
            )
            self.assertEqual(res.status_code, status.HTTP_201_CREATED, f"Failed for {ctype}: {res.data}")
            self.assertEqual(res.data["type"], ctype)
            self.assertEqual(res.data["recorded_by"], self.operator.id)

    def test_invalid_contact_type_rejected_by_api(self):
        """Invalid contact type is rejected with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "TELEPATHY", "notes": "Invalid interaction"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("type", res.data)

    def test_invalid_contact_type_db_constraint(self):
        """Direct database insert with invalid type violates check constraint."""
        with self.assertRaises(IntegrityError):
            OpportunityContactAttempt.objects.bulk_create(
                [
                    OpportunityContactAttempt(
                        opportunity=self.opp,
                        type="INVALID_TYPE",
                        notes="Bypassing validation",
                    )
                ]
            )

    # -------------------------------------------------------------------------
    # 2. Server-derived Recorder & Spoofed Recorder Rejection
    # -------------------------------------------------------------------------

    def test_recorder_derived_from_authenticated_user(self):
        """recorded_by is automatically set to the authenticated user."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "CALL", "notes": "Logged call"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["recorded_by"], self.operator.id)
        self.assertEqual(res.data["recorded_by_email"], self.operator.email)

        attempt = OpportunityContactAttempt.objects.get(id=res.data["id"])
        self.assertEqual(attempt.recorded_by, self.operator)

    def test_spoofed_recorder_rejected_via_mass_assignment(self):
        """Client-provided recorded_by or recorded_by_id is ignored and replaced by authenticated actor."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {
                "type": "MESSAGE",
                "notes": "Attempting to attribute to another operator",
                "recorded_by": self.other_operator.id,
                "recorded_by_id": self.other_operator.id,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["recorded_by"], self.operator.id)
        self.assertEqual(res.data["recorded_by_email"], self.operator.email)

        attempt = OpportunityContactAttempt.objects.get(id=res.data["id"])
        self.assertEqual(attempt.recorded_by, self.operator)
        self.assertNotEqual(attempt.recorded_by, self.other_operator)

    # -------------------------------------------------------------------------
    # 3. occurred_at Validation (Past Interactions & Future Timestamp Guard)
    # -------------------------------------------------------------------------

    def test_past_occurred_at_permitted(self):
        """Historical past interactions can be accurately recorded."""
        past_time = timezone.now() - datetime.timedelta(days=14, hours=3)
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {
                "type": "MEETING",
                "occurred_at": past_time.isoformat(),
                "notes": "Meeting held two weeks ago",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        attempt = OpportunityContactAttempt.objects.get(id=res.data["id"])
        self.assertAlmostEqual(
            attempt.occurred_at.timestamp(), past_time.timestamp(), delta=2
        )

    def test_invalid_occurred_at_string_rejected(self):
        """Malformed timestamp string returns 400 Bad Request."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "CALL", "occurred_at": "not-a-valid-timestamp"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("occurred_at", res.data)

    def test_future_occurred_at_rejected(self):
        """Future timestamp beyond allowable clock drift returns 400 Bad Request."""
        future_time = timezone.now() + datetime.timedelta(days=2)
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "CALL", "occurred_at": future_time.isoformat()},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("occurred_at", res.data)

    # -------------------------------------------------------------------------
    # 4. Details Field Alias
    # -------------------------------------------------------------------------

    def test_details_alias_populates_notes(self):
        """Client can submit 'details' instead of 'notes'."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "NOTE", "details": "Internal meeting minutes from yesterday"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["notes"], "Internal meeting minutes from yesterday")

    # -------------------------------------------------------------------------
    # 5. Deterministic Ordering & Stable Secondary Ordering
    # -------------------------------------------------------------------------

    def test_deterministic_ordering_by_occurred_at_desc(self):
        """Contact attempts return strictly ordered by occurred_at descending."""
        now = timezone.now()
        t1 = now - datetime.timedelta(days=5)
        t2 = now - datetime.timedelta(days=2)
        t3 = now - datetime.timedelta(hours=1)

        # Create out of order
        a2 = record_contact_attempt(self.opp.id, type="CALL", occurred_at=t2, notes="Second", actor=self.operator)
        a1 = record_contact_attempt(self.opp.id, type="EMAIL", occurred_at=t1, notes="First", actor=self.operator)
        a3 = record_contact_attempt(self.opp.id, type="MEETING", occurred_at=t3, notes="Third", actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["id"], str(a3.id))
        self.assertEqual(items[1]["id"], str(a2.id))
        self.assertEqual(items[2]["id"], str(a1.id))

    def test_equal_timestamp_ordering_stability(self):
        """Contact attempts with identical occurred_at maintain deterministic order via created_at and id."""
        fixed_time = timezone.now() - datetime.timedelta(days=1)

        a1 = record_contact_attempt(self.opp.id, type="CALL", occurred_at=fixed_time, notes="A1", actor=self.operator)
        a2 = record_contact_attempt(self.opp.id, type="NOTE", occurred_at=fixed_time, notes="A2", actor=self.operator)
        a3 = record_contact_attempt(self.opp.id, type="EMAIL", occurred_at=fixed_time, notes="A3", actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        res1 = self.client.get(self.base_url)
        res2 = self.client.get(self.base_url)

        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        ids1 = [item["id"] for item in res1.data]
        ids2 = [item["id"] for item in res2.data]

        # Order must be 100% stable across repeated requests
        self.assertEqual(ids1, ids2)
        self.assertEqual(len(ids1), 3)
        self.assertSetEqual(set(ids1), {str(a1.id), str(a2.id), str(a3.id)})

    # -------------------------------------------------------------------------
    # 6. Authorization Matrix
    # -------------------------------------------------------------------------

    def test_authorization_matrix(self):
        """
        Matrix:
        - Operator: 200/201
        - Product Admin: 200/201
        - Buyer Org User (counterparty): 403 Forbidden
        - Supplier Org User: 403 Forbidden
        - Broker Org User (attributed broker): 403 Forbidden
        - Django staff-only (no system role): 403 Forbidden
        - Django superuser-only (no system role): 403 Forbidden
        - Anonymous: 401/403
        """
        attempt = record_contact_attempt(self.opp.id, type="CALL", notes="Auth test", actor=self.operator)
        detail_url = f"{self.base_url}{attempt.id}/"

        # 1. Operator
        self.client.force_authenticate(user=self.operator)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_201_CREATED,
        )

        # 2. Product Admin
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_201_CREATED,
        )

        # 3. Buyer Org User (counterparty of this opportunity!)
        self.client.force_authenticate(user=self.buyer_user)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 4. Supplier Org User
        self.client.force_authenticate(user=self.supplier_user)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 5. Broker Org User (attributed broker on this opportunity!)
        self.client.force_authenticate(user=self.broker_user)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 6. Django Staff-only
        self.client.force_authenticate(user=self.staff_only)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 7. Django Superuser-only
        self.client.force_authenticate(user=self.superuser_only)
        self.assertEqual(self.client.get(self.base_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 8. Anonymous
        self.client.logout()
        self.assertIn(
            self.client.get(self.base_url).status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            self.client.get(detail_url).status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
        self.assertIn(
            self.client.post(self.base_url, {"type": "CALL"}, format="json").status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    # -------------------------------------------------------------------------
    # 7. Append-only Behavior (No PUT, PATCH, DELETE)
    # -------------------------------------------------------------------------

    def test_append_only_endpoints_reject_put_patch_delete(self):
        """PUT, PATCH, DELETE methods are disallowed on contact attempt endpoints (405)."""
        attempt = record_contact_attempt(self.opp.id, type="CALL", notes="Original notes", actor=self.operator)
        detail_url = f"{self.base_url}{attempt.id}/"
        self.client.force_authenticate(user=self.operator)

        # On list endpoint
        self.assertEqual(
            self.client.put(self.base_url, {"notes": "new"}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(self.base_url, {"notes": "new"}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(self.base_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        # On detail endpoint
        self.assertEqual(
            self.client.put(detail_url, {"notes": "altered"}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(detail_url, {"notes": "altered"}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(detail_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    # -------------------------------------------------------------------------
    # 8. IDOR & Malformed IDs (No 500 Errors)
    # -------------------------------------------------------------------------

    def test_malformed_opportunity_id_returns_404_not_500(self):
        """Malformed Opportunity UUID returns 404, not an unhandled 500."""
        self.client.force_authenticate(user=self.operator)
        url = "/api/opportunities/opportunities/not-a-valid-uuid/contact-attempts/"

        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        res_post = self.client.post(url, {"type": "CALL"}, format="json")
        self.assertEqual(res_post.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_opportunity_id_returns_404(self):
        """Non-existent Opportunity UUID returns 404."""
        random_uuid = uuid.uuid4()
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{random_uuid}/contact-attempts/"

        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, status.HTTP_404_NOT_FOUND)

        res_post = self.client.post(url, {"type": "CALL"}, format="json")
        self.assertEqual(res_post.status_code, status.HTTP_404_NOT_FOUND)

    def test_malformed_attempt_id_returns_404_not_500(self):
        """Malformed Contact Attempt UUID returns 404, not 500."""
        self.client.force_authenticate(user=self.operator)
        url = f"{self.base_url}not-a-valid-uuid/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_opportunity_attempt_idor_rejected(self):
        """Querying an attempt belonging to Opportunity B under Opportunity A returns 404."""
        attempt_b = record_contact_attempt(self.opp_b.id, type="CALL", notes="Belongs to B", actor=self.operator)

        self.client.force_authenticate(user=self.operator)
        # Attempt to access attempt_b through opp_a's URL
        idor_url = f"{self.base_url}{attempt_b.id}/"
        res = self.client.get(idor_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # But querying it under opp_b succeeds
        legit_url = f"/api/opportunities/opportunities/{self.opp_b.id}/contact-attempts/{attempt_b.id}/"
        res_legit = self.client.get(legit_url)
        self.assertEqual(res_legit.status_code, status.HTTP_200_OK)
        self.assertEqual(res_legit.data["id"], str(attempt_b.id))

    def test_human_readable_identifier_supported_in_url(self):
        """Opportunity canonical identifier (e.g. OPP-2026-000001) works in place of UUID in URL."""
        self.client.force_authenticate(user=self.operator)
        url = f"/api/opportunities/opportunities/{self.opp.identifier}/contact-attempts/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    # -------------------------------------------------------------------------
    # 9. Opportunity Integrity & Lifecycle Non-Mutation
    # -------------------------------------------------------------------------

    def test_contact_attempt_does_not_mutate_opportunity_status_or_version(self):
        """Recording contact attempts does NOT mutate Opportunity status or bump version."""
        initial_status = self.opp.status
        initial_version = self.opp.version

        self.client.force_authenticate(user=self.operator)
        res = self.client.post(
            self.base_url,
            {"type": "CALL", "notes": "First contact interaction"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, initial_status)
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opp.version, initial_version)
        self.assertEqual(self.opp.version, 1)

    def test_contact_attempt_does_not_mutate_opportunity_source_or_broker(self):
        """Recording contact attempts preserves opportunity source provenance and broker attribution."""
        self.client.force_authenticate(user=self.operator)
        self.client.post(self.base_url, {"type": "EMAIL", "notes": "Discussion"}, format="json")

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(self.opp.broker_id, self.broker_org.id)
        self.assertEqual(self.opp.organization_id, self.buyer_org.id)

    def test_user_deletion_preserves_contact_attempt_provenance(self):
        """Deleting the user sets recorded_by to NULL without deleting the contact attempt."""
        temp_operator = User.objects.create_user(email="temp_op@platform.com", password="password")
        SystemRoleAssignment.objects.create(
            user=temp_operator, role=SystemRoleAssignment.SystemRole.OPERATOR
        )
        attempt = record_contact_attempt(self.opp.id, type="CALL", notes="Op will be deleted", actor=temp_operator)

        temp_operator.delete()

        attempt.refresh_from_db()
        self.assertIsNone(attempt.recorded_by)
        self.assertEqual(attempt.notes, "Op will be deleted")

    def test_opportunity_deletion_cascades_to_contact_attempts(self):
        """Deleting parent Opportunity cascades to its contact attempts."""
        attempt = record_contact_attempt(self.opp.id, type="CALL", notes="Cascade test", actor=self.operator)
        self.assertTrue(OpportunityContactAttempt.objects.filter(id=attempt.id).exists())

        self.opp.delete()
        self.assertFalse(OpportunityContactAttempt.objects.filter(id=attempt.id).exists())

    # -------------------------------------------------------------------------
    # 10. Read Privacy (No Accidental Leaks)
    # -------------------------------------------------------------------------

    def test_contact_attempts_not_leaked_in_opportunity_projections(self):
        """Contact attempts are not embedded in external projection serializers."""
        record_contact_attempt(self.opp.id, type="CALL", notes="Internal only log", actor=self.operator)

        # Check OpportunityOrganizationProjectionSerializer
        org_proj = OpportunityOrganizationProjectionSerializer(self.buyer_org).data
        self.assertNotIn("contact_attempts", org_proj)

        # Check OpportunityExternalCounterpartyProjectionSerializer
        ext_proj = OpportunityExternalCounterpartyProjectionSerializer(self.external_cp).data
        self.assertNotIn("contact_attempts", ext_proj)

        # Check OpportunityDetailSerializer
        opp_detail = OpportunityDetailSerializer(self.opp).data
        self.assertNotIn("contact_attempts", opp_detail)
