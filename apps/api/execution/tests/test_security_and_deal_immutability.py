from rest_framework import status
from rest_framework.test import APIClient

from deals.models import (
    Deal,
    DealCostSnapshot,
    DealPartySnapshot,
    DealTermsSnapshot,
)
from execution.enums import ExecutionStatus
from execution.exceptions import CrossObjectIntegrityError
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    complete_milestone,
    create_or_get_execution_for_deal,
    start_milestone,
)
from execution.tests.base import BaseExecutionTestCase


class SecurityAndDealImmutabilityTests(BaseExecutionTestCase):
    """
    Tests for cross-object attack isolation and strict Deal commercial immutability
    (Epic 10 Contract §3, §4, §95, §116, T1003).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.client = APIClient()

    def test_cross_object_attack_rejected(self):
        """
        Cross-object attack protection:
        Milestone from Execution A cannot be mutated using Execution B or Deal B scope.
        """
        deal_a = self.create_sample_deal()
        deal_b = self.create_sample_deal()

        exec_a = create_or_get_execution_for_deal(deal_id=deal_a.id, actor=self.operator_user)
        exec_b = create_or_get_execution_for_deal(deal_id=deal_b.id, actor=self.operator_user)

        m_a = ExecutionMilestone.objects.get(execution=exec_a, definition__code="CONTRACT_SIGNED")

        # 1. Attempt complete Milestone A under Execution B in service
        with self.assertRaises(CrossObjectIntegrityError):
            complete_milestone(
                execution_id=exec_b.id,
                milestone_id=m_a.id,
                expected_version=1,
                actor=self.operator_user,
            )

        # 2. Attempt complete Milestone A under Deal B scope in service
        with self.assertRaises(CrossObjectIntegrityError):
            complete_milestone(
                execution_id=exec_a.id,
                milestone_id=m_a.id,
                expected_version=1,
                actor=self.operator_user,
                deal_id=deal_b.id,
            )

        # 3. Via API: POST /api/execution/{exec_b.id}/milestones/{m_a.id}/complete/
        self.client.force_authenticate(user=self.operator_user)
        url_attack = f"/api/execution/{exec_b.id}/milestones/{m_a.id}/complete/"
        resp = self.client.post(url_attack, {"expected_version": 1}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # 4. Via API: POST /api/deals/{deal_b.id}/execution/milestones/{m_a.id}/complete/
        url_deal_attack = f"/api/deals/{deal_b.id}/execution/milestones/{m_a.id}/complete/"
        resp_deal = self.client.post(url_deal_attack, {"expected_version": 1}, format="json")
        self.assertEqual(resp_deal.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_deal_mutation_across_entire_execution_lifecycle(self):
        """
        Snapshot Deal commercial records before runtime actions.
        Assert immutable Deal commercial truth is 100% identical after:
        - Execution creation
        - Milestone start
        - Milestone complete
        - Terminal closure
        """
        deal = self.create_sample_deal()

        def snapshot_deal():
            d = Deal.objects.get(pk=deal.pk)
            terms = list(DealTermsSnapshot.objects.filter(deal=d).values())
            parties = list(DealPartySnapshot.objects.filter(deal=d).values())
            costs = list(DealCostSnapshot.objects.filter(deal_terms_snapshot__deal=d).values())
            return {
                "id": str(d.id),
                "award_id": str(d.award_id),
                "award_allocation_id": str(d.award_allocation_id),
                "rfq_id": str(d.rfq_id),
                "offer_id": str(d.offer_id),
                "offer_version_id": str(d.offer_version_id),
                "buyer_organization_id": str(d.buyer_organization_id),
                "seller_organization_id": str(d.seller_organization_id),
                "created_at": d.created_at,
                "terms": terms,
                "parties": parties,
                "costs": costs,
            }

        initial_snapshot = snapshot_deal()

        # Action 1: Create execution
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self.assertEqual(snapshot_deal(), initial_snapshot)

        # Action 2: Start CONTRACT_SIGNED milestone
        m_contract = ExecutionMilestone.objects.get(execution=execution, definition__code="CONTRACT_SIGNED")
        start_milestone(
            execution_id=execution.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actor=self.operator_user,
        )
        self.assertEqual(snapshot_deal(), initial_snapshot)

        # Action 3: Complete CONTRACT_SIGNED milestone
        complete_milestone(
            execution_id=execution.id,
            milestone_id=m_contract.id,
            expected_version=2,
            actor=self.operator_user,
        )
        self.assertEqual(snapshot_deal(), initial_snapshot)

        # Action 4: Progress sequentially through all remaining milestones to terminal closure
        definitions = list(execution.workflow_template_version.milestones.all().order_by("sort_order"))
        for defn in definitions:
            m = ExecutionMilestone.objects.get(execution=execution, definition=defn)
            if m.status != ExecutionStatus.CLOSED and m.status != "COMPLETED":
                complete_milestone(
                    execution_id=execution.id,
                    milestone_id=m.id,
                    expected_version=m.version,
                    actor=self.operator_user,
                )

        execution.refresh_from_db()
        self.assertEqual(execution.status, ExecutionStatus.CLOSED)

        # Final assertion: Deal commercial records completely unchanged
        self.assertEqual(snapshot_deal(), initial_snapshot)
