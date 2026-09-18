from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalDimension,
    SignalOutcome,
)
from matching.models import (
    MatchingCandidate,
    MatchingPolicy,
    MatchingPolicyVersion,
    MatchingRun,
    MatchingSignal,
)
from organizations.models import Organization
from trade_hub.models import RFQ, RFQStatus, SupplyListing, SupplyListingStatus


class NumericIntegrityTests(TestCase):
    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Numeric Buyer Org")
        self.supplier_org = Organization.objects.create(name="Numeric Supplier Org")

        self.commodity = CommodityDefinition.objects.create(code="bitumen-num-test", name_en="Bitumen", name_fa="قیر")
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.policy = MatchingPolicy.objects.create(code="numeric-test-policy", name="Numeric Policy")
        self.policy_version = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.PUBLISHED,
        )

        self.run = MatchingRun.objects.create(
            rfq=self.rfq,
            rfq_version=self.rfq.version,
            audience=MatchingAudience.BUYER,
            policy_version=self.policy_version,
            requesting_organization=self.buyer_org,
        )

        self.listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            status=SupplyListingStatus.ACTIVE,
        )

    def test_null_scores_and_rank_allowed(self):
        """Prove that before T0707 final scoring, scores and rank can be null."""
        cand = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            fit_score=None,
            evidence_coverage=None,
            ranking_score=None,
            rank=None,
        )
        self.assertIsNone(cand.fit_score)
        self.assertIsNone(cand.rank)

    def test_candidate_score_ranges_enforced_by_db(self):
        """Prove DB rejects negative scores and scores > 100 for candidate."""
        # 1. Negative fit_score
        cand1 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            fit_score=Decimal("-1.00"),
        )
        with self.assertRaises(ValidationError):
            cand1.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand1])

        # 2. fit_score > 100
        cand2 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            fit_score=Decimal("100.01"),
        )
        with self.assertRaises(ValidationError):
            cand2.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand2])

        # 3. Negative evidence_coverage
        cand3 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            evidence_coverage=Decimal("-0.01"),
        )
        with self.assertRaises(ValidationError):
            cand3.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand3])

        # 4. evidence_coverage > 100
        cand4 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            evidence_coverage=Decimal("101.00"),
        )
        with self.assertRaises(ValidationError):
            cand4.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand4])

        # 5. Negative ranking_score
        cand5 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            ranking_score=Decimal("-5.00"),
        )
        with self.assertRaises(ValidationError):
            cand5.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand5])

        # 6. ranking_score > 100
        cand6 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            ranking_score=Decimal("150.00"),
        )
        with self.assertRaises(ValidationError):
            cand6.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand6])

        # 7. Rank 0 rejected
        cand7 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            rank=0,
        )
        with self.assertRaises(ValidationError):
            cand7.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand7])

        # 8. Negative rank rejected
        cand8 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
            rank=-1,
        )
        with self.assertRaises(ValidationError):
            cand8.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand8])

    def test_signal_numeric_ranges_enforced_by_db(self):
        """Prove DB rejects raw_score < 0, raw_score > 1, and negative weight/contribution."""
        cand = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
        )

        # 1. raw_score < 0
        sig1 = MatchingSignal(
            candidate=cand,
            dimension=SignalDimension.SPECIFICATION,
            code="spec.pen",
            outcome=SignalOutcome.FAIL,
            raw_score=Decimal("-0.0001"),
        )
        with self.assertRaises(ValidationError):
            sig1.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingSignal.objects.bulk_create([sig1])

        # 2. raw_score > 1
        sig2 = MatchingSignal(
            candidate=cand,
            dimension=SignalDimension.SPECIFICATION,
            code="spec.pen",
            outcome=SignalOutcome.PASS,
            raw_score=Decimal("1.0001"),
        )
        with self.assertRaises(ValidationError):
            sig2.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingSignal.objects.bulk_create([sig2])

        # 3. negative weight
        sig3 = MatchingSignal(
            candidate=cand,
            dimension=SignalDimension.SPECIFICATION,
            code="spec.pen",
            outcome=SignalOutcome.PASS,
            weight=Decimal("-1.00"),
        )
        with self.assertRaises(ValidationError):
            sig3.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingSignal.objects.bulk_create([sig3])

        # 4. negative contribution
        sig4 = MatchingSignal(
            candidate=cand,
            dimension=SignalDimension.SPECIFICATION,
            code="spec.pen",
            outcome=SignalOutcome.PASS,
            contribution=Decimal("-0.01"),
        )
        with self.assertRaises(ValidationError):
            sig4.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingSignal.objects.bulk_create([sig4])

    def test_unknown_and_na_outcomes_do_not_require_fake_score(self):
        """Prove that UNKNOWN and NOT_APPLICABLE outcomes can persist with raw_score=None."""
        cand = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
        )

        sig_unknown = MatchingSignal.objects.create(
            candidate=cand,
            dimension=SignalDimension.HISTORY,
            code="history.disputes",
            outcome=SignalOutcome.UNKNOWN,
            raw_score=None,
            weight=Decimal("5.00"),
            contribution=None,
            reason_code="NO_HISTORY_RECORD",
        )
        self.assertIsNone(sig_unknown.raw_score)

        sig_na = MatchingSignal.objects.create(
            candidate=cand,
            dimension=SignalDimension.HISTORY,
            code="history.perf",
            outcome=SignalOutcome.NOT_APPLICABLE,
            raw_score=None,
            weight=None,
            contribution=None,
            reason_code="PILOT_PHASE_NA",
        )
        self.assertIsNone(sig_na.raw_score)
        self.assertIsNone(sig_na.weight)
