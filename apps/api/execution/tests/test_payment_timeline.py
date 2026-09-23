from decimal import Decimal

from execution.enums import PaymentStatus, TimelineEventType
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    confirm_payment,
    create_or_get_execution_for_deal,
    project_execution_timeline,
    report_payment,
)
from execution.tests.base import BaseExecutionTestCase


class PaymentTimelineTests(BaseExecutionTestCase):
    """
    Tests for deterministic timeline projection of payment monitoring events (Contract §57, §59, T1006).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

    def test_payment_expected_produces_no_payment_timeline_events(self):
        """
        When payment is in EXPECTED status, no payment timeline events are projected.
        Timeline only projects authoritative historical occurrences (Contract §57).
        """
        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertNotIn(TimelineEventType.PAYMENT_REPORTED, event_types)
        self.assertNotIn(TimelineEventType.PAYMENT_CONFIRMED, event_types)

    def test_payment_reported_timeline_event(self):
        """Reporting payment projects deterministic PAYMENT_REPORTED event (priority 26)."""
        rep = report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            reference="TX-998877",
            notes="Buyer transfer executed.",
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.PAYMENT_REPORTED, event_types)

        rep_event = next(
            ev for ev in timeline if ev["event_type"] == TimelineEventType.PAYMENT_REPORTED
        )
        self.assertEqual(rep_event["type_priority"], 26)
        self.assertEqual(rep_event["event_at"], rep.reported_at)
        self.assertEqual(rep_event["actor_id"], str(self.buyer_owner.id))
        self.assertEqual(rep_event["metadata"]["status"], PaymentStatus.REPORTED)
        self.assertEqual(rep_event["metadata"]["reference"], "TX-998877")
        self.assertEqual(rep_event["metadata"]["currency"], rep.currency)
        self.assertEqual(Decimal(rep_event["metadata"]["expected_amount"]), rep.expected_amount)

    def test_payment_confirmed_timeline_event(self):
        """
        Confirming payment projects deterministic PAYMENT_CONFIRMED event (priority 31)
        in addition to the preceding PAYMENT_REPORTED event.
        """
        report_payment(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            reference="INV-CONF-001",
        )
        conf = confirm_payment(
            self.execution.id,
            expected_version=2,
            actor=self.operator_user,
            reference="BANK-ACK-4455",
            notes="Bank confirmed funds credited.",
        )

        timeline = project_execution_timeline(self.execution, actor=self.operator_user)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.PAYMENT_REPORTED, event_types)
        self.assertIn(TimelineEventType.PAYMENT_CONFIRMED, event_types)

        conf_event = next(
            ev for ev in timeline if ev["event_type"] == TimelineEventType.PAYMENT_CONFIRMED
        )
        self.assertEqual(conf_event["type_priority"], 31)
        self.assertEqual(conf_event["event_at"], conf.confirmed_at)
        self.assertEqual(conf_event["actor_id"], str(self.operator_user.id))
        self.assertEqual(conf_event["metadata"]["status"], PaymentStatus.CONFIRMED)
        self.assertEqual(conf_event["metadata"]["reference"], "BANK-ACK-4455")
        self.assertEqual(conf_event["metadata"]["currency"], conf.currency)

    def test_deterministic_timeline_ordering_with_timestamp_tie(self):
        """
        Timestamp ties between events are deterministically broken by stable type priority then ID.
        Priority: PAYMENT_REPORTED (26) comes after LOADING_SCHEDULED (20) and before PAYMENT_CONFIRMED (31).
        """
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)
        confirm_payment(self.execution.id, expected_version=2, actor=self.operator_user)

        timeline = project_execution_timeline(self.execution, actor=self.operator_user)

        # Assert timeline is strictly sorted: (event_at, type_priority, event_id)
        for i in range(len(timeline) - 1):
            curr = timeline[i]
            nxt = timeline[i + 1]
            key_curr = (curr["event_at"], curr["type_priority"], str(curr["event_id"]))
            key_nxt = (nxt["event_at"], nxt["type_priority"], str(nxt["event_id"]))
            self.assertLessEqual(key_curr, key_nxt)
