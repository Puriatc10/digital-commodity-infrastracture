from django.test import SimpleTestCase

from matching.enums import SignalOutcome
from matching.rules.capability import evaluate_capability


class CapabilityRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for capability gate evaluation (Supplier / Broker paths).
    """

    def test_supplier_capability_matches(self):
        res = evaluate_capability(
            required_capability="supplier",
            candidate_capabilities=["supplier"],
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "CAPABILITY_MATCH")

    def test_broker_capability_matches(self):
        res = evaluate_capability(
            required_capability="broker",
            candidate_capabilities=["broker"],
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "CAPABILITY_MATCH")

    def test_wrong_capability_hard_fails(self):
        res = evaluate_capability(
            required_capability="supplier",
            candidate_capabilities=["buyer"],
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "CAPABILITY_MISMATCH")

    def test_multi_capability_organization_passes(self):
        res = evaluate_capability(
            required_capability="supplier",
            candidate_capabilities=["buyer", "supplier", "broker"],
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
