from datetime import datetime, timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import TimelineEventType
from execution.models.milestone import ExecutionMilestone
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    add_milestone_definition,
    complete_milestone,
    create_draft_version,
    create_or_get_execution_for_deal,
    project_execution_timeline,
    publish_version,
)
from execution.tests.base import BaseExecutionTestCase


class TimelineProjectionTests(BaseExecutionTestCase):
    """Tests for deterministic execution timeline projection and ordering (Epic 10 Contract §32, §33, §34, T1003)."""

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_timeline_projection_sources_and_events(self):
        """Timeline contains EXECUTION_CREATED and auto-completed AWARDED events."""
        events = project_execution_timeline(self.execution, actor=self.operator_user)
        self.assertGreaterEqual(len(events), 2)

        # First event is EXECUTION_CREATED
        self.assertEqual(events[0]["event_type"], TimelineEventType.EXECUTION_CREATED)
        self.assertEqual(events[0]["metadata"]["workflow_version"], 1)

        # Second event is MILESTONE_COMPLETED for AWARDED
        self.assertEqual(events[1]["event_type"], TimelineEventType.MILESTONE_COMPLETED)
        self.assertEqual(events[1]["milestone_code"], "AWARDED")
        self.assertEqual(events[1]["milestone_name_en"], "Awarded")
        self.assertEqual(events[1]["milestone_name_fa"], "واگذاری معامله")

    def test_timeline_ordering_with_explicit_timestamp_ties(self):
        """
        When events share the exact same timestamp, ordering is strictly determined by:
        stable_type_priority ASC -> stable_id ASC.
        """
        fixed_time = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

        # Set execution started_at to fixed_time
        self.execution.started_at = fixed_time
        self.execution.save(update_fields=["started_at"])

        # Complete CONTRACT_SIGNED at exact same fixed_time
        m_contract = ExecutionMilestone.objects.get(execution=self.execution, definition__code="CONTRACT_SIGNED")
        complete_milestone(
            execution_id=self.execution.id,
            milestone_id=m_contract.id,
            expected_version=1,
            actual_at=fixed_time,
            actor=self.operator_user,
        )

        # Set AWARDED actual_at to exact same fixed_time
        m_awarded = ExecutionMilestone.objects.get(execution=self.execution, definition__code="AWARDED")
        ExecutionMilestone.objects.filter(pk=m_awarded.pk).update(actual_at=fixed_time)

        events = project_execution_timeline(self.execution, actor=self.operator_user)

        tied_events = [ev for ev in events if ev["event_at"] == fixed_time]
        self.assertEqual(len(tied_events), 3)

        # Expected priority:
        # EXECUTION_CREATED (10) < MILESTONE_COMPLETED (30)
        self.assertEqual(tied_events[0]["event_type"], TimelineEventType.EXECUTION_CREATED)
        self.assertEqual(tied_events[1]["event_type"], TimelineEventType.MILESTONE_COMPLETED)
        self.assertEqual(tied_events[2]["event_type"], TimelineEventType.MILESTONE_COMPLETED)

        # Between the two MILESTONE_COMPLETED events with identical priority (30), stable_id ASC decides:
        id1 = tied_events[1]["event_id"]
        id2 = tied_events[2]["event_id"]
        self.assertLess(id1, id2)

    def test_historical_rendering_uses_bound_workflow_definitions(self):
        """
        After template version 2 is published with modified labels,
        the existing Execution still renders the version 1 definition labels and metadata.
        """
        template = self.bitumen_v1.template
        # Create and publish v2 with modified labels
        v2 = create_draft_version(template, change_summary="v2 labels", actor=self.operator_user)
        add_milestone_definition(
            v2,
            code="AWARDED",
            name_fa="واگذاری معامله ویرایش دو",
            name_en="Awarded V2 Modified",
            sort_order=1,
            required=True,
            actor=self.operator_user,
        )
        add_milestone_definition(
            v2,
            code="CLOSED",
            name_fa="بسته شد ویرایش دو",
            name_en="Closed V2 Modified",
            sort_order=2,
            required=True,
            blocking=True,
            terminal=True,
            actor=self.operator_user,
        )
        publish_version(v2, actor=self.operator_user, set_active=True)


        # Project timeline of old execution
        events = project_execution_timeline(self.execution, actor=self.operator_user)
        awarded_event = next(ev for ev in events if ev.get("milestone_code") == "AWARDED")

        # It must still render v1 labels!
        self.assertEqual(awarded_event["milestone_name_en"], "Awarded")
        self.assertEqual(awarded_event["milestone_name_fa"], "واگذاری معامله")
        self.assertNotEqual(awarded_event["milestone_name_en"], "Awarded V2 Modified")

    def test_timeline_api_endpoint(self):
        """GET /api/execution/{execution_id}/timeline/ returns deterministic timeline."""
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/execution/{self.execution.id}/timeline/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)
