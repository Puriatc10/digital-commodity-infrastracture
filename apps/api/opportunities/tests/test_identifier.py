from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from identity.models import SystemRoleAssignment, User
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityIdentifierSequence,
)
from opportunities.services import (
    allocate_opportunity_identifier,
    allocate_opportunity_sequence,
    create_opportunity,
    format_opportunity_identifier,
)
from organizations.models import Organization, OrganizationCapability, OrganizationMembership


class OpportunityIdentifierUnitTests(TestCase):
    """
    Unit tests for Opportunity identifier formatting, allocation, clock injection,
    and annual rollover semantics.
    """

    def setUp(self):
        self.operator = User.objects.create_user(email="op@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)
        self.organization = Organization.objects.create(name="Identifier Org", country="IR")

    def test_format_opportunity_identifier_padding(self):
        """Validates canonical OPP-{YEAR}-{SEQUENCE} formatting with minimum 6-digit zero padding."""
        self.assertEqual(format_opportunity_identifier(2026, 1), "OPP-2026-000001")
        self.assertEqual(format_opportunity_identifier(2026, 124), "OPP-2026-000124")
        self.assertEqual(format_opportunity_identifier(2026, 999999), "OPP-2026-999999")

    def test_format_opportunity_identifier_exceeds_six_digits_no_truncation(self):
        """Sequences exceeding 6 digits must NOT be truncated."""
        self.assertEqual(format_opportunity_identifier(2026, 1000000), "OPP-2026-1000000")
        self.assertEqual(format_opportunity_identifier(2026, 12345678), "OPP-2026-12345678")

    def test_annual_sequence_reset_and_independent_scopes(self):
        """
        Sequence allocator maintains independent counters per calendar year.
        When the calendar year rolls over, sequence resets to 1.
        """
        # Allocate in 2026
        seq_2026_1 = allocate_opportunity_sequence(2026)
        seq_2026_2 = allocate_opportunity_sequence(2026)
        self.assertEqual(seq_2026_1, 1)
        self.assertEqual(seq_2026_2, 2)

        # Allocate in 2027: resets to 1
        seq_2027_1 = allocate_opportunity_sequence(2027)
        self.assertEqual(seq_2027_1, 1)

        # Subsequent 2026 allocation continues from 3
        seq_2026_3 = allocate_opportunity_sequence(2026)
        self.assertEqual(seq_2026_3, 3)

        # Verify DB state of sequences
        seq_rec_2026 = OpportunityIdentifierSequence.objects.get(year=2026)
        seq_rec_2027 = OpportunityIdentifierSequence.objects.get(year=2027)
        self.assertEqual(seq_rec_2026.next_value, 4)
        self.assertEqual(seq_rec_2027.next_value, 2)

    def test_clock_injection_via_as_of(self):
        """Clock injection via as_of determines the year of the allocated identifier."""
        id_2026 = allocate_opportunity_identifier(as_of=datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt_timezone.utc))
        id_2027 = allocate_opportunity_identifier(as_of=datetime(2027, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc))

        self.assertTrue(id_2026.startswith("OPP-2026-"))
        self.assertTrue(id_2027.startswith("OPP-2027-"))

    def test_rollback_failure_leaves_allocator_valid(self):
        """
        If Opportunity creation fails after or during sequence allocation,
        the allocator remains valid and subsequent creations succeed cleanly.
        """
        opp1 = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.organization.id,
            as_of=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(opp1.identifier, "OPP-2026-000001")

        # Opportunity creation intentionally fails inside transaction
        try:
            with transaction.atomic():
                allocate_opportunity_sequence(2026)
                raise ValueError("Simulated catastrophic business failure after allocation")
        except ValueError:
            pass

        # Subsequent creation succeeds without error
        opp2 = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.organization.id,
            as_of=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertTrue(opp2.identifier.startswith("OPP-2026-"))
        self.assertNotEqual(opp1.identifier, opp2.identifier)

    def test_immutability_on_opportunity_update(self):
        """Opportunity identifier is strictly immutable after creation."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.organization.id,
            quantity=Decimal("100.000"),
            notes="Original note",
        )
        original_identifier = opp.identifier
        self.assertTrue(original_identifier.startswith("OPP-"))

        # Updating editable attributes preserves identifier
        opp.notes = "Updated note"
        opp.quantity = Decimal("200.000")
        opp.save()
        opp.refresh_from_db()
        self.assertEqual(opp.identifier, original_identifier)
        self.assertEqual(opp.notes, "Updated note")

        # Attempting to mutate identifier raises ValidationError
        opp.identifier = "OPP-2026-999999"
        with self.assertRaises(ValidationError) as ctx:
            opp.save()
        self.assertIn("identifier", ctx.exception.message_dict)

    def test_direct_db_uniqueness(self):
        """Database enforces UNIQUE constraint on Opportunity.identifier."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.organization.id,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.create(
                    identifier=opp.identifier,
                    direction=OpportunityDirection.DEMAND,
                    organization=self.organization,
                )


class OpportunityIdentifierAPITests(TestCase):
    """
    API contract tests for Opportunity identifier:
    - Read-only response field
    - Mass-assignment protection
    - Exact lookup by identifier preserving authorization
    """

    def setUp(self):
        self.client = APIClient()

        # System roles
        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.buyer_user = User.objects.create_user(email="buyer@test.com", password="password")
        self.buyer_org = Organization.objects.create(name="Buyer Org", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER
        )

        self.opportunity = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            created_by=self.operator,
        )

    def test_create_opportunity_ignores_client_supplied_identifier(self):
        """Client cannot dictate identifier on create; server generates canonical reference."""
        self.client.force_authenticate(user=self.operator)
        forged_identifier = "OPP-2026-999999"

        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "identifier": forged_identifier,
                "direction": "Demand",
                "organization_id": str(self.buyer_org.id),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(res.data["identifier"], forged_identifier)
        self.assertTrue(res.data["identifier"].startswith("OPP-"))

    def test_update_opportunity_ignores_client_supplied_identifier(self):
        """Client cannot alter identifier via PATCH/PUT."""
        self.client.force_authenticate(user=self.operator)
        orig_id = self.opportunity.identifier

        res = self.client.patch(
            f"/api/opportunities/opportunities/{self.opportunity.id}/",
            {"identifier": "OPP-2026-888888", "notes": "Updated note"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["identifier"], orig_id)

        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.identifier, orig_id)

    def test_lookup_by_exact_identifier_operator_success(self):
        """Operator can look up opportunity by exact human-readable identifier via detail endpoint."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.get(f"/api/opportunities/opportunities/{self.opportunity.identifier}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], str(self.opportunity.id))
        self.assertEqual(res.data["identifier"], self.opportunity.identifier)

    def test_lookup_by_identifier_filter_query_param(self):
        """Operator can filter opportunity list by exact identifier query parameter."""
        self.client.force_authenticate(user=self.operator)
        res = self.client.get(f"/api/opportunities/opportunities/?identifier={self.opportunity.identifier}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["identifier"], self.opportunity.identifier)

    def test_lookup_by_identifier_preserves_authorization(self):
        """Non-operator/admin users are forbidden from looking up opportunities by identifier."""
        # Unauthenticated
        res = self.client.get(f"/api/opportunities/opportunities/{self.opportunity.identifier}/")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # Authenticated non-operator (Buyer)
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get(f"/api/opportunities/opportunities/{self.opportunity.identifier}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
