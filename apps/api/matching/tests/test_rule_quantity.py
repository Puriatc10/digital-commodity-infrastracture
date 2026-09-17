from decimal import Decimal
from django.test import SimpleTestCase

from matching.enums import SignalOutcome
from matching.rules.quantity import evaluate_quantity


class QuantityRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for exact Decimal quantity rule evaluation.
    """

    def test_full_quantity_fulfillment_passes(self):
        res = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=Decimal("500.000"),
            candidate_unit="MT",
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "QUANTITY_FULL_MATCH")

    def test_over_quantity_fulfillment_capped_at_one(self):
        res = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=Decimal("1000.000"),
            candidate_unit="MT",
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)

    def test_partial_quantity_fulfillment_remains_eligible(self):
        res = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=Decimal("300.000"),
            candidate_unit="MT",
            require_full_fulfillment=False,
        )
        self.assertEqual(res.outcome, SignalOutcome.PARTIAL)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.6000"))
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "QUANTITY_PARTIAL_MATCH")

    def test_full_fulfillment_required_shortage_hard_fails(self):
        res = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=Decimal("300.000"),
            candidate_unit="MT",
            require_full_fulfillment=True,
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.6000"))
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "QUANTITY_SHORTAGE_FULL_REQUIRED")

    def test_incompatible_units_unknown(self):
        res = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=Decimal("500.000"),
            candidate_unit="Barrels",
        )
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "QUANTITY_INCOMPATIBLE_UNITS")

    def test_missing_quantities_unknown(self):
        res1 = evaluate_quantity(
            requested_quantity=Decimal("500.000"),
            requested_unit="MT",
            candidate_quantity=None,
            candidate_unit="MT",
        )
        self.assertEqual(res1.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res1.raw_score)

        res2 = evaluate_quantity(
            requested_quantity=None,
            requested_unit="MT",
            candidate_quantity=Decimal("500.000"),
            candidate_unit="MT",
        )
        self.assertEqual(res2.outcome, SignalOutcome.UNKNOWN)
