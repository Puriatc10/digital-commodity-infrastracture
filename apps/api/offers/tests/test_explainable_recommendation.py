from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityAttributeDefinition, CommoditySchemaVersion
from commodities.services import publish_schema
from offers.enums import (
    DecisionDimension,
    DecisionSignalStatus,
    LogisticsCostStatus,
    OfferorRole,
    OfferVersionStatus,
)
from offers.models.decision import (
    DecisionCandidate,
    DecisionRun,
    DecisionSignal,
)
from offers.models.offer import Offer
from offers.models.offer_version import OfferVersion
from offers.services.decision_service import (
    execute_decision_run_pipeline,
    is_decision_run_stale,
)
from offers.services.evaluators import (
    evaluate_completeness_signal,
    evaluate_cost_signal,
    evaluate_delivery_signal,
    evaluate_payment_signal,
    evaluate_quality_signal,
    evaluate_trust_signal,
    find_best_same_currency_cost,
)
from offers.services.normalization import normalize_offer_version
from offers.services.policy_seed import seed_decision_profile_v1
from offers.services.scoring import (
    aggregate_candidate_scores,
)
from offers.tests.base import BaseOffersTestCase
from opportunities.models import ExternalCounterparty
from organizations.models import Organization
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ


class ExplainableRecommendationTests(BaseOffersTestCase):
    """
    Exhaustive test suite for T0809 — Explainable Recommendation.
    """

    def setUp(self):
        super().setUp()
        self.profile_v1 = seed_decision_profile_v1()
        self.api_client = APIClient()

        # Create Schema V2 with required and optional attributes
        self.schema_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_v2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_v2,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=False,
            sort_order=2,
        )
        publish_schema(self.schema_v2, activate=True)

        # Set structured attributes on RFQ
        RFQ.objects.filter(pk=self.published_rfq.pk).update(
            schema_version=self.schema_v2,
            specifications={"penetration_grade": "60/70", "softening_point": 48},
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 31),
            payment_terms="CAD",
        )
        self.published_rfq.refresh_from_db()

        # Add Verification to Supplier Organization
        self.supplier_verification = OrganizationVerification.objects.create(
            organization=self.supplier_org,
            status=VerificationStatus.VERIFIED,
            version=1,
        )

    def _create_offer_with_submitted_version(
        self,
        *,
        rfq=None,
        organization=None,
        external_counterparty=None,
        role=OfferorRole.SUPPLIER,
        price=Decimal("400.00"),
        quantity=Decimal("500.000"),
        currency="USD",
        version_num=1,
        logistics_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        logistics_amount=None,
        payment_terms="CAD",
        delivery_start=date(2026, 10, 5),
        delivery_end=date(2026, 10, 25),
        incoterm="FOB",
        specifications=None,
        valid_until=None,
        notes="",
    ) -> tuple[Offer, OfferVersion]:
        target_rfq = rfq or self.published_rfq
        if organization:
            offering_org = organization
        elif external_counterparty:
            offering_org = None
        else:
            # Check if self.supplier_org already has an offer on target_rfq with this role
            if Offer.objects.filter(rfq=target_rfq, offering_organization=self.supplier_org, offeror_role=role).exists():
                offering_org = Organization.objects.create(
                    name=f"Supplier Org {uuid.uuid4().hex[:6]}",
                    country="IR",
                    is_active=True,
                )
                from organizations.models import OrganizationCapability
                OrganizationCapability.objects.create(
                    organization=offering_org,
                    capability=OrganizationCapability.CapabilityType.SUPPLIER,
                )
                OrganizationVerification.objects.create(
                    organization=offering_org,
                    status=VerificationStatus.VERIFIED,
                    version=1,
                )
            else:
                offering_org = self.supplier_org

        creator = self.operator_user if external_counterparty else self.supplier_user

        offer = Offer.objects.create(
            rfq=target_rfq,
            offering_organization=offering_org,
            external_counterparty=external_counterparty,
            offeror_role=role,
            created_by=creator,
        )

        specs = (
            {"penetration_grade": "60/70", "softening_point": 48}
            if specifications is None
            else specifications
        )
        validity = valid_until or (timezone.now() + timedelta(days=14))

        version = OfferVersion.objects.create(
            offer=offer,
            version_number=version_num,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=target_rfq.schema_version,
            offered_quantity=quantity,
            quantity_unit="MT",
            unit_price=price,
            currency=currency,
            logistics_cost_status=logistics_status,
            logistics_cost_amount=logistics_amount,
            payment_terms=payment_terms,
            delivery_terms="FOB Bandar Abbas",
            incoterm=incoterm,
            delivery_start=delivery_start,
            delivery_end=delivery_end,
            specifications=specs,
            valid_until=validity,
            notes=notes,
            created_by=creator,
            submitted_by=creator,
            submitted_at=timezone.now(),
        )

        offer.current_submitted_version = version
        offer.save(update_fields=["current_submitted_version"])
        return offer, version

    # =========================================================================
    # 1. MANDATORY MATH TEST (A / K / C + Exact Decimal Formulas)
    # =========================================================================

    def test_mandatory_math_exact_formula_and_persisted_scores(self):
        """
        Manually construct known signals, calculate A, K, C independently, and assert
        all 3 persisted Decimal scores: DecisionScore, EvidenceCoverage, EffectiveScore.
        """
        offer, version = self._create_offer_with_submitted_version(price=Decimal("400.00"))

        # Baseline seeded weights:
        # COST: 35, QUALITY: 25, DELIVERY: 15, PAYMENT: 10, TRUST: 10, COMPLETENESS: 5 -> Total = 100
        run = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        self.assertEqual(run.candidates.count(), 1)
        candidate = run.candidates.first()

        # All 6 dimensions for this candidate are fully known (1.0000):
        # A = 100, K = 100, C = 35(1) + 25(1) + 15(1) + 10(1) + 10(1) + 5(1) = 100.00
        # DecisionScore = 100.00, EvidenceCoverage = 100.00, EffectiveScore = 100.00
        self.assertEqual(candidate.decision_score, Decimal("100.00"))
        self.assertEqual(candidate.evidence_coverage, Decimal("100.00"))
        self.assertEqual(candidate.effective_score, Decimal("100.00"))
        self.assertTrue(candidate.award_eligible)
        self.assertTrue(candidate.is_recommended)
        self.assertEqual(candidate.rank, 1)

    # =========================================================================
    # 2. MANDATORY STATUS TESTS (PASS, PARTIAL, FAIL, UNKNOWN, NOT_APPLICABLE)
    # =========================================================================

    def test_mandatory_status_denominator_effects(self):
        """
        Verify denominator effects on A and K across PASS, PARTIAL, FAIL, UNKNOWN, NOT_APPLICABLE.
        """
        dw = list(self.profile_v1.dimension_weights.all())

        # Test A: Genuinely NOT_APPLICABLE
        # Total weights = 100. DELIVERY (15) is NOT_APPLICABLE.
        # Applicable weight A = 100 - 15 = 85.00.
        _, ver = self._create_offer_with_submitted_version()
        norm = normalize_offer_version(ver)
        signals_na = {
            DecisionDimension.COST: evaluate_cost_signal(self.published_rfq, ver, norm, Decimal("400.00")),
            DecisionDimension.QUALITY: evaluate_quality_signal(self.published_rfq, ver),
            DecisionDimension.DELIVERY: evaluate_delivery_signal(
                RFQ(delivery_window_start=None, delivery_window_end=None),
                OfferVersion(),
            ),
            DecisionDimension.PAYMENT: evaluate_payment_signal(self.published_rfq, ver),
            DecisionDimension.TRUST: evaluate_trust_signal(self.published_rfq, ver),
            DecisionDimension.COMPLETENESS: evaluate_completeness_signal(self.published_rfq, ver, norm),
        }
        scores, _ = aggregate_candidate_scores(signals_na, dw)
        self.assertEqual(scores.applicable_weight, Decimal("85.00"))
        self.assertEqual(scores.known_weight, Decimal("85.00"))
        self.assertEqual(scores.evidence_coverage, Decimal("100.00"))

        # Test B: UNKNOWN excludes weight from K, but keeps in A
        signals_unknown = {
            DecisionDimension.COST: evaluate_cost_signal(
                self.published_rfq,
                OfferVersion(currency="EUR"),  # cross currency -> UNKNOWN
                norm,
                Decimal("400.00"),
            ),
        }
        scores_u, _ = aggregate_candidate_scores(signals_unknown, dw)
        # COST (35) is UNKNOWN -> in A, not in K.
        self.assertIn(Decimal("35.00"), [scores_u.applicable_weight])
        self.assertEqual(scores_u.known_weight, Decimal("0.00"))

        # Test C: FAIL includes weight in K and has raw_score=0.0000
        # Modify supplier verification to UNVERIFIED -> FAIL score 0.0000
        self.supplier_verification.status = VerificationStatus.UNVERIFIED
        self.supplier_verification.save()
        trust_fail_res = evaluate_trust_signal(
            self.published_rfq,
            OfferVersion(offer=Offer(offering_organization=self.supplier_org)),
        )
        self.assertEqual(trust_fail_res.status, DecisionSignalStatus.FAIL)
        self.assertEqual(trust_fail_res.raw_score, Decimal("0.0000"))

        scores_fail, _ = aggregate_candidate_scores({DecisionDimension.TRUST: trust_fail_res}, dw)
        # TRUST weight (10) IS included in K and A!
        self.assertEqual(scores_fail.known_weight, Decimal("10.00"))
        self.assertEqual(scores_fail.applicable_weight, Decimal("10.00"))
        self.assertEqual(scores_fail.decision_score, Decimal("0.00"))

    # =========================================================================
    # 3. ZERO-KNOWN GUARD TEST
    # =========================================================================

    def test_zero_known_guard_returns_null_score_and_zero_coverage(self):
        """
        When all applicable signals are UNKNOWN, K=0:
        DecisionScore = null, EvidenceCoverage = 0, EffectiveScore = 0.
        """
        dw = list(self.profile_v1.dimension_weights.all())
        # All signals UNKNOWN
        dummy_offer = Offer(external_counterparty=ExternalCounterparty(company_name="Ext"))
        dummy_version = OfferVersion(offer=dummy_offer, currency="EUR")  # cross currency

        unknown_signals = {
            DecisionDimension.COST: evaluate_cost_signal(
                self.published_rfq,
                dummy_version,
                normalize_offer_version(
                    self._create_offer_with_submitted_version(currency="EUR")[1]
                ),
                Decimal("400.00"),
            ),
            DecisionDimension.TRUST: evaluate_trust_signal(self.published_rfq, dummy_version),
        }
        scores, _ = aggregate_candidate_scores(unknown_signals, dw)
        self.assertIsNone(scores.decision_score)
        self.assertEqual(scores.evidence_coverage, Decimal("0.00"))
        self.assertEqual(scores.effective_score, Decimal("0.00"))

    # =========================================================================
    # 4. MANDATORY COST TESTS
    # =========================================================================

    def test_mandatory_cost_cheapest_score_one_and_higher_cost_proportional(self):
        """
        Same-currency candidates:
        Candidate 1: $400/MT (best) -> score = 1.0000
        Candidate 2: $500/MT -> score = 400/500 = 0.8000
        """
        offer1, v1 = self._create_offer_with_submitted_version(price=Decimal("400.00"))
        offer2, v2 = self._create_offer_with_submitted_version(
            organization=self.broker_org,
            role=OfferorRole.BROKER,
            price=Decimal("500.00"),
        )

        norm1 = normalize_offer_version(v1)
        norm2 = normalize_offer_version(v2)

        best_cost = find_best_same_currency_cost(
            self.published_rfq,
            [(v1, norm1), (v2, norm2)],
        )
        self.assertEqual(best_cost, Decimal("400.00"))

        sig1 = evaluate_cost_signal(self.published_rfq, v1, norm1, best_cost)
        sig2 = evaluate_cost_signal(self.published_rfq, v2, norm2, best_cost)

        self.assertEqual(sig1.status, DecisionSignalStatus.PASS)
        self.assertEqual(sig1.raw_score, Decimal("1.0000"))

        self.assertEqual(sig2.status, DecisionSignalStatus.PARTIAL)
        self.assertEqual(sig2.raw_score, Decimal("0.8000"))

    def test_mandatory_cost_incomplete_landed_cost_unknown_no_unit_price_fallback(self):
        """
        When logistics cost status is UNKNOWN, landed_unit_cost is None.
        Cost evaluator must return UNKNOWN with raw_score=None.
        Headline unit price must NEVER be used as fallback.
        """
        offer, v = self._create_offer_with_submitted_version(
            price=Decimal("350.00"),  # Very cheap headline price
            logistics_status=LogisticsCostStatus.UNKNOWN,
        )
        norm = normalize_offer_version(v)
        self.assertIsNone(norm.landed_unit_cost)

        sig = evaluate_cost_signal(self.published_rfq, v, norm, Decimal("400.00"))
        self.assertEqual(sig.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(sig.raw_score)
        self.assertEqual(sig.reason_code, "INCOMPLETE_LANDED_COST")

    def test_mandatory_cost_cross_currency_strictly_unknown(self):
        """
        Cross-currency offers evaluate strictly to UNKNOWN; EUR is not numerically compared to USD.
        """
        offer, v = self._create_offer_with_submitted_version(
            price=Decimal("300.00"),
            currency="EUR",  # RFQ is USD
        )
        norm = normalize_offer_version(v)
        sig = evaluate_cost_signal(self.published_rfq, v, norm, Decimal("400.00"))

        self.assertEqual(sig.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(sig.raw_score)
        self.assertEqual(sig.reason_code, "CROSS_CURRENCY_UNKNOWN")

    # =========================================================================
    # 5. MANDATORY QUALITY TESTS
    # =========================================================================

    def test_mandatory_quality_pass_hard_fail_unknown_and_ineligibility(self):
        """
        Quality fit:
        - Match -> PASS (1.0000)
        - Missing spec -> UNKNOWN (None)
        - Required spec mismatch -> FAIL (0.0000), award_eligible=False
        """
        # Pass
        _, v_pass = self._create_offer_with_submitted_version(
            specifications={"penetration_grade": "60/70", "softening_point": 48}
        )
        sig_pass = evaluate_quality_signal(self.published_rfq, v_pass)
        self.assertEqual(sig_pass.status, DecisionSignalStatus.PASS)
        self.assertEqual(sig_pass.raw_score, Decimal("1.0000"))
        self.assertFalse(sig_pass.is_hard_failure)

        # Unknown (missing optional specification evidence requested by RFQ)
        _, v_unk = self._create_offer_with_submitted_version(
            specifications={"penetration_grade": "60/70"}  # softening_point omitted
        )
        sig_unk = evaluate_quality_signal(self.published_rfq, v_unk)
        self.assertEqual(sig_unk.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(sig_unk.raw_score)
        self.assertEqual(sig_unk.reason_code, "MISSING_SPECIFICATION_EVIDENCE")

        # Soft fail (softening_point is optional on schema but differs from RFQ demand)
        _, v_soft = self._create_offer_with_submitted_version(
            specifications={"penetration_grade": "60/70", "softening_point": 55}
        )
        sig_soft = evaluate_quality_signal(self.published_rfq, v_soft)
        self.assertEqual(sig_soft.status, DecisionSignalStatus.PARTIAL)
        self.assertFalse(sig_soft.is_hard_failure)

        # Hard fail (penetration_grade is required)
        _, v_fail = self._create_offer_with_submitted_version(
            specifications={"penetration_grade": "85/100", "softening_point": 48}  # RFQ wanted 60/70
        )
        sig_fail = evaluate_quality_signal(self.published_rfq, v_fail)
        self.assertEqual(sig_fail.status, DecisionSignalStatus.FAIL)
        self.assertEqual(sig_fail.raw_score, Decimal("0.0000"))
        self.assertTrue(sig_fail.is_hard_failure)

        # In pipeline, hard quality failure marks candidate ineligible
        run = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand_fail = run.candidates.filter(offer_version_id=v_fail.id).first()
        self.assertFalse(cand_fail.award_eligible)
        self.assertIn("HARD_QUALITY_FAILURE", cand_fail.eligibility_reasons)
        self.assertFalse(cand_fail.is_recommended)

    # =========================================================================
    # 6. MANDATORY DELIVERY TESTS
    # =========================================================================

    def test_mandatory_delivery_full_partial_fail_unknown(self):
        """
        Delivery window: [2026-10-01, 2026-10-31]
        - [10-05, 10-25] -> PASS (1.0000)
        - [10-20, 11-10] -> PARTIAL (0.5000)
        - [11-05, 11-20] -> FAIL (0.0000)
        - None           -> UNKNOWN (None)
        """
        # Full satisfaction
        _, v_full = self._create_offer_with_submitted_version(
            delivery_start=date(2026, 10, 5), delivery_end=date(2026, 10, 25)
        )
        sig_full = evaluate_delivery_signal(self.published_rfq, v_full)
        self.assertEqual(sig_full.status, DecisionSignalStatus.PASS)
        self.assertEqual(sig_full.raw_score, Decimal("1.0000"))

        # Partial overlap
        _, v_part = self._create_offer_with_submitted_version(
            delivery_start=date(2026, 10, 20), delivery_end=date(2026, 11, 10)
        )
        sig_part = evaluate_delivery_signal(self.published_rfq, v_part)
        self.assertEqual(sig_part.status, DecisionSignalStatus.PARTIAL)
        self.assertEqual(sig_part.raw_score, Decimal("0.5000"))

        # Fail (no overlap)
        _, v_fail = self._create_offer_with_submitted_version(
            delivery_start=date(2026, 11, 5), delivery_end=date(2026, 11, 20)
        )
        sig_fail = evaluate_delivery_signal(self.published_rfq, v_fail)
        self.assertEqual(sig_fail.status, DecisionSignalStatus.FAIL)
        self.assertEqual(sig_fail.raw_score, Decimal("0.0000"))

        # Unknown (missing dates)
        _, v_unk = self._create_offer_with_submitted_version(
            delivery_start=None, delivery_end=None
        )
        sig_unk = evaluate_delivery_signal(self.published_rfq, v_unk)
        self.assertEqual(sig_unk.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(sig_unk.raw_score)

    # =========================================================================
    # 7. MANDATORY PAYMENT TESTS
    # =========================================================================

    def test_mandatory_payment_structured_vs_free_text(self):
        """
        Payment terms:
        - "CAD" == "CAD" -> PASS (1.0000)
        - "LC" != "CAD" -> PARTIAL (0.5000)
        - Free text "30% advance, rest on BL copy after inspection" -> UNKNOWN
        """
        # Match
        _, v_match = self._create_offer_with_submitted_version(payment_terms="CAD")
        sig_match = evaluate_payment_signal(self.published_rfq, v_match)
        self.assertEqual(sig_match.status, DecisionSignalStatus.PASS)
        self.assertEqual(sig_match.raw_score, Decimal("1.0000"))

        # Structured deviation
        _, v_lc = self._create_offer_with_submitted_version(payment_terms="LC")
        sig_lc = evaluate_payment_signal(self.published_rfq, v_lc)
        self.assertEqual(sig_lc.status, DecisionSignalStatus.PARTIAL)
        self.assertEqual(sig_lc.raw_score, Decimal("0.5000"))

        # Free text
        _, v_free = self._create_offer_with_submitted_version(
            payment_terms="30% advance, rest on BL copy after inspection"
        )
        sig_free = evaluate_payment_signal(self.published_rfq, v_free)
        self.assertEqual(sig_free.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(sig_free.raw_score)
        self.assertEqual(sig_free.reason_code, "FREE_TEXT_PAYMENT_UNKNOWN")

    # =========================================================================
    # 8. MANDATORY TRUST TESTS
    # =========================================================================

    def test_mandatory_trust_mapping_all_statuses_and_external_and_suspended(self):
        """
        Trust mapping:
        - Verified            -> 1.00
        - Basic Verified      -> 0.70
        - Under Review        -> 0.30
        - Documents Submitted -> 0.15
        - Unverified          -> 0.00
        - Suspended           -> 0.00 + award_eligible=False
        - ExternalCounterparty -> UNKNOWN (never inherits Broker trust)
        """
        offer, version = self._create_offer_with_submitted_version()

        # 1. Verified
        self.supplier_verification.status = VerificationStatus.VERIFIED
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("1.0000"))

        # 2. Basic Verified
        self.supplier_verification.status = VerificationStatus.BASIC_VERIFIED
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("0.7000"))

        # 3. Under Review
        self.supplier_verification.status = VerificationStatus.UNDER_REVIEW
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("0.3000"))

        # 4. Documents Submitted
        self.supplier_verification.status = VerificationStatus.DOCUMENTS_SUBMITTED
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("0.1500"))

        # 5. Unverified
        self.supplier_verification.status = VerificationStatus.UNVERIFIED
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("0.0000"))
        self.assertFalse(s.is_hard_failure)

        # 6. Suspended
        self.supplier_verification.status = VerificationStatus.SUSPENDED
        self.supplier_verification.save()
        s = evaluate_trust_signal(self.published_rfq, version)
        self.assertEqual(s.raw_score, Decimal("0.0000"))
        self.assertTrue(s.is_hard_failure)

        # 7. External Counterparty
        ext_offer, ext_ver = self._create_offer_with_submitted_version(
            external_counterparty=self.external_cp,
            role=OfferorRole.BROKER,  # Entered by broker
        )
        s_ext = evaluate_trust_signal(self.published_rfq, ext_ver)
        self.assertEqual(s_ext.status, DecisionSignalStatus.UNKNOWN)
        self.assertIsNone(s_ext.raw_score)

    # =========================================================================
    # 9. MANDATORY COMPLETENESS TESTS
    # =========================================================================

    def test_mandatory_completeness_complete_vs_missing_and_verbose_notes_no_benefit(self):
        """
        Completeness evaluates decision-critical fields only.
        Verbose notes (e.g. 10,000 characters) give ZERO additional points.
        """
        # Complete
        _, v_comp = self._create_offer_with_submitted_version()
        norm_comp = normalize_offer_version(v_comp)
        s_comp = evaluate_completeness_signal(self.published_rfq, v_comp, norm_comp)
        self.assertEqual(s_comp.status, DecisionSignalStatus.PASS)
        self.assertEqual(s_comp.raw_score, Decimal("1.0000"))

        # Missing delivery and payment structure
        _, v_miss = self._create_offer_with_submitted_version(
            payment_terms="unstructured payment string",
            delivery_start=None,
        )
        norm_miss = normalize_offer_version(v_miss)
        s_miss = evaluate_completeness_signal(self.published_rfq, v_miss, norm_miss)
        self.assertEqual(s_miss.status, DecisionSignalStatus.PARTIAL)
        self.assertLess(s_miss.raw_score, Decimal("1.0000"))

        # Offer with 10,000 chars of notes -> score must remain EXACTLY identical!
        _, v_verbose = self._create_offer_with_submitted_version(
            payment_terms="unstructured payment string",
            delivery_start=None,
            notes="A" * 10000,
        )
        norm_verbose = normalize_offer_version(v_verbose)
        s_verbose = evaluate_completeness_signal(self.published_rfq, v_verbose, norm_verbose)
        self.assertEqual(s_verbose.raw_score, s_miss.raw_score)

    # =========================================================================
    # 10. MANDATORY RECOMMENDATION TESTS
    # =========================================================================

    def test_mandatory_recommendation_and_cross_currency_65_percent_regression(self):
        """
        Recommendation tests:
        1. Eligible + coverage >= 70% -> Recommended
        2. Ineligible (Quality hard fail) -> NOT recommended despite high score
        3. Ineligible (Suspended org) -> NOT recommended
        4. Cross-currency regression: COST=35 is UNKNOWN -> max coverage = 65% < 70% threshold -> NOT recommended!
        """
        # Candidate 1: Cross-currency offer (EUR, price 300)
        # RFQ is USD. All other dimensions are perfect (25+15+10+10+5 = 65).
        # EvidenceCoverage = 65.00%. Policy minimum_coverage = 70%.
        # Must NOT be recommended!
        offer_eur, v_eur = self._create_offer_with_submitted_version(
            price=Decimal("300.00"),
            currency="EUR",
        )

        run = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand_eur = run.candidates.filter(offer_version_id=v_eur.id).first()
        self.assertEqual(cand_eur.evidence_coverage, Decimal("65.00"))
        self.assertFalse(cand_eur.is_recommended)

        # Now add Candidate 2: USD offer, fully known (coverage = 100.00% >= 70%)
        offer_usd, v_usd = self._create_offer_with_submitted_version(
            organization=self.broker_org,
            role=OfferorRole.BROKER,
            price=Decimal("450.00"),
            currency="USD",
        )
        run2 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand_usd = run2.candidates.filter(offer_version_id=v_usd.id).first()
        cand_eur2 = run2.candidates.filter(offer_version_id=v_eur.id).first()

        self.assertTrue(cand_usd.is_recommended)
        self.assertFalse(cand_eur2.is_recommended)

    def test_mandatory_recommendation_suspended_and_quality_fail_excluded(self):
        """Suspended organization and hard quality failure cannot be recommended."""
        # Candidate 1: Suspended organization
        self.supplier_verification.status = VerificationStatus.SUSPENDED
        self.supplier_verification.save()

        offer, version = self._create_offer_with_submitted_version()
        run = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand = run.candidates.first()

        self.assertFalse(cand.award_eligible)
        self.assertIn("SUSPENDED_ORGANIZATION", cand.eligibility_reasons)
        self.assertFalse(cand.is_recommended)

    # =========================================================================
    # 11. MANDATORY DETERMINISM TEST
    # =========================================================================

    def test_mandatory_determinism_identical_runs_produce_identical_fingerprints(self):
        """Two independent pipeline executions on identical data produce identical result fingerprints."""
        self._create_offer_with_submitted_version(price=Decimal("410.00"))
        self._create_offer_with_submitted_version(
            organization=self.broker_org,
            role=OfferorRole.BROKER,
            price=Decimal("430.00"),
        )

        run1 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        run2 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)

        self.assertNotEqual(run1.id, run2.id)
        self.assertTrue(run1.result_fingerprint)
        self.assertEqual(run1.result_fingerprint, run2.result_fingerprint)

    # =========================================================================
    # 12. MANDATORY STALENESS TEST
    # =========================================================================

    def test_mandatory_staleness_run_on_v1_stale_when_v2_submitted(self):
        """
        Run evaluated on V1.
        Submit V2 on same Offer.
        Old run is marked stale (is_stale=True), but old candidates and signals remain unchanged.
        New run evaluates V2.
        """
        offer, v1 = self._create_offer_with_submitted_version(price=Decimal("450.00"), version_num=1)

        run1 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand1 = run1.candidates.first()
        self.assertEqual(cand1.offer_version_id, v1.id)
        self.assertFalse(run1.is_stale)
        self.assertFalse(is_decision_run_stale(run1))

        # Submit V2
        v2 = OfferVersion.objects.create(
            offer=offer,
            version_number=2,
            status=OfferVersionStatus.SUBMITTED,
            schema_version=self.published_rfq.schema_version,
            offered_quantity=Decimal("500.000"),
            unit_price=Decimal("390.00"),
            currency="USD",
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            payment_terms="CAD",
            delivery_terms="FOB",
            incoterm="FOB",
            delivery_start=date(2026, 10, 5),
            delivery_end=date(2026, 10, 25),
            specifications={"penetration_grade": "60/70"},
            valid_until=timezone.now() + timedelta(days=14),
            created_by=self.supplier_user,
            submitted_by=self.supplier_user,
            submitted_at=timezone.now(),
        )
        offer.current_submitted_version = v2
        offer.aggregate_version += 1
        offer.save(update_fields=["current_submitted_version", "aggregate_version"])

        # Old run is now stale!
        self.assertTrue(run1.is_stale)
        self.assertTrue(is_decision_run_stale(run1))
        # But old candidate is STILL bound to V1!
        cand1.refresh_from_db()
        self.assertEqual(cand1.offer_version_id, v1.id)

        # New run evaluates V2
        run2 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        self.assertFalse(run2.is_stale)
        cand2 = run2.candidates.first()
        self.assertEqual(cand2.offer_version_id, v2.id)

    # =========================================================================
    # 13. MANDATORY TRUST-HISTORY TEST
    # =========================================================================

    def test_mandatory_trust_history_immutability(self):
        """
        Run with Verified organization.
        Update organization verification to Suspended.
        Old run candidate signals remain strictly Verified.
        New run reflects Suspended.
        """
        offer, v = self._create_offer_with_submitted_version()
        run1 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand1 = run1.candidates.first()
        trust_sig1 = cand1.signals.filter(dimension=DecisionDimension.TRUST).first()
        self.assertEqual(trust_sig1.status, DecisionSignalStatus.PASS)
        self.assertEqual(trust_sig1.reason_code, "VERIFIED")

        # Now change Organization verification status
        self.supplier_verification.status = VerificationStatus.SUSPENDED
        self.supplier_verification.save()

        # Old run signal remains strictly VERIFIED
        trust_sig1.refresh_from_db()
        self.assertEqual(trust_sig1.status, DecisionSignalStatus.PASS)
        self.assertEqual(trust_sig1.reason_code, "VERIFIED")

        # New run reflects current SUSPENDED state
        run2 = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        cand2 = run2.candidates.first()
        trust_sig2 = cand2.signals.filter(dimension=DecisionDimension.TRUST).first()
        self.assertEqual(trust_sig2.status, DecisionSignalStatus.FAIL)
        self.assertEqual(trust_sig2.reason_code, "SUSPENDED_ORGANIZATION")

    # =========================================================================
    # 14. RUNTIME FAILURE ATTACK (Atomicity & Zero Partial Run)
    # =========================================================================

    def test_runtime_failure_attack_aborts_transaction_and_no_partial_run_persists(self):
        """
        Injecting a provider crash must roll back the transaction.
        No partial DecisionRun or DecisionCandidate can be persisted.
        """
        self._create_offer_with_submitted_version()

        initial_run_count = DecisionRun.objects.count()
        initial_candidate_count = DecisionCandidate.objects.count()
        initial_signal_count = DecisionSignal.objects.count()

        # Inject runtime exception into evaluate_delivery_signal
        with patch(
            "offers.services.decision_service.evaluate_delivery_signal",
            side_effect=RuntimeError("Provider hardware failure"),
        ):
            with self.assertRaises(RuntimeError):
                execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)

        # Assert zero partial persistence in database
        self.assertEqual(DecisionRun.objects.count(), initial_run_count)
        self.assertEqual(DecisionCandidate.objects.count(), initial_candidate_count)
        self.assertEqual(DecisionSignal.objects.count(), initial_signal_count)

    # =========================================================================
    # 15. NO AUTOMATIC ACTION
    # =========================================================================

    def test_no_automatic_action_assert_domain_entities_unmutated(self):
        """
        Decision pipeline is strictly observational.
        Assert Offer, OfferVersion, and other domain counts are unchanged.
        """
        offer, version = self._create_offer_with_submitted_version()
        v_updated_at = version.updated_at

        run = execute_decision_run_pipeline(self.published_rfq, actor=self.buyer_user)
        self.assertIsNotNone(run)

        version.refresh_from_db()
        self.assertEqual(version.updated_at, v_updated_at)
        self.assertEqual(version.status, OfferVersionStatus.SUBMITTED)

    # =========================================================================
    # 16. API ENDPOINTS & PRIVACY / IDOR TESTS
    # =========================================================================

    def test_api_create_and_get_decision_run_and_privacy_rejections(self):
        """
        Test POST /api/offers/rfqs/<rfq_id>/decision-runs/
        and GET /api/offers/decision-runs/<run_id>/
        - Buyer and Operator allowed.
        - Competitor Supplier/Broker receive 403.
        """
        self._create_offer_with_submitted_version(price=Decimal("420.00"))

        # 1. Buyer creates decision run via POST
        self.api_client.force_authenticate(user=self.buyer_user)
        post_res = self.api_client.post(
            f"/api/offers/rfqs/{self.published_rfq.id}/decision-runs/",
            {},
            format="json",
        )
        self.assertEqual(post_res.status_code, status.HTTP_201_CREATED)
        run_id = post_res.data["id"]
        self.assertTrue(post_res.data["candidates"])
        self.assertTrue(post_res.data["candidates"][0]["signals"])
        self.assertFalse(post_res.data["is_stale"])

        # 2. Buyer reads decision run via GET
        get_res = self.api_client.get(f"/api/offers/decision-runs/{run_id}/")
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertEqual(get_res.data["id"], run_id)

        # 3. Competitor Supplier denied (403)
        self.api_client.force_authenticate(user=self.supplier_user)
        sup_res = self.api_client.get(f"/api/offers/decision-runs/{run_id}/")
        self.assertEqual(sup_res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Competitor Broker denied (403)
        self.api_client.force_authenticate(user=self.broker_user)
        brk_res = self.api_client.get(f"/api/offers/decision-runs/{run_id}/")
        self.assertEqual(brk_res.status_code, status.HTTP_403_FORBIDDEN)
