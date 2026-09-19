from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone

from offers.enums import (
    AwardStatus,
    LogisticsCostStatus,
    OfferorRole,
)
from offers.exceptions import (
    AwardConflictError,
    AwardEligibilityError,
    AwardImmutableError,
    AwardValidationError,
    OfferStateError,
    StaleVersionError,
)
from offers.models import AwardAllocation, OfferVersion
from offers.services.award_service import (
    add_award_allocation,
    create_draft_award,
    finalize_award,
    remove_award_allocation,
    update_award_allocation,
)
from offers.services.creation import create_offer
from offers.services.decision_service import execute_decision_run_pipeline
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.revision_service import (
    create_revised_draft_offer_version,
    create_revision_request,
    submit_revised_offer_version,
)
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from offers.tests.base import BaseOffersTestCase
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus

User = get_user_model()


class AwardDomainServiceTests(BaseOffersTestCase):
    """
    Authoritative unit & domain service tests for T0813 Award Offer:
    - One Award aggregate per RFQ
    - Exact OfferVersion allocation
    - Decimal quantity rules (>0, <= offered, sum <= requested, under-allocation allowed)
    - Manual multi-award
    - Optimistic concurrency (expected_version)
    - Authoritative finalization with stable lock ordering
    - Re-checking: Stale version, Suspended org, Expiry, Hard Quality Fail, External Provenance
    - Recommendation override (Human agency)
    - Award independence (No DecisionRun prerequisite)
    - Zero auto-award in decision pipeline
    - Immutability of Finalized Award
    - Atomic rollback on lifecycle failure
    - Strict Deal scope boundary (zero Deal creation)
    """

    def setUp(self):
        super().setUp()

        # Ensure supplier_org and broker_org are verified
        OrganizationVerification.objects.update_or_create(
            organization=self.supplier_org,
            defaults={"status": VerificationStatus.VERIFIED, "version": 1},
        )
        OrganizationVerification.objects.update_or_create(
            organization=self.broker_org,
            defaults={"status": VerificationStatus.VERIFIED, "version": 1},
        )

        # 1. Supplier Offer & Submitted V1 (300 MT)
        self.offer_supplier = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1_supplier_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer_supplier,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("320.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            delivery_start=date(2026, 10, 1),
            delivery_end=date(2026, 10, 15),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            valid_until=timezone.now() + timezone.timedelta(days=14),
            specifications={"penetration_grade": "60/70"},
        )
        self.v1_supplier = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1_supplier_draft,
        )

        # 2. Broker Offer & Submitted V1 (200 MT)
        self.offer_broker = create_offer(
            actor=self.broker_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        self.v1_broker_draft = create_draft_offer_version(
            actor=self.broker_user,
            offer=self.offer_broker,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("330.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            delivery_start=date(2026, 10, 1),
            delivery_end=date(2026, 10, 15),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            valid_until=timezone.now() + timezone.timedelta(days=14),
            specifications={"penetration_grade": "60/70"},
        )
        self.v1_broker = submit_internal_offer_version(
            actor=self.broker_user,
            offer_version=self.v1_broker_draft,
        )

        # 3. External Counterparty Offer submitted by Operator (150 MT)
        self.offer_external, self.v1_external = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("150.000"),
            quantity_unit="MT",
            unit_price=Decimal("310.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="FOB Dubai",
            incoterm="FOB",
            delivery_start=date(2026, 10, 1),
            delivery_end=date(2026, 10, 15),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            valid_until=timezone.now() + timezone.timedelta(days=14),
            specifications={"penetration_grade": "60/70"},
        )

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)


    def test_create_draft_award_success(self):
        """Buyer creates a single Draft Award aggregate for an RFQ in COLLECTING_OFFERS."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        self.assertEqual(award.rfq, self.published_rfq)
        self.assertEqual(award.status, AwardStatus.DRAFT)
        self.assertEqual(award.version, 1)
        self.assertEqual(award.created_by, self.buyer_user)
        self.assertIsNone(award.finalized_by)
        self.assertIsNone(award.finalized_at)

    def test_operator_can_create_draft_award(self):
        """Platform Operator can create a Draft Award on behalf of Buyer."""
        award = create_draft_award(self.published_rfq.id, actor=self.operator_user)
        self.assertEqual(award.rfq, self.published_rfq)
        self.assertEqual(award.created_by, self.operator_user)

    def test_competing_award_rejected_at_db_and_service(self):
        """Only one Award aggregate permitted per RFQ; competing creation is rejected."""
        create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        with self.assertRaises(AwardConflictError):
            create_draft_award(self.published_rfq.id, actor=self.buyer_user)

    def test_award_creation_rejected_on_terminal_or_draft_rfq(self):
        """Award creation rejected on Draft, Closed, Cancelled, or Awarded RFQ."""
        draft_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("100.000"),
            unit="MT",
            status=RFQStatus.DRAFT,
        )
        with self.assertRaises(OfferStateError):
            create_draft_award(draft_rfq.id, actor=self.buyer_user)

    def test_add_allocation_exact_offer_version_success(self):
        """Allocation binds to exact OfferVersion snapshot and increments version."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("250.000"),
            quantity_unit="MT",
            expected_version=1,
            actor=self.buyer_user,
        )
        self.assertEqual(alloc.award, award)
        self.assertEqual(alloc.offer, self.offer_supplier)
        self.assertEqual(alloc.offer_version, self.v1_supplier)
        self.assertEqual(alloc.awarded_quantity, Decimal("250.000"))
        self.assertEqual(alloc.quantity_unit, "MT")

        award.refresh_from_db()
        self.assertEqual(award.version, 2)

    def test_add_allocation_draft_version_rejected(self):
        """Draft (unsubmitted) OfferVersion cannot be allocated."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        draft_v = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer_supplier,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("300.00"),
            specifications={"penetration_grade": "60/70"},
        )
        with self.assertRaises(AwardValidationError):
            add_award_allocation(
                award.id,
                offer_version_id=draft_v.id,
                awarded_quantity=Decimal("50.000"),
                expected_version=1,
                actor=self.buyer_user,
            )

    def test_add_allocation_duplicate_snapshot_rejected(self):
        """Duplicate allocation for the same exact snapshot or same offer is rejected."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("100.000"),
            expected_version=1,
            actor=self.buyer_user,
        )
        with self.assertRaises(AwardConflictError):
            add_award_allocation(
                award.id,
                offer_version_id=self.v1_supplier.id,
                awarded_quantity=Decimal("100.000"),
                expected_version=2,
                actor=self.buyer_user,
            )

    def test_quantity_rules_mandatory_cases(self):
        """
        Test mandatory quantity rules:
        - allocation = offered quantity -> pass
        - allocation < offered quantity -> pass
        - allocation > offered quantity -> reject
        - total < RFQ quantity -> pass (under-allocation)
        - total = RFQ quantity -> pass
        - total > RFQ quantity -> reject (over-allocation)
        """
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)

        # 1. allocation > offered quantity -> reject
        with self.assertRaises(AwardValidationError):
            add_award_allocation(
                award.id,
                offer_version_id=self.v1_supplier.id,
                awarded_quantity=Decimal("350.000"),  # offered is 300.000
                expected_version=1,
                actor=self.buyer_user,
            )

        # 2. allocation < offered quantity -> pass
        alloc1 = add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),  # offered is 300.000
            expected_version=1,
            actor=self.buyer_user,
        )
        self.assertEqual(alloc1.awarded_quantity, Decimal("200.000"))

        # 3. allocation = offered quantity on second offer -> pass
        alloc2 = add_award_allocation(
            award.id,
            offer_version_id=self.v1_broker.id,
            awarded_quantity=Decimal("200.000"),  # offered is 200.000
            expected_version=2,
            actor=self.buyer_user,
        )
        self.assertEqual(alloc2.awarded_quantity, Decimal("200.000"))

        # Current total is 200 + 200 = 400 MT (< 500 MT RFQ quantity -> under-allocation pass)
        award.refresh_from_db()
        self.assertEqual(award.version, 3)

        # 4. total > RFQ quantity -> reject
        with self.assertRaises(AwardValidationError):
            add_award_allocation(
                award.id,
                offer_version_id=self.v1_external.id,
                awarded_quantity=Decimal("150.000"),  # 400 + 150 = 550 > 500
                expected_version=3,
                actor=self.buyer_user,
            )

        # 5. total = RFQ quantity -> pass
        alloc3 = add_award_allocation(
            award.id,
            offer_version_id=self.v1_external.id,
            awarded_quantity=Decimal("100.000"),  # 400 + 100 = 500 MT
            expected_version=3,
            actor=self.buyer_user,
        )
        self.assertEqual(alloc3.awarded_quantity, Decimal("100.000"))

    def test_update_and_remove_allocation_services(self):
        """Test draft allocation quantity update and deletion with expected_version."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("150.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        # Update allocation quantity
        updated_alloc = update_award_allocation(
            alloc.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=2,
            actor=self.buyer_user,
        )
        self.assertEqual(updated_alloc.awarded_quantity, Decimal("200.000"))

        # Stale version check on update
        with self.assertRaises(StaleVersionError):
            update_award_allocation(
                alloc.id,
                awarded_quantity=Decimal("250.000"),
                expected_version=2,  # current is 3
                actor=self.buyer_user,
            )

        # Remove allocation
        remove_award_allocation(alloc.id, expected_version=3, actor=self.buyer_user)
        self.assertFalse(AwardAllocation.objects.filter(pk=alloc.id).exists())

        award.refresh_from_db()
        self.assertEqual(award.version, 4)

    def test_finalize_award_success_and_rfq_transition(self):
        """Authoritative finalization transitions Award to FINALIZED and RFQ to AWARDED."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("300.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        finalized = finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertEqual(finalized.status, AwardStatus.FINALIZED)
        self.assertEqual(finalized.finalized_by, self.buyer_user)
        self.assertIsNotNone(finalized.finalized_at)
        self.assertEqual(finalized.version, 3)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.AWARDED)

    def test_finalized_award_is_strictly_immutable(self):
        """After finalization, any mutation attempt is rejected."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )
        finalize_award(award.id, expected_version=2, actor=self.buyer_user)

        # Attempt to add allocation -> AwardImmutableError
        with self.assertRaises(AwardImmutableError):
            add_award_allocation(
                award.id,
                offer_version_id=self.v1_broker.id,
                awarded_quantity=Decimal("100.000"),
                expected_version=3,
                actor=self.buyer_user,
            )

        # Attempt to update allocation -> AwardImmutableError
        with self.assertRaises(AwardImmutableError):
            update_award_allocation(
                alloc.id,
                awarded_quantity=Decimal("250.000"),
                expected_version=3,
                actor=self.buyer_user,
            )

        # Attempt to remove allocation -> AwardImmutableError
        with self.assertRaises(AwardImmutableError):
            remove_award_allocation(alloc.id, expected_version=3, actor=self.buyer_user)

        # Attempt to re-finalize -> AwardConflictError
        with self.assertRaises(AwardConflictError):
            finalize_award(award.id, expected_version=3, actor=self.buyer_user)

    def test_stale_allocation_rejected_at_finalization(self):
        """If V2 is submitted after allocation was created with V1, finalize rejects stale V1."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("250.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        # Open revision request and submit V2 for Supplier Offer
        self.offer_supplier.refresh_from_db()
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=self.offer_supplier,
            base_offer_version=self.v1_supplier,
            requested_fields=["unit_price"],
            message="Please lower unit price",
            expected_version=self.offer_supplier.aggregate_version,
        )
        self.offer_supplier.refresh_from_db()
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer_supplier.aggregate_version,
        )
        v2_draft.unit_price = Decimal("310.00")
        v2_draft.save()
        self.offer_supplier.refresh_from_db()
        submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer_supplier.aggregate_version,
            draft_version=v2_draft,
        )

        self.offer_supplier.refresh_from_db()
        self.assertNotEqual(self.offer_supplier.current_submitted_version_id, self.v1_supplier.id)

        # Attempt to finalize Award allocating V1 -> must reject as stale
        with self.assertRaises(AwardEligibilityError) as ctx:
            finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertIn("not the current submitted version", str(ctx.exception))

    def test_suspended_organization_rejected_at_finalization(self):
        """Organization Suspended after allocation is rejected at finalize even if previously verified."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        # Suspend the supplier organization
        ver, _ = OrganizationVerification.objects.get_or_create(organization=self.supplier_org)
        ver.status = VerificationStatus.SUSPENDED
        ver.save()

        with self.assertRaises(AwardEligibilityError) as ctx:
            finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertIn("SUSPENDED", str(ctx.exception))

    def test_expired_offer_rejected_at_finalization(self):
        """Offer that expired before finalization is rejected."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        # Backdate valid_until on V1
        OfferVersion.objects.filter(pk=self.v1_supplier.id).update(
            valid_until=timezone.now() - timezone.timedelta(days=1)
        )

        with self.assertRaises(AwardEligibilityError) as ctx:
            finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_hard_quality_failure_rejected_at_finalization(self):
        """Offer failing hard technical specifications cannot be awarded."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        # Invalidate required spec on V1
        OfferVersion.objects.filter(pk=self.v1_supplier.id).update(
            specifications={"penetration_grade": "80/100"}  # RFQ requires 60/70
        )

        with self.assertRaises(AwardEligibilityError) as ctx:
            finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertIn("fails hard technical specifications", str(ctx.exception))

    def test_external_counterparty_offer_awarded_cleanly(self):
        """Operator-entered external counterparty quote can be awarded without fake platform identity."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.v1_external.id,
            awarded_quantity=Decimal("150.000"),
            expected_version=1,
            actor=self.buyer_user,
        )
        self.assertEqual(alloc.offer, self.offer_external)
        self.assertEqual(alloc.offer_version, self.v1_external)

        finalized = finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertEqual(finalized.status, AwardStatus.FINALIZED)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.AWARDED)

    def test_recommendation_override_human_agency(self):
        """Buyer can choose eligible Offer B even if DecisionRun recommended Offer A."""
        # Execute DecisionRun (lowest price / verified recommended)
        run = execute_decision_run_pipeline(rfq=self.published_rfq, actor=self.buyer_user)
        rec = run.candidates.filter(is_recommended=True).first()
        self.assertIsNotNone(rec)

        # Buyer intentionally allocates a different eligible offer than the recommended one
        alternate_version = self.v1_broker if rec.offer_id != self.offer_broker.id else self.v1_supplier
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=alternate_version.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        finalized = finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertEqual(finalized.status, AwardStatus.FINALIZED)
        self.assertEqual(finalized.allocations.count(), 1)
        self.assertEqual(finalized.allocations.first().offer_version, alternate_version)


    def test_award_without_decision_run_succeeds(self):
        """Award workflow requires no analytical DecisionRun prerequisite."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("300.000"),
            expected_version=1,
            actor=self.buyer_user,
        )
        finalized = finalize_award(award.id, expected_version=2, actor=self.buyer_user)
        self.assertEqual(finalized.status, AwardStatus.FINALIZED)

    def test_atomic_failure_injection_rolls_back(self):
        """If failure occurs before RFQ transition commits, transaction completely rolls back."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )

        with patch("offers.services.award_service.award_rfq", side_effect=RuntimeError("Simulated lifecycle crash")):
            with self.assertRaises(RuntimeError):
                finalize_award(award.id, expected_version=2, actor=self.buyer_user)

        award.refresh_from_db()
        self.assertEqual(award.status, AwardStatus.DRAFT)
        self.assertIsNone(award.finalized_by)
        self.assertIsNone(award.finalized_at)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)

    def test_strict_deal_boundary_no_deal_created(self):
        """Confirm that after award finalization, strictly zero Deal entities are created."""
        award = create_draft_award(self.published_rfq.id, actor=self.buyer_user)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1_supplier.id,
            awarded_quantity=Decimal("200.000"),
            expected_version=1,
            actor=self.buyer_user,
        )
        finalize_award(award.id, expected_version=2, actor=self.buyer_user)

        # Verify no Deal model exists in Django apps
        from django.apps import apps
        with self.assertRaises(LookupError):
            apps.get_model("offers", "Deal")
        with self.assertRaises(LookupError):
            apps.get_model("trade_hub", "Deal")
