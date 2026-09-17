from datetime import date
from decimal import Decimal
from django.test import SimpleTestCase

from matching.enums import SignalOutcome
from matching.rules.availability import evaluate_availability


class AvailabilityRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for date interval availability matching rule evaluation.
    """

    def test_full_window_covered_passes(self):
        # Requested: July 10 to July 20 (11 days)
        # Candidate: July 1 to July 31 (full coverage)
        res = evaluate_availability(
            requested_start=date(2026, 7, 10),
            requested_end=date(2026, 7, 20),
            candidate_start=date(2026, 7, 1),
            candidate_end=date(2026, 7, 31),
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "AVAILABILITY_FULL_MATCH")

    def test_partial_window_overlap_produces_ratio(self):
        # Requested: July 1 to July 10 (10 days)
        # Candidate: July 6 to July 15 (overlap July 6-10 = 5 days -> ratio = 5/10 = 0.5000)
        res = evaluate_availability(
            requested_start=date(2026, 7, 1),
            requested_end=date(2026, 7, 10),
            candidate_start=date(2026, 7, 6),
            candidate_end=date(2026, 7, 15),
        )
        self.assertEqual(res.outcome, SignalOutcome.PARTIAL)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.5000"))
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "AVAILABILITY_PARTIAL_OVERLAP")

    def test_no_overlap_hard_fails(self):
        # Requested: July 1 to July 10
        # Candidate: July 11 to July 20 (disjoint)
        res = evaluate_availability(
            requested_start=date(2026, 7, 1),
            requested_end=date(2026, 7, 10),
            candidate_start=date(2026, 7, 11),
            candidate_end=date(2026, 7, 20),
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.0000"))
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "AVAILABILITY_NO_OVERLAP")

    def test_exact_boundary_overlap(self):
        # Requested: July 1 to July 10 (10 days)
        # Candidate: July 10 to July 15 (overlap on exactly July 10 = 1 day -> ratio = 1/10 = 0.1000)
        res = evaluate_availability(
            requested_start=date(2026, 7, 1),
            requested_end=date(2026, 7, 10),
            candidate_start=date(2026, 7, 10),
            candidate_end=date(2026, 7, 15),
        )
        self.assertEqual(res.outcome, SignalOutcome.PARTIAL)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.1000"))
        self.assertTrue(res.is_eligible)

    def test_missing_dates_unknown(self):
        res = evaluate_availability(
            requested_start=date(2026, 7, 1),
            requested_end=date(2026, 7, 10),
            candidate_start=None,
            candidate_end=date(2026, 7, 15),
        )
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "AVAILABILITY_MISSING_EVIDENCE")
