import copy

from deals.models import DealCostSnapshot, DealPartySnapshot, DealTermsSnapshot
from execution.enums import MilestoneStatus, PaymentStatus
from execution.exceptions import ExecutionValidationError
from execution.models.milestone import ExecutionMilestone
from execution.models.payment import ExecutionPayment
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    complete_milestone,
    confirm_payment,
    create_or_get_execution_for_deal,
    report_payment,
)
from execution.tests.base import BaseExecutionTestCase


class PaymentMilestoneIntegrationTests(BaseExecutionTestCase):
    """
    Tests for PAYMENT_REPORTED milestone integration and commercial Deal immutability (Contract §58, T1006).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

        # Advance milestone 1: CONTRACT_SIGNED
        m_contract = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="CONTRACT_SIGNED"
        )
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actor=self.operator_user,
        )

    def test_milestone_rejected_when_payment_is_expected(self):
        """
        When payment is in EXPECTED status, completing PAYMENT_REPORTED milestone is rejected.
        Payment aggregate is the source of truth; milestone cannot precede payment report.
        """
        payment = ExecutionPayment.objects.get(execution=self.execution)
        self.assertEqual(payment.status, PaymentStatus.EXPECTED)

        m_pay = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="PAYMENT_REPORTED"
        )

        with self.assertRaises(ExecutionValidationError) as ctx:
            complete_milestone(
                execution_id=self.execution.id,
                milestone_id=m_pay.id,
                expected_version=1,
                actor=self.operator_user,
            )

        self.assertIn("requires payment status to be REPORTED or CONFIRMED", str(ctx.exception))
        m_pay.refresh_from_db()
        self.assertEqual(m_pay.status, MilestoneStatus.PENDING)

    def test_milestone_allowed_when_payment_is_reported(self):
        """
        When payment is in REPORTED status, PAYMENT_REPORTED milestone completes successfully.
        Milestone actual_at defaults to payment.reported_at if not explicitly passed.
        """
        rep = report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            reference="SWIFT-12345",
        )
        self.assertEqual(rep.status, PaymentStatus.REPORTED)
        self.assertIsNotNone(rep.reported_at)

        m_pay = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="PAYMENT_REPORTED"
        )
        m_completed = complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_pay.id,
            expected_version=1,
            actor=self.operator_user,
        )

        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)
        self.assertEqual(m_completed.actual_at, rep.reported_at)

    def test_milestone_allowed_when_payment_is_confirmed(self):
        """
        When payment is in CONFIRMED status, PAYMENT_REPORTED milestone completes successfully.
        """
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)
        conf = confirm_payment(self.execution.id, expected_version=2, actor=self.operator_user)
        self.assertEqual(conf.status, PaymentStatus.CONFIRMED)

        m_pay = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="PAYMENT_REPORTED"
        )
        m_completed = complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_pay.id,
            expected_version=1,
            actor=self.operator_user,
        )

        self.assertEqual(m_completed.status, MilestoneStatus.COMPLETED)
        self.assertEqual(m_completed.actual_at, conf.reported_at)

    def test_milestone_completion_does_not_mutate_payment_aggregate(self):
        """
        Completing the milestone does not independently modify the ExecutionPayment aggregate.
        Payment aggregate version, status, and metadata remain untouched.
        """
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)
        payment_before = ExecutionPayment.objects.get(execution=self.execution)

        m_pay = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="PAYMENT_REPORTED"
        )
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_pay.id,
            expected_version=1,
            actor=self.operator_user,
        )

        payment_after = ExecutionPayment.objects.get(execution=self.execution)
        self.assertEqual(payment_after.version, payment_before.version)
        self.assertEqual(payment_after.status, payment_before.status)
        self.assertEqual(payment_after.reported_at, payment_before.reported_at)
        self.assertEqual(payment_after.reported_by, payment_before.reported_by)
        self.assertEqual(payment_after.confirmed_at, payment_before.confirmed_at)
        self.assertEqual(payment_after.confirmed_by, payment_before.confirmed_by)

    def test_commercial_deal_immutability_throughout_payment_lifecycle(self):
        """
        Critical Contract Invariant (§50, §58):
        Deal terms snapshot, cost snapshot, and party snapshot are never mutated
        during payment reporting, confirmation, or milestone completion.
        """
        terms_before = copy.deepcopy(
            DealTermsSnapshot.objects.filter(deal=self.deal).values().first()
        )
        cost_before = copy.deepcopy(
            list(DealCostSnapshot.objects.filter(deal_terms_snapshot__deal=self.deal).values())
        )
        party_before = copy.deepcopy(
            DealPartySnapshot.objects.filter(deal=self.deal).values().first()
        )

        # 1. Report payment
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)

        # 2. Complete milestone
        m_pay = ExecutionMilestone.objects.get(
            execution=self.execution, definition__code="PAYMENT_REPORTED"
        )
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_pay.id,
            expected_version=1,
            actor=self.operator_user,
        )

        # 3. Confirm payment
        confirm_payment(self.execution.id, expected_version=2, actor=self.operator_user)

        terms_after = DealTermsSnapshot.objects.filter(deal=self.deal).values().first()
        cost_after = list(DealCostSnapshot.objects.filter(deal_terms_snapshot__deal=self.deal).values())
        party_after = DealPartySnapshot.objects.filter(deal=self.deal).values().first()

        self.assertEqual(terms_before, terms_after)
        self.assertEqual(cost_before, cost_after)
        self.assertEqual(party_before, party_after)
