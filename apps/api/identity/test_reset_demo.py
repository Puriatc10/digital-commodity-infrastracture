"""
Tests for Canonical Demo Reset Mechanism (Epic 13, T1308).

Validates:
- Safety guards (rejection of disabled switcher, rejection of production configuration).
- Deterministic baseline restoration after reset.
- Recovery from mutated Demo / Hero flow state back to initial canonical conditions.
- Non-Demo data preservation (unrelated users, organizations, RFQs, opportunities).
- Repeated reset determinism and idempotency (no progressive counter drift).
- Commercial and operational relationship coherence across Deals and Executions.
- Atomic rollback upon failure.
- Django management command `reset_demo` execution.
"""

from decimal import Decimal
import io
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from deals.models import Deal
from execution.enums import ExecutionStatus, MilestoneStatus
from identity.models import SystemRoleAssignment
from identity.reset_demo import reset_demo_environment
from identity.seed_hero import (
    HERO_OPP_IDENTIFIER,
    HERO_RFQ_TAG,
)
from offers.enums import OfferorRole
from offers.models import Offer
from offers.services.creation import create_offer
from offers.services.version_services import create_draft_offer_version
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityIdentifierSequence,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    mark_opportunity_contacted,
    qualify_opportunity,
    record_contact_attempt,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ
from trade_hub.services.rfq_service import RFQService

User = get_user_model()


class DemoResetSafetyTests(TestCase):
    """Verify safety guards rejecting unsafe environments."""

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=False)
    def test_safety_guard_rejects_when_switcher_disabled(self):
        """Reject reset when DEMO_PERSONA_SWITCHER_ENABLED is False."""
        with self.assertRaises(CommandError) as ctx:
            reset_demo_environment()
        self.assertIn("DEMO_PERSONA_SWITCHER_ENABLED", str(ctx.exception))

    @override_settings(
        DEMO_PERSONA_SWITCHER_ENABLED=True,
        SETTINGS_MODULE="config.settings.production",
    )
    def test_safety_guard_rejects_in_production_settings_module(self):
        """Reject reset when production settings module is active."""
        with self.assertRaises(CommandError) as ctx:
            reset_demo_environment()
        self.assertIn("production", str(ctx.exception).lower())

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_safety_guard_rejects_in_production_env_var(self):
        """Reject reset when DJANGO_SETTINGS_MODULE points to production."""
        with mock.patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.production"}):
            with self.assertRaises(CommandError) as ctx:
                reset_demo_environment()
            self.assertIn("production", str(ctx.exception).lower())


@override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
class DemoResetExecutionTests(TestCase):
    """Verify reset correctness, baseline restoration, and idempotency."""

    def test_reset_restores_canonical_baseline(self):
        """Verify reset restores the canonical T1301 and T1302 seed state."""
        out = io.StringIO()
        result = reset_demo_environment(stdout=out)

        self.assertEqual(result["status"], "success")
        summary = result["seed_summary"]

        # 1. Organization Capability Counts
        self.assertEqual(summary["buyers_count"], 5)
        self.assertEqual(summary["suppliers_count"], 9)
        self.assertEqual(summary["brokers_count"], 6)

        # 2. Transactional Entity Counts
        self.assertEqual(summary["rfqs_count"], 23)  # 22 baseline + 1 Hero
        self.assertEqual(summary["offers_count"], 44)
        self.assertEqual(summary["deals_count"], 10)
        self.assertEqual(summary["opportunities_count"], 8)
        self.assertEqual(summary["executions_count"], 10)

        # 3. Hero Scenario State
        hero = summary["hero_scenario"]
        self.assertEqual(hero["hero_rfq_status"], "published")
        self.assertEqual(hero["hero_opportunity_status"], "Captured")
        self.assertEqual(hero["matching_suppliers_count"], 7)
        self.assertEqual(hero["matching_brokers_count"], 3)

        # 4. Critical Invariants
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        self.assertEqual(Offer.objects.filter(rfq=hero_rfq).count(), 0)
        self.assertEqual(Deal.objects.filter(rfq=hero_rfq).count(), 0)

        hero_opp = Opportunity.objects.get(identifier=HERO_OPP_IDENTIFIER)
        self.assertEqual(hero_opp.status, OpportunityStatus.CAPTURED)
        self.assertEqual(hero_opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertIsNotNone(hero_opp.broker)
        self.assertEqual(hero_opp.broker.name, "Demo Brokerage")

    def test_reset_clears_mutated_hero_and_demo_state(self):
        """Verify that mutations simulating Hero Flow or demo play are cleanly restored."""
        # Baseline seed
        reset_demo_environment()

        # Simulate user & Hero Flow mutations
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        supplier_user = User.objects.get(email="supplier@demo.local")
        supplier_org = Organization.objects.get(name="Demo Supplier LLC")
        operator_user = User.objects.get(email="operator@demo.local")
        buyer_user = User.objects.get(email="buyer@demo.local")
        buyer_org = Organization.objects.get(name="Demo Buyer Corp")

        # 1. Submit an offer on Hero RFQ
        offer = create_offer(
            actor=supplier_user,
            rfq=hero_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=supplier_org,
        )
        create_draft_offer_version(
            actor=supplier_user,
            offer=offer,
            offered_quantity=hero_rfq.quantity,
            quantity_unit=hero_rfq.unit,
            unit_price=Decimal("370.00"),
            currency="USD",
            delivery_terms="FOB Bandar Abbas",
            specifications=hero_rfq.specifications,
        )
        self.assertEqual(Offer.objects.filter(rfq=hero_rfq).count(), 1)

        # 2. Advance Hero Opportunity from Captured -> Contacted -> Qualified
        hero_opp = Opportunity.objects.get(identifier=HERO_OPP_IDENTIFIER)
        record_contact_attempt(hero_opp.id, type="call", notes="Test contact attempt", actor=operator_user)
        hero_opp = mark_opportunity_contacted(hero_opp.id, expected_version=hero_opp.version, actor=operator_user)
        hero_opp = qualify_opportunity(hero_opp.id, expected_version=hero_opp.version, actor=operator_user)
        self.assertEqual(hero_opp.status, OpportunityStatus.QUALIFIED)

        # 3. Mutate an organization's verification status
        buyer_5 = Organization.objects.get(name="Arman Civil & Infrastructure Ltd")
        verif = OrganizationVerification.objects.get(organization=buyer_5)
        self.assertEqual(verif.status, VerificationStatus.DOCUMENTS_SUBMITTED)
        verif.status = VerificationStatus.VERIFIED
        verif.save(update_fields=["status"])

        # 4. Create an extraneous Demo RFQ and Opportunity
        extra_rfq = RFQService.create_draft(
            user=buyer_user,
            data={
                "commodity_id": hero_rfq.commodity_id,
                "schema_version_id": hero_rfq.schema_version_id,
                "quantity": Decimal("100.000"),
                "unit": "MT",
                "target_price": Decimal("350.00"),
                "currency": "USD",
                "notes": "[EXTRA-DEMO-RFQ] Extraneous RFQ created during testing.",
            },
            organization_hint=buyer_org.id,
        )
        extra_opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=supplier_org.id,
            commodity_id=hero_rfq.commodity_id,
            quantity=Decimal("100.000"),
            unit="MT",
            notes="[EXTRA-DEMO-OPP] Extraneous Opportunity created during testing.",
            created_by=operator_user,
        )

        self.assertTrue(RFQ.objects.filter(id=extra_rfq.id).exists())
        self.assertTrue(Opportunity.objects.filter(id=extra_opp.id).exists())

        # RUN RESET
        reset_demo_environment()

        # VERIFY RESTORATION
        # A. Hero RFQ has 0 offers again
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        self.assertEqual(Offer.objects.filter(rfq=hero_rfq).count(), 0)
        self.assertEqual(Deal.objects.filter(rfq=hero_rfq).count(), 0)
        self.assertEqual(hero_rfq.status, "published")

        # B. Hero Opportunity is in Captured status again
        hero_opp = Opportunity.objects.get(identifier=HERO_OPP_IDENTIFIER)
        self.assertEqual(hero_opp.status, OpportunityStatus.CAPTURED)

        # C. Verification status of buyer_5 restored to DOCUMENTS_SUBMITTED
        buyer_5_verif = OrganizationVerification.objects.get(organization=buyer_5)
        self.assertEqual(buyer_5_verif.status, VerificationStatus.DOCUMENTS_SUBMITTED)

        # D. Extraneous RFQ and Opportunity are removed
        self.assertFalse(RFQ.objects.filter(id=extra_rfq.id).exists())
        self.assertFalse(Opportunity.objects.filter(id=extra_opp.id).exists())

        # E. Total canonical RFQ count is exactly 23
        self.assertEqual(RFQ.objects.count(), 23)

    def test_non_demo_data_is_preserved_through_reset(self):
        """Verify that non-demo organizations, users, and RFQs are never touched."""
        # Baseline seed
        reset_demo_environment()

        # Create independent non-demo user and organization
        real_user = User.objects.create(email="trader@real-global-petro.com")
        real_org = Organization.objects.create(
            name="Real Global Petrochemicals SA",
            registration_identifier="FR-REG-987654",
            country="FR",
            website="https://www.real-global-petro.com",
            is_active=True,
        )
        real_membership = OrganizationMembership.objects.create(
            user=real_user,
            organization=real_org,
            role="owner",
        )
        real_capability = OrganizationCapability.objects.create(
            organization=real_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )

        # Create independent non-demo RFQ
        hero_rfq = RFQ.objects.get(notes__contains=HERO_RFQ_TAG)
        real_rfq = RFQService.create_draft(
            user=real_user,
            data={
                "commodity_id": hero_rfq.commodity_id,
                "schema_version_id": hero_rfq.schema_version_id,
                "quantity": Decimal("250.000"),
                "unit": "MT",
                "target_price": Decimal("390.00"),
                "currency": "EUR",
                "notes": "Legitimate non-demo commercial procurement requirement.",
            },
            organization_hint=real_org.id,
        )

        # Create independent non-demo Opportunity
        real_opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=real_org.id,
            commodity_id=hero_rfq.commodity_id,
            quantity=Decimal("250.000"),
            unit="MT",
            indicative_price=Decimal("390.00"),
            currency="EUR",
            notes="Independent non-demo customer lead.",
            created_by=real_user,
        )

        # RUN RESET
        reset_demo_environment()

        # ASSERT NON-DEMO DATA REMAINS COMPLETELY UNTOUCHED
        self.assertTrue(User.objects.filter(id=real_user.id).exists())
        self.assertTrue(Organization.objects.filter(id=real_org.id).exists())
        self.assertTrue(OrganizationMembership.objects.filter(id=real_membership.id).exists())
        self.assertTrue(OrganizationCapability.objects.filter(id=real_capability.id).exists())
        self.assertTrue(RFQ.objects.filter(id=real_rfq.id).exists())
        self.assertTrue(Opportunity.objects.filter(id=real_opp.id).exists())

        # Cleanup non-demo records
        real_rfq.delete()
        real_opp.delete()
        real_capability.delete()
        real_membership.delete()
        real_org.delete()
        real_user.delete()

    def test_repeated_resets_are_deterministic_and_idempotent(self):
        """Verify that running reset repeatedly produces stable datasets without counter drift."""
        # Run 1
        res_1 = reset_demo_environment()
        opp_identifiers_1 = list(
            Opportunity.objects.order_by("identifier").values_list("identifier", flat=True)
        )
        seq_1 = OpportunityIdentifierSequence.objects.get(year=2026).next_value

        # Run 2
        res_2 = reset_demo_environment()
        opp_identifiers_2 = list(
            Opportunity.objects.order_by("identifier").values_list("identifier", flat=True)
        )
        seq_2 = OpportunityIdentifierSequence.objects.get(year=2026).next_value

        # Run 3
        res_3 = reset_demo_environment()
        opp_identifiers_3 = list(
            Opportunity.objects.order_by("identifier").values_list("identifier", flat=True)
        )
        seq_3 = OpportunityIdentifierSequence.objects.get(year=2026).next_value

        # Identical counts
        self.assertEqual(res_1["seed_summary"]["rfqs_count"], res_2["seed_summary"]["rfqs_count"])
        self.assertEqual(res_2["seed_summary"]["rfqs_count"], res_3["seed_summary"]["rfqs_count"])

        # Identical Opportunity Identifiers (no progressive counter drift)
        self.assertEqual(opp_identifiers_1, opp_identifiers_2)
        self.assertEqual(opp_identifiers_2, opp_identifiers_3)
        self.assertEqual(seq_1, seq_2)
        self.assertEqual(seq_2, seq_3)

        # Expected canonical opportunities: OPP-2026-000001 through OPP-2026-000007 + OPP-2026-000124
        self.assertIn("OPP-2026-000001", opp_identifiers_1)
        self.assertIn("OPP-2026-000007", opp_identifiers_1)
        self.assertIn("OPP-2026-000124", opp_identifiers_1)

    def test_relationships_coherence_after_reset(self):
        """Verify that Deal, Snapshot, Attribution, and Execution relationships remain coherent."""
        reset_demo_environment()

        # Verify Deals 1-10 have complete terms snapshots and executions
        deals = Deal.objects.all()
        self.assertEqual(deals.count(), 10)

        for deal in deals:
            self.assertIsNotNone(deal.terms_snapshot)
            self.assertIsNotNone(deal.terms_snapshot.cost_snapshots)
            self.assertGreaterEqual(deal.party_snapshots.count(), 2)
            self.assertIsNotNone(deal.execution)

        # Verify Deal 1 & 2 are CLOSED with 10 milestones
        deal_1 = Deal.objects.filter(rfq__notes__contains="[DEMO-RFQ-01]").first()
        self.assertIsNotNone(deal_1)
        self.assertEqual(deal_1.execution.status, ExecutionStatus.CLOSED)
        self.assertEqual(deal_1.execution.milestones.count(), 10)
        self.assertEqual(
            deal_1.execution.milestones.filter(status=MilestoneStatus.COMPLETED).count(), 10
        )

        # Verify Deal 10 is OPEN with 2 milestones completed
        deal_10 = Deal.objects.filter(rfq__notes__contains="[DEMO-RFQ-10]").first()
        self.assertIsNotNone(deal_10)
        self.assertEqual(deal_10.execution.status, ExecutionStatus.OPEN)
        self.assertEqual(
            deal_10.execution.milestones.filter(status=MilestoneStatus.COMPLETED).count(), 2
        )

        # Verify System Roles: operator and admin only
        operators = SystemRoleAssignment.objects.filter(role="operator")
        admins = SystemRoleAssignment.objects.filter(role="admin")
        self.assertEqual(operators.count(), 1)
        self.assertEqual(operators.first().user.email, "operator@demo.local")
        self.assertEqual(admins.count(), 1)
        self.assertEqual(admins.first().user.email, "admin@demo.local")

    def test_atomic_rollback_on_failure(self):
        """Verify that a failure during reset rolls back database modifications cleanly."""
        # Initial baseline seed
        reset_demo_environment()
        initial_rfqs = RFQ.objects.count()

        # Simulate unexpected failure during seed step
        with mock.patch("identity.reset_demo.seed_demo_dataset", side_effect=RuntimeError("Simulated failure")):
            with self.assertRaises(RuntimeError):
                reset_demo_environment()

        # Verify that transaction rolled back and didn't leave zero RFQs
        self.assertEqual(RFQ.objects.count(), initial_rfqs)

    def test_management_command_reset_demo(self):
        """Verify that python manage.py reset_demo management command executes successfully."""
        out = io.StringIO()
        call_command("reset_demo", stdout=out)
        output = out.getvalue()

        self.assertIn("Starting Demo environment reset", output)
        self.assertIn("Successfully reset and restored canonical Demo environment", output)
        self.assertEqual(RFQ.objects.count(), 23)
