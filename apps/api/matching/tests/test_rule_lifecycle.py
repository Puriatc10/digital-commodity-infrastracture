from django.test import SimpleTestCase

from matching.enums import CandidateKind, SignalOutcome
from matching.rules.lifecycle import evaluate_lifecycle


class LifecycleRuleEvaluatorTests(SimpleTestCase):
    """
    Tests for source lifecycle eligibility gate.
    """

    def test_active_supply_listing_passes(self):
        res = evaluate_lifecycle(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            status="active",
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "LIFECYCLE_SUPPLY_LISTING_ACTIVE")

    def test_inactive_supply_listing_states_hard_fail(self):
        for status in ("draft", "expired", "closed"):
            res = evaluate_lifecycle(
                candidate_kind=CandidateKind.SUPPLY_LISTING,
                status=status,
            )
            self.assertEqual(res.outcome, SignalOutcome.FAIL, f"Status '{status}' should fail")
            self.assertTrue(res.is_hard)
            self.assertFalse(res.is_eligible)
            self.assertEqual(res.reason_code, "LIFECYCLE_SUPPLY_LISTING_INACTIVE")

    def test_qualified_supply_opportunity_passes(self):
        res = evaluate_lifecycle(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            status="Qualified",
            direction="Supply",
        )
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, "LIFECYCLE_OPPORTUNITY_QUALIFIED_SUPPLY")

    def test_demand_opportunity_hard_fails(self):
        res = evaluate_lifecycle(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            status="Qualified",
            direction="Demand",
        )
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertFalse(res.is_eligible)
        self.assertEqual(res.reason_code, "LIFECYCLE_OPPORTUNITY_NOT_SUPPLY")

    def test_non_qualified_supply_opportunity_hard_fails(self):
        for status in ("Captured", "Contacted", "Converted", "Lost"):
            res = evaluate_lifecycle(
                candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
                status=status,
                direction="Supply",
            )
            self.assertEqual(res.outcome, SignalOutcome.FAIL)
            self.assertTrue(res.is_hard)
            self.assertFalse(res.is_eligible)
            self.assertEqual(res.reason_code, "LIFECYCLE_OPPORTUNITY_NOT_QUALIFIED")

    def test_organization_active_and_inactive(self):
        res_active = evaluate_lifecycle(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            status="",
            is_active=True,
        )
        self.assertEqual(res_active.outcome, SignalOutcome.PASS)
        self.assertTrue(res_active.is_eligible)

        res_inactive = evaluate_lifecycle(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            status="",
            is_active=False,
        )
        self.assertEqual(res_inactive.outcome, SignalOutcome.FAIL)
        self.assertTrue(res_inactive.is_hard)
        self.assertFalse(res_inactive.is_eligible)
