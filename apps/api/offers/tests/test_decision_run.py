from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from offers.enums import (
    DecisionDimension,
    DecisionProfileLifecycleStatus,
    DecisionSignalStatus,
    OfferorRole,
    OfferVersionStatus,
)
from offers.exceptions import (
    DecisionPolicyError,
)
from offers.models.decision import (
    DecisionCandidate,
    DecisionDimensionWeight,
    DecisionProfileVersion,
    DecisionSignal,
)
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from offers.services.comparison import compare_rfq_offers
from offers.services.decision_fingerprint import (
    compute_decision_run_input_fingerprint,
)
from offers.services.decision_service import create_decision_run_foundation
from offers.services.policy_seed import seed_decision_profile_v1
from offers.tests.base import BaseOffersTestCase
from trade_hub.models import RFQ, RFQStatus, RFQVisibility


class DecisionRunTests(BaseOffersTestCase):
    """
    Comprehensive tests for DecisionRun, DecisionCandidate, DecisionSignal, and fingerprinting (T0808).
    """

    def setUp(self):
        super().setUp()
        self.profile_v1 = seed_decision_profile_v1()

    def _create_submitted_offer(
        self,
        *,
        rfq=None,
        organization=None,
        external_counterparty=None,
        role=OfferorRole.SUPPLIER,
        price=Decimal("450.00"),
        quantity=Decimal("300.000"),
        version_num=1,
    ) -> tuple[Offer, OfferVersion]:
        target_rfq = rfq or self.published_rfq
        offer = Offer.objects.create(
            rfq=target_rfq,
            offering_organization=organization or (self.supplier_org if not external_counterparty else None),
            external_counterparty=external_counterparty,
            offeror_role=role,
            created_by=self.operator_user if external_counterparty else self.supplier_user,
        )
        creator = self.operator_user if external_counterparty else self.supplier_user
        version = OfferVersion.objects.create(
            offer=offer,
            version_number=version_num,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=target_rfq.schema_version,
            offered_quantity=quantity,
            quantity_unit="MT",
            unit_price=price,
            currency=target_rfq.currency,
            payment_terms="CAD",
            delivery_terms="FOB",
            incoterm="FOB",
            specifications={"penetration_grade": "60/70"},
            created_by=creator,
            submitted_by=creator,
            submitted_at=timezone.now(),
        )

        offer.current_submitted_version = version
        offer.save(update_fields=["current_submitted_version"])
        return offer, version

    def test_candidate_universe_current_submitted_versions_only(self):
        """Candidate universe materializes only current submitted version per Offer; drafts excluded."""
        # Offer 1: Submitted V1
        offer1, v1 = self._create_submitted_offer(price=Decimal("400.00"))

        # Offer 2: Draft only (unsubmitted)
        offer2 = Offer.objects.create(
            rfq=self.published_rfq,
            offering_organization=self.broker_org,
            offeror_role=OfferorRole.BROKER,
            created_by=self.broker_user,
        )
        OfferVersion.objects.create(
            offer=offer2,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.published_rfq.schema_version,
            offered_quantity=Decimal("200.000"),
            unit_price=Decimal("420.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            created_by=self.broker_user,
        )


        # Offer 2 has current_submitted_version = None

        # Offer 3: External counterparty entered by operator
        offer3, v3 = self._create_submitted_offer(
            external_counterparty=self.external_cp,
            role=OfferorRole.SUPPLIER,
            price=Decimal("410.00"),
        )

        run = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)

        self.assertEqual(run.candidates.count(), 2)
        candidate_version_ids = set(run.candidates.values_list("offer_version_id", flat=True))
        self.assertIn(v1.id, candidate_version_ids)
        self.assertIn(v3.id, candidate_version_ids)
        # Draft offer2 excluded
        self.assertNotIn(offer2.id, run.candidates.values_list("offer_id", flat=True))

        # Award eligibility defaults to None (safe unevaluated representation)
        for cand in run.candidates.all():
            self.assertIsNone(cand.award_eligible)
            self.assertIsNone(cand.decision_score)
            self.assertIsNone(cand.evidence_coverage)
            self.assertIsNone(cand.effective_score)
            self.assertIsNone(cand.rank)

    def test_p0_historical_binding_old_run_v1_unchanged_after_v2_submitted(self):
        """
        P0 Invariant:
        Create run using V1. Then submit V2.
        Verify:
        - old run candidate = V1
        - current comparison = V2
        No historical rewrite.
        """
        offer, v1 = self._create_submitted_offer(price=Decimal("450.00"), version_num=1)

        # Run 1 created when Offer is on V1
        run1 = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)
        self.assertEqual(run1.candidates.count(), 1)
        candidate1 = run1.candidates.first()
        self.assertEqual(candidate1.offer_version_id, v1.id)

        # Now submit V2 on the offer parent
        v2 = OfferVersion.objects.create(
            offer=offer,
            version_number=2,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.published_rfq.schema_version,
            offered_quantity=Decimal("350.000"),
            quantity_unit="MT",
            unit_price=Decimal("430.00"),
            currency=self.published_rfq.currency,
            specifications={"penetration_grade": "60/70"},
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )


        offer.current_submitted_version = v2
        offer.aggregate_version += 1
        offer.save(update_fields=["current_submitted_version", "aggregate_version"])

        # P0 Check 1: Old run candidate is STILL bound to V1
        candidate1.refresh_from_db()
        self.assertEqual(candidate1.offer_version_id, v1.id)
        self.assertEqual(candidate1.offer_version.version_number, 1)

        # P0 Check 2: Current commercial comparison evaluates V2
        comparison = compare_rfq_offers(self.published_rfq, actor=self.buyer_user)
        self.assertEqual(len(comparison.items), 1)
        self.assertEqual(comparison.items[0].offer_version_id, v2.id)
        self.assertEqual(comparison.items[0].version_number, 2)

        # P0 Check 3: A new decision run evaluates V2, not V1
        run2 = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)
        self.assertEqual(run2.candidates.count(), 1)
        candidate2 = run2.candidates.first()
        self.assertEqual(candidate2.offer_version_id, v2.id)
        self.assertEqual(candidate2.offer_version.version_number, 2)

        # Run 1 is STILL V1!
        self.assertEqual(run1.candidates.first().offer_version_id, v1.id)

    def test_cross_rfq_candidate_injection_rejected(self):
        """DecisionCandidate belonging to another RFQ cannot be attached to a run."""
        other_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )
        other_offer, other_version = self._create_submitted_offer(rfq=other_rfq)

        run = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)

        # Attempt to inject candidate from other_rfq into run
        injected = DecisionCandidate(
            decision_run=run,
            offer=other_offer,
            offer_version=other_version,
        )
        with self.assertRaises(ValidationError) as ctx:
            injected.full_clean()
        self.assertIn("belong to the same RFQ", str(ctx.exception))

    def test_fingerprint_deterministic_and_independent_of_order_or_timestamp(self):
        """Fingerprint is identical for identical inputs, independent of candidate list ordering, and ignores timestamps."""
        offer1, v1 = self._create_submitted_offer(price=Decimal("400.00"))
        offer2, v2 = self._create_submitted_offer(
            organization=self.broker_org,
            role=OfferorRole.BROKER,
            price=Decimal("420.00"),
        )

        fp1 = compute_decision_run_input_fingerprint(
            rfq=self.published_rfq,
            candidate_items=[(offer1, v1), (offer2, v2)],
            profile_version=self.profile_v1,
        )

        # Reverse candidate items order -> must produce EXACT same fingerprint
        fp2 = compute_decision_run_input_fingerprint(
            rfq=self.published_rfq,
            candidate_items=[(offer2, v2), (offer1, v1)],
            profile_version=self.profile_v1,
        )
        self.assertEqual(fp1, fp2)

        # Changing an offer version attribute changes the fingerprint
        v1_changed = OfferVersion(
            id=v1.id,
            offer=offer1,
            version_number=v1.version_number,
            status=v1.status,
            offered_quantity=v1.offered_quantity,
            quantity_unit=v1.quantity_unit,
            unit_price=Decimal("405.00"),  # Changed price
            currency=v1.currency,
            payment_terms=v1.payment_terms,
            delivery_terms=v1.delivery_terms,
            incoterm=v1.incoterm,
            specifications=v1.specifications,
        )
        fp3 = compute_decision_run_input_fingerprint(
            rfq=self.published_rfq,
            candidate_items=[(offer1, v1_changed), (offer2, v2)],
            profile_version=self.profile_v1,
        )
        self.assertNotEqual(fp1, fp3)

    def test_policy_v1_run_unchanged_after_policy_v2_published(self):
        """Publishing policy v2 does not alter or rebind existing v1 DecisionRun."""
        self._create_submitted_offer()
        run = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)
        self.assertEqual(run.decision_profile_version_id, self.profile_v1.id)
        self.assertEqual(run.decision_profile_version.version, 1)

        # Create and publish profile v2
        profile = self.profile_v1.profile
        v2 = DecisionProfileVersion.objects.create(
            profile=profile,
            version=2,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("75.00"),
        )
        for dim, weight in [
            (DecisionDimension.COST, Decimal("40.00")),
            (DecisionDimension.QUALITY, Decimal("20.00")),
            (DecisionDimension.DELIVERY, Decimal("15.00")),
            (DecisionDimension.PAYMENT, Decimal("10.00")),
            (DecisionDimension.TRUST, Decimal("10.00")),
            (DecisionDimension.COMPLETENESS, Decimal("5.00")),
        ]:
            DecisionDimensionWeight.objects.create(profile_version=v2, dimension=dim.value, weight=weight)
        v2.status = DecisionProfileLifecycleStatus.PUBLISHED
        v2.save()

        # Existing run is strictly bound to v1
        run.refresh_from_db()
        self.assertEqual(run.decision_profile_version_id, self.profile_v1.id)
        self.assertEqual(run.decision_profile_version.version, 1)

    def test_signal_structured_persistence_and_privacy_sanitization(self):
        """DecisionSignal stores exact Decimal fields and rejects private CRM/contact data."""
        offer, version = self._create_submitted_offer()
        run = create_decision_run_foundation(self.published_rfq, actor=self.buyer_user)
        candidate = run.candidates.first()

        # Valid signal
        signal = DecisionSignal.objects.create(
            candidate=candidate,
            dimension=DecisionDimension.COST,
            code="cost.landed_unit_cost",
            status=DecisionSignalStatus.PASS,
            weight=Decimal("35.00"),
            raw_score=Decimal("0.9500"),
            contribution=Decimal("33.25"),
            expected_value={"unit_price": "450.00", "currency": "USD"},
            actual_value={"unit_price": "450.00", "currency": "USD"},
            reason_code="COST_MATCH",
            snapshot_data={"landed_cost": "450.00", "comparability": "COMPARABLE"},
        )
        signal.refresh_from_db()
        self.assertEqual(signal.weight, Decimal("35.00"))
        self.assertEqual(signal.raw_score, Decimal("0.9500"))
        self.assertEqual(signal.contribution, Decimal("33.25"))

        # Reject private CRM fields in signal snapshot_data
        bad_signal = DecisionSignal(
            candidate=candidate,
            dimension=DecisionDimension.TRUST,
            code="trust.verification",
            status=DecisionSignalStatus.PASS,
            reason_code="VERIFIED",
            snapshot_data={"phone": "+1234567890", "email": "secret@vendor.com"},
        )
        with self.assertRaises(ValidationError) as ctx:
            bad_signal.full_clean()
        self.assertIn("strictly forbidden in DecisionSignal snapshot_data", str(ctx.exception))

    def test_run_requires_published_profile_version(self):
        """Attempting to create a run with a DRAFT profile version fails with DecisionPolicyError."""
        draft_v = DecisionProfileVersion.objects.create(
            profile=self.profile_v1.profile,
            version=99,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("70.00"),
        )
        with self.assertRaises(DecisionPolicyError):
            create_decision_run_foundation(
                self.published_rfq,
                actor=self.buyer_user,
                profile_version=draft_v,
            )
