import datetime
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from commodities.models import CommodityDefinition
from opportunities.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    OpportunityNotFoundError,
    ReservedTransitionError,
    StaleVersionError,
)
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity, update_opportunity
from opportunities.services_lifecycle import (
    convert_opportunity,
    expire_opportunity,
    mark_opportunity_contacted,
    mark_opportunity_lost,
    put_opportunity_on_hold,
    qualify_opportunity,
    reject_opportunity,
    resume_opportunity,
    start_opportunity_matching,
)
from organizations.models import Organization, OrganizationCapability


class OpportunityLifecycleDomainServiceTests(TestCase):
    """
    Comprehensive domain tests for OpportunityLifecycleService state machine.

    Statuses:
    Captured, Contacted, Qualified, Matching, Converted, On Hold, Rejected, Lost, Expired.
    """

    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_60_70",
            name_en="Bitumen 60/70",
            name_fa="قیر ۶۰/۷۰",
        )
        self.buyer_org = Organization.objects.create(name="Alpha Buyer Corp")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.broker_org = Organization.objects.create(name="Prime Brokerage Ltd")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("500.000"),
            unit="MT",
            indicative_price=Decimal("380.00"),
            currency="USD",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
            geography="Rotterdam, Netherlands",
            delivery_window_start=datetime.date(2026, 10, 1),
            delivery_window_end=datetime.date(2026, 10, 31),
            payment_terms="100% LC at sight",
        )

    # -------------------------------------------------------------------------
    # 1. Valid Happy-Path Transitions
    # -------------------------------------------------------------------------

    def test_captured_to_contacted_success(self):
        """Captured transitions to Contacted, increments version, sets contacted_at."""
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opp.version, 1)
        self.assertIsNone(self.opp.contacted_at)

        updated = mark_opportunity_contacted(self.opp.id, expected_version=1)

        self.assertEqual(updated.status, OpportunityStatus.CONTACTED)
        self.assertEqual(updated.version, 2)
        self.assertIsNotNone(updated.contacted_at)

        # Confirm database persistence
        reloaded = Opportunity.objects.get(id=self.opp.id)
        self.assertEqual(reloaded.status, OpportunityStatus.CONTACTED)
        self.assertEqual(reloaded.version, 2)
        self.assertEqual(reloaded.contacted_at, updated.contacted_at)

    def test_captured_to_qualified_direct_success(self):
        """Captured transitions directly to Qualified, increments version, sets qualified_at."""
        updated = qualify_opportunity(self.opp.id, expected_version=1)

        self.assertEqual(updated.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(updated.version, 2)
        self.assertIsNotNone(updated.qualified_at)

    def test_contacted_to_qualified_success(self):
        """Contacted transitions to Qualified, increments version, sets qualified_at."""
        contacted = mark_opportunity_contacted(self.opp.id, expected_version=1)
        self.assertEqual(contacted.version, 2)

        qualified = qualify_opportunity(self.opp.id, expected_version=2)
        self.assertEqual(qualified.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(qualified.version, 3)
        self.assertIsNotNone(qualified.qualified_at)

    def test_qualified_to_matching_success(self):
        """Qualified transitions to Matching, increments version."""
        qualified = qualify_opportunity(self.opp.id, expected_version=1)
        self.assertEqual(qualified.version, 2)

        matching = start_opportunity_matching(self.opp.id, expected_version=2)
        self.assertEqual(matching.status, OpportunityStatus.MATCHING)
        self.assertEqual(matching.version, 3)

    # -------------------------------------------------------------------------
    # 2. On Hold & Authoritative Resumption Semantics
    # -------------------------------------------------------------------------

    def test_put_on_hold_from_captured_records_previous_status_and_reason(self):
        """Putting Captured opportunity on hold stores status_before_hold, held_at, and reason."""
        held = put_opportunity_on_hold(self.opp.id, expected_version=1, reason="Awaiting counterparty response")

        self.assertEqual(held.status, OpportunityStatus.ON_HOLD)
        self.assertEqual(held.status_before_hold, OpportunityStatus.CAPTURED)
        self.assertEqual(held.hold_reason, "Awaiting counterparty response")
        self.assertIsNotNone(held.held_at)
        self.assertEqual(held.version, 2)

    def test_put_on_hold_from_qualified_records_previous_status(self):
        """Putting Qualified opportunity on hold stores Qualified as status_before_hold."""
        qualify_opportunity(self.opp.id, expected_version=1)
        held = put_opportunity_on_hold(self.opp.id, expected_version=2, reason="Market price volatility pause")

        self.assertEqual(held.status, OpportunityStatus.ON_HOLD)
        self.assertEqual(held.status_before_hold, OpportunityStatus.QUALIFIED)
        self.assertEqual(held.version, 3)

    def test_put_on_hold_from_matching_records_previous_status(self):
        """Putting Matching opportunity on hold stores Matching as status_before_hold."""
        qualify_opportunity(self.opp.id, expected_version=1)
        start_opportunity_matching(self.opp.id, expected_version=2)
        held = put_opportunity_on_hold(self.opp.id, expected_version=3, reason="Credit review in progress")

        self.assertEqual(held.status, OpportunityStatus.ON_HOLD)
        self.assertEqual(held.status_before_hold, OpportunityStatus.MATCHING)
        self.assertEqual(held.version, 4)

    def test_put_on_hold_requires_non_empty_reason(self):
        """Empty or whitespace-only reason is rejected when putting on hold."""
        with self.assertRaises(InvalidTransitionError):
            put_opportunity_on_hold(self.opp.id, expected_version=1, reason="")

        with self.assertRaises(InvalidTransitionError):
            put_opportunity_on_hold(self.opp.id, expected_version=1, reason="   ")

    def test_resume_restores_authoritative_status_before_hold(self):
        """Resuming authoritatively restores the pre-hold status and clears status_before_hold."""
        # Hold from Qualified
        qualify_opportunity(self.opp.id, expected_version=1)
        put_opportunity_on_hold(self.opp.id, expected_version=2, reason="Temporary hold")

        resumed = resume_opportunity(self.opp.id, expected_version=3)
        self.assertEqual(resumed.status, OpportunityStatus.QUALIFIED)
        self.assertEqual(resumed.status_before_hold, "")
        self.assertEqual(resumed.version, 4)

    def test_resume_from_non_on_hold_is_rejected(self):
        """Attempting to resume an opportunity that is not On Hold is rejected."""
        with self.assertRaises(InvalidTransitionError):
            resume_opportunity(self.opp.id, expected_version=1)

    # -------------------------------------------------------------------------
    # 3. Terminal Transitions: Reject, Lost, Expire
    # -------------------------------------------------------------------------

    def test_reject_success_from_captured(self):
        """Rejecting records rejected_at, non-empty rejection_reason, increments version."""
        rejected = reject_opportunity(self.opp.id, expected_version=1, reason="Counterparty not reachable")

        self.assertEqual(rejected.status, OpportunityStatus.REJECTED)
        self.assertEqual(rejected.rejection_reason, "Counterparty not reachable")
        self.assertIsNotNone(rejected.rejected_at)
        self.assertEqual(rejected.version, 2)

    def test_reject_requires_non_empty_reason(self):
        """Empty or whitespace-only reason is rejected on reject."""
        with self.assertRaises(InvalidTransitionError):
            reject_opportunity(self.opp.id, expected_version=1, reason="")

        with self.assertRaises(InvalidTransitionError):
            reject_opportunity(self.opp.id, expected_version=1, reason="   ")

    def test_mark_lost_success_from_qualified(self):
        """Marking lost records lost_at, non-empty lost_reason, increments version."""
        qualify_opportunity(self.opp.id, expected_version=1)
        lost = mark_opportunity_lost(self.opp.id, expected_version=2, reason="Competitor offered lower freight")

        self.assertEqual(lost.status, OpportunityStatus.LOST)
        self.assertEqual(lost.lost_reason, "Competitor offered lower freight")
        self.assertIsNotNone(lost.lost_at)
        self.assertEqual(lost.version, 3)

    def test_mark_lost_requires_non_empty_reason(self):
        """Empty or whitespace-only reason is rejected on mark_lost."""
        with self.assertRaises(InvalidTransitionError):
            mark_opportunity_lost(self.opp.id, expected_version=1, reason="")

        with self.assertRaises(InvalidTransitionError):
            mark_opportunity_lost(self.opp.id, expected_version=1, reason="   ")

    def test_expire_success(self):
        """Expiring records expired_at, optional reason, increments version."""
        expired = expire_opportunity(self.opp.id, expected_version=1, reason="Delivery window elapsed")

        self.assertEqual(expired.status, OpportunityStatus.EXPIRED)
        self.assertEqual(expired.expiration_reason, "Delivery window elapsed")
        self.assertIsNotNone(expired.expired_at)
        self.assertEqual(expired.version, 2)

    def test_expire_with_empty_reason_allowed(self):
        """Expiring with empty reason is permitted."""
        expired = expire_opportunity(self.opp.id, expected_version=1)
        self.assertEqual(expired.status, OpportunityStatus.EXPIRED)
        self.assertEqual(expired.expiration_reason, "")

    # -------------------------------------------------------------------------
    # 4. Terminal State Invariants: No Exits Permitted
    # -------------------------------------------------------------------------

    def test_terminal_states_cannot_transition(self):
        """Rejected, Lost, and Expired opportunities cannot transition to any status."""
        for setup_func in [
            lambda: reject_opportunity(self.opp.id, expected_version=self.opp.version, reason="Rejected"),
            lambda: mark_opportunity_lost(self.opp.id, expected_version=self.opp.version, reason="Lost"),
            lambda: expire_opportunity(self.opp.id, expected_version=self.opp.version),
        ]:
            # Reset opportunity to Captured
            Opportunity.objects.filter(id=self.opp.id).update(
                status=OpportunityStatus.CAPTURED,
                version=1,
                status_before_hold="",
            )
            self.opp.refresh_from_db()

            terminal_opp = setup_func()
            v = terminal_opp.version

            with self.assertRaises(InvalidTransitionError):
                mark_opportunity_contacted(self.opp.id, expected_version=v)

            with self.assertRaises(InvalidTransitionError):
                qualify_opportunity(self.opp.id, expected_version=v)

            with self.assertRaises(InvalidTransitionError):
                start_opportunity_matching(self.opp.id, expected_version=v)

            with self.assertRaises(InvalidTransitionError):
                put_opportunity_on_hold(self.opp.id, expected_version=v, reason="Hold attempt")

            with self.assertRaises(InvalidTransitionError):
                resume_opportunity(self.opp.id, expected_version=v)

            with self.assertRaises(InvalidTransitionError):
                reject_opportunity(self.opp.id, expected_version=v, reason="Reject attempt")

            with self.assertRaises(InvalidTransitionError):
                mark_opportunity_lost(self.opp.id, expected_version=v, reason="Lost attempt")

            with self.assertRaises(InvalidTransitionError):
                expire_opportunity(self.opp.id, expected_version=v)

    # -------------------------------------------------------------------------
    # 5. Critical Future-Task Boundary: Converted is Strictly Reserved
    # -------------------------------------------------------------------------

    def test_direct_transition_to_converted_is_reserved(self):
        """Calling convert without an authoritative conversion target raises ReservedTransitionError."""
        qualify_opportunity(self.opp.id, expected_version=1)

        with self.assertRaises(ReservedTransitionError) as ctx:
            convert_opportunity(self.opp.id, expected_version=2, conversion_target=None)

        self.assertIn("strictly reserved", str(ctx.exception))

    def test_convert_from_unqualified_opportunity_is_rejected(self):
        """Even with dummy conversion target, convert from Captured is rejected."""
        dummy_target = object()
        with self.assertRaises(InvalidTransitionError):
            convert_opportunity(self.opp.id, expected_version=1, conversion_target=dummy_target)

    # -------------------------------------------------------------------------
    # 6. Concurrency & expected_version Invariants
    # -------------------------------------------------------------------------

    def test_missing_or_null_expected_version_rejected(self):
        """None or missing expected_version raises InvalidVersionError."""
        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=None)

    def test_invalid_type_expected_version_rejected(self):
        """Non-integer or boolean expected_version raises InvalidVersionError."""
        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=True)

        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=False)

        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version="1")

        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=1.5)

    def test_non_positive_expected_version_rejected(self):
        """expected_version < 1 raises InvalidVersionError."""
        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=0)

        with self.assertRaises(InvalidVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=-1)

    def test_stale_expected_version_raises_stale_version_error(self):
        """expected_version mismatch raises StaleVersionError."""
        # Initial version is 1, caller supplies 2
        with self.assertRaises(StaleVersionError):
            mark_opportunity_contacted(self.opp.id, expected_version=2)

        # After successful transition to version 2, caller supplies stale 1
        mark_opportunity_contacted(self.opp.id, expected_version=1)
        with self.assertRaises(StaleVersionError):
            qualify_opportunity(self.opp.id, expected_version=1)

    # -------------------------------------------------------------------------
    # 7. Provenance Preservation Across Lifecycle
    # -------------------------------------------------------------------------

    def test_provenance_immutability_through_lifecycle(self):
        """
        Lifecycle transitions must never alter core provenance fields:
        identifier, source, broker, direction, organization/external_counterparty, commodity.
        """
        orig_id = self.opp.id
        orig_identifier = self.opp.identifier
        orig_direction = self.opp.direction
        orig_org = self.opp.organization_id
        orig_commodity = self.opp.commodity_id
        orig_source = self.opp.source
        orig_broker = self.opp.broker_id

        # Transition 1: Captured -> Contacted
        opp = mark_opportunity_contacted(self.opp.id, expected_version=1)
        self.assertEqual(opp.id, orig_id)
        self.assertEqual(opp.identifier, orig_identifier)
        self.assertEqual(opp.direction, orig_direction)
        self.assertEqual(opp.organization_id, orig_org)
        self.assertEqual(opp.commodity_id, orig_commodity)
        self.assertEqual(opp.source, orig_source)
        self.assertEqual(opp.broker_id, orig_broker)

        # Transition 2: Contacted -> Qualified
        opp = qualify_opportunity(self.opp.id, expected_version=2)
        self.assertEqual(opp.identifier, orig_identifier)
        self.assertEqual(opp.source, orig_source)
        self.assertEqual(opp.broker_id, orig_broker)

        # Transition 3: Qualified -> On Hold
        opp = put_opportunity_on_hold(self.opp.id, expected_version=3, reason="Hold reason")
        self.assertEqual(opp.identifier, orig_identifier)
        self.assertEqual(opp.source, orig_source)
        self.assertEqual(opp.broker_id, orig_broker)

        # Transition 4: On Hold -> Resume
        opp = resume_opportunity(self.opp.id, expected_version=4)
        self.assertEqual(opp.identifier, orig_identifier)
        self.assertEqual(opp.source, orig_source)
        self.assertEqual(opp.broker_id, orig_broker)

        # Transition 5: Resume -> Matching
        opp = start_opportunity_matching(self.opp.id, expected_version=5)
        self.assertEqual(opp.identifier, orig_identifier)
        self.assertEqual(opp.source, orig_source)
        self.assertEqual(opp.broker_id, orig_broker)

    # -------------------------------------------------------------------------
    # 8. Atomicity & Rollback Verification
    # -------------------------------------------------------------------------

    def test_atomic_rollback_on_failure(self):
        """Simulated failure after mutation rolls back status, version, and timestamps."""
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opp.version, 1)

        # Patch save to raise IntegrityError inside the atomic block
        with patch.object(Opportunity, "save", side_effect=IntegrityError("Simulated DB failure")):
            with self.assertRaises(IntegrityError):
                mark_opportunity_contacted(self.opp.id, expected_version=1)

        # Confirm nothing persisted or partially committed
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(self.opp.version, 1)
        self.assertIsNone(self.opp.contacted_at)

    # -------------------------------------------------------------------------
    # 9. Generic Update Guards
    # -------------------------------------------------------------------------

    def test_generic_update_cannot_mutate_status_or_version(self):
        """Attempting to mutate status or version via update_opportunity is rejected."""
        with self.assertRaises(ValidationError) as ctx:
            update_opportunity(self.opp, data={"status": OpportunityStatus.QUALIFIED})
        self.assertIn("status", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            update_opportunity(self.opp, data={"version": 99})
        self.assertIn("version", ctx.exception.message_dict)

    def test_generic_update_on_terminal_opportunity_rejected(self):
        """Attempting to update commercial terms on a terminal opportunity is rejected."""
        reject_opportunity(self.opp.id, expected_version=1, reason="Deal cancelled")
        self.opp.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            update_opportunity(self.opp, data={"indicative_price": Decimal("390.00")})
        self.assertIn("terminal status", str(ctx.exception))

    def test_identifier_or_uuid_lookup(self):
        """OpportunityLifecycleService resolves by Opportunity instance, UUID, and human-readable identifier."""
        # Using instance
        opp1 = mark_opportunity_contacted(self.opp, expected_version=1)
        self.assertEqual(opp1.status, OpportunityStatus.CONTACTED)

        # Using human-readable identifier string (e.g. OPP-2026-000001)
        opp2 = qualify_opportunity(self.opp.identifier, expected_version=2)
        self.assertEqual(opp2.status, OpportunityStatus.QUALIFIED)

        # Invalid identifier string
        with self.assertRaises(OpportunityNotFoundError):
            qualify_opportunity("NON-EXISTENT-ID", expected_version=3)
