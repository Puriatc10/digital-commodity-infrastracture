import uuid
from django.test import SimpleTestCase

from matching.enums import SignalOutcome
from matching.rules.self_match import evaluate_self_match


class SelfMatchRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for self-match exclusion rule.
    """

    def test_supplier_self_match_hard_fails(self):
        org_id = uuid.uuid4()
        res = evaluate_self_match(
            rfq_owner_organization_id=org_id,
            candidate_organization_id=org_id,
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "SELF_MATCH_FORBIDDEN")

    def test_broker_self_match_hard_fails(self):
        org_id = uuid.uuid4()
        res = evaluate_self_match(
            rfq_owner_organization_id=org_id,
            candidate_organization_id=org_id,
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "SELF_MATCH_FORBIDDEN")

    def test_distinct_counterparty_passes(self):
        buyer_org_id = uuid.uuid4()
        supplier_org_id = uuid.uuid4()
        res = evaluate_self_match(
            rfq_owner_organization_id=buyer_org_id,
            candidate_organization_id=supplier_org_id,
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "SELF_MATCH_PERMITTED")
