from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from offers.enums import AwardStatus, LogisticsCostStatus, OfferorRole
from offers.models import Award, Offer
from offers.services.award_service import (
    add_award_allocation,
    create_draft_award,
    finalize_award,
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
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class Epic8HeroFlowIntegrationTests(BaseOffersTestCase):
    """
    Authoritative End-to-End Hero Flow Integration Test for Epic 8:
    Buyer publishes RFQ
    -> Supplier V1 submitted
    -> Broker V1 submitted
    -> Operator external Offer submitted
    -> DecisionRun recommendations
    -> Buyer requests revision on Supplier offer
    -> Supplier submits V2
    -> New DecisionRun evaluates V2
    -> Buyer creates Draft multi-allocation Award (human agency overrides purely algorithmic pick)
    -> Explicit human Finalize
    -> RFQ Awarded
    -> Strict Deal boundary: zero Deal records created.
    """

    def setUp(self):
        super().setUp()

        OrganizationVerification.objects.update_or_create(
            organization=self.supplier_org,
            defaults={"status": VerificationStatus.VERIFIED, "version": 1},
        )
        OrganizationVerification.objects.update_or_create(
            organization=self.broker_org,
            defaults={"status": VerificationStatus.VERIFIED, "version": 1},
        )

    def test_complete_epic8_hero_flow(self):
        """
        Execute the full Epic 8 Hero Flow end-to-end.
        """
        # =====================================================================
        # Step 1: Buyer Publishes RFQ (1,000 MT)
        # =====================================================================
        rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )
        self.assertEqual(rfq.status, RFQStatus.PUBLISHED)

        # =====================================================================
        # Step 2: Supplier Submits Offer V1 (600 MT @ $340)
        # =====================================================================
        supplier_offer = create_offer(
            actor=self.supplier_user,
            rfq=rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        v1_supplier_draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=supplier_offer.id,
            offered_quantity=Decimal("600.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 60 days",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=7),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        supplier_offer.refresh_from_db()
        v1_supplier = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v1_supplier_draft.id,
            expected_version=supplier_offer.aggregate_version,
        )
        supplier_offer.refresh_from_db()
        self.assertEqual(supplier_offer.current_submitted_version_id, v1_supplier.id)

        # =====================================================================
        # Step 3: Broker Submits Offer V1 (400 MT @ $335)
        # =====================================================================
        broker_offer = create_offer(
            actor=self.broker_user,
            rfq=rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        v1_broker_draft = create_draft_offer_version(
            actor=self.broker_user,
            offer=broker_offer.id,
            offered_quantity=Decimal("400.000"),
            quantity_unit="MT",
            unit_price=Decimal("335.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=7),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        broker_offer.refresh_from_db()
        v1_broker = submit_internal_offer_version(
            actor=self.broker_user,
            offer_version=v1_broker_draft.id,
            expected_version=broker_offer.aggregate_version,
        )
        broker_offer.refresh_from_db()
        self.assertEqual(broker_offer.current_submitted_version_id, v1_broker.id)

        # =====================================================================
        # Step 4: Operator Submits External Offer (300 MT @ $350)
        # =====================================================================
        ext_offer, v1_ext = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=rfq,
            opportunity=self.opp_external_qualified,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            valid_until=timezone.now() + timezone.timedelta(days=10),
            payment_terms="Cash against documents",
            delivery_terms="FOB",
            incoterm="FOB",
        )
        ext_offer.refresh_from_db()
        self.assertEqual(ext_offer.current_submitted_version_id, v1_ext.id)

        # Verify 3 submitted offers exist for this RFQ
        self.assertEqual(Offer.objects.filter(rfq=rfq).count(), 3)

        # =====================================================================
        # Step 5: Decision Support Pipeline (DecisionRun 1)
        # =====================================================================
        decision_run_1 = execute_decision_run_pipeline(
            rfq,
            self.buyer_user,
        )
        self.assertIsNotNone(decision_run_1)
        self.assertEqual(decision_run_1.candidates.count(), 3)

        # =====================================================================
        # Step 6: Buyer Requests Revision on Supplier Offer & V2 Submitted
        # =====================================================================
        supplier_offer.refresh_from_db()
        rev_req = create_revision_request(
            actor=self.buyer_user,
            offer=supplier_offer,
            base_offer_version=v1_supplier,
            requested_fields=["unit_price"],
            message="Please match $325/MT to be competitive",
            expected_version=supplier_offer.aggregate_version,
        )
        supplier_offer.refresh_from_db()
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=supplier_offer.aggregate_version,
        )
        v2_draft.unit_price = Decimal("325.00")
        v2_draft.save()
        supplier_offer.refresh_from_db()
        v2_supplier, _ = submit_revised_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=supplier_offer.aggregate_version,
            draft_version=v2_draft,
        )
        supplier_offer.refresh_from_db()
        self.assertEqual(supplier_offer.current_submitted_version_id, v2_supplier.id)

        # =====================================================================
        # Step 7: New Decision Support Pipeline (DecisionRun 2)
        # =====================================================================
        decision_run_2 = execute_decision_run_pipeline(
            rfq,
            self.buyer_user,
        )
        self.assertEqual(decision_run_2.candidates.count(), 3)
        # DecisionRun 2 evaluates supplier's V2, not stale V1
        supplier_candidate = decision_run_2.candidates.get(offer_id=supplier_offer.id)
        self.assertEqual(supplier_candidate.offer_version_id, v2_supplier.id)

        # =====================================================================
        # Step 8: Buyer Creates Draft Multi-Allocation Award
        # Buyer exercises agency: allocates 600 MT to Supplier V2 and 400 MT to Broker V1
        # =====================================================================
        award = create_draft_award(rfq.id, actor=self.buyer_user)
        self.assertEqual(award.status, AwardStatus.DRAFT)
        self.assertEqual(award.version, 1)

        # Allocation 1: Supplier V2 (600 MT)
        alloc1 = add_award_allocation(
            award.id,
            offer_version_id=v2_supplier.id,
            awarded_quantity=Decimal("600.000"),
            expected_version=award.version,
            actor=self.buyer_user,
        )
        award.refresh_from_db()
        self.assertEqual(award.version, 2)

        # Allocation 2: Broker V1 (400 MT)
        alloc2 = add_award_allocation(
            award.id,
            offer_version_id=v1_broker.id,
            awarded_quantity=Decimal("400.000"),
            expected_version=award.version,
            actor=self.buyer_user,
        )
        award.refresh_from_db()
        self.assertEqual(award.version, 3)

        # Check total allocated quantity equals RFQ requested quantity (1,000 MT)
        allocations = award.allocations.all()
        self.assertEqual(allocations.count(), 2)
        total_qty = sum(a.awarded_quantity for a in allocations)
        self.assertEqual(total_qty, Decimal("1000.000"))

        # =====================================================================
        # Step 9: Explicit Human Finalization
        # =====================================================================
        finalized_award = finalize_award(
            award.id,
            expected_version=award.version,
            actor=self.buyer_user,
        )
        self.assertEqual(finalized_award.status, AwardStatus.FINALIZED)
        self.assertEqual(finalized_award.finalized_by, self.buyer_user)
        self.assertIsNotNone(finalized_award.finalized_at)

        # Target RFQ transitions to AWARDED
        rfq.refresh_from_db()
        self.assertEqual(rfq.status, RFQStatus.AWARDED)

        # =====================================================================
        # Step 10: Strict Scope & Deal Boundary Invariants
        # =====================================================================
        # 1. Exactly one Award aggregate exists for this RFQ
        self.assertEqual(Award.objects.filter(rfq=rfq).count(), 1)
        # 2. Allocations preserve exact OfferVersion linkages
        self.assertEqual(alloc1.offer_version_id, v2_supplier.id)
        self.assertEqual(alloc2.offer_version_id, v1_broker.id)
        # 3. Epic 9 Boundary: Verify NO deal objects/tables created
        from django.apps import apps
        deal_model = None
        for model in apps.get_models():
            if model.__name__ in ("Deal", "DealAllocation"):
                deal_model = model
                break
        self.assertIsNone(
            deal_model,
            "CRITICAL EPIC BOUNDARY VIOLATION: Deal or DealAllocation models must not exist in Epic 8!",
        )
