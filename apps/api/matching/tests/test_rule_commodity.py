import uuid
from django.test import SimpleTestCase

from matching.enums import SignalOutcome
from matching.rules.commodity import evaluate_commodity


class CommodityRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for exact commodity identity comparison.
    """

    def test_exact_commodity_match(self):
        commodity_id = uuid.uuid4()
        res = evaluate_commodity(
            requested_commodity_id=commodity_id,
            candidate_commodity_id=commodity_id,
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "COMMODITY_MATCH")

    def test_commodity_mismatch_hard_fails(self):
        res = evaluate_commodity(
            requested_commodity_id=uuid.uuid4(),
            candidate_commodity_id=uuid.uuid4(),
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "COMMODITY_MISMATCH")

    def test_organization_supported_commodities_match(self):
        target_comm = uuid.uuid4()
        supported = [uuid.uuid4(), target_comm, uuid.uuid4()]
        res = evaluate_commodity(
            requested_commodity_id=target_comm,
            candidate_supported_commodity_ids=supported,
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)

    def test_organization_supported_commodities_mismatch(self):
        target_comm = uuid.uuid4()
        supported = [uuid.uuid4(), uuid.uuid4()]
        res = evaluate_commodity(
            requested_commodity_id=target_comm,
            candidate_supported_commodity_ids=supported,
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
