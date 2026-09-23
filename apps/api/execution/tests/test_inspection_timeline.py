from django.utils import timezone

from commodities.models import (
    CommodityAttributeDefinition,
    CommoditySchemaVersion,
)
from execution.enums import InspectionResult, TimelineEventType
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    cancel_inspection,
    complete_inspection,
    create_or_get_execution_for_deal,
    project_execution_timeline,
    render_execution_deal_specifications,
    schedule_inspection,
)
from execution.tests.base import BaseExecutionTestCase


class InspectionTimelineAndSchemaTests(BaseExecutionTestCase):
    """
    Tests for deterministic timeline projection and version-bound historical schema rendering (T1005).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )

    def test_inspection_scheduled_timeline_event(self):
        """Scheduling an inspection projects deterministic INSPECTION_SCHEDULED event."""
        now = timezone.now()
        schedule_time = now + timezone.timedelta(days=2)
        schedule_inspection(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            scheduled_at=schedule_time,
            agency="SGS Testing",
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.INSPECTION_SCHEDULED, event_types)

        sched_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.INSPECTION_SCHEDULED)
        self.assertEqual(sched_event["metadata"]["agency"], "SGS Testing")
        self.assertEqual(sched_event["type_priority"], 25)
        self.assertEqual(sched_event["event_at"], schedule_time)

    def test_inspection_completed_timeline_event(self):
        """Completing an inspection projects deterministic INSPECTION_COMPLETED event."""
        now = timezone.now()
        schedule_time = now + timezone.timedelta(days=1)
        complete_time = now + timezone.timedelta(days=2)

        schedule_inspection(self.execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=schedule_time, agency="SGS")
        complete_inspection(
            self.execution.id,
            expected_version=2,
            actor=self.supplier_user,
            inspection_at=complete_time,
            result=InspectionResult.FAIL,
            agency="SGS",
            notes="Penetration grade slightly off-spec.",
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)

        completed_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.INSPECTION_COMPLETED)
        self.assertEqual(completed_event["type_priority"], 32)
        self.assertEqual(completed_event["event_at"], complete_time)
        self.assertEqual(completed_event["metadata"]["result"], InspectionResult.FAIL)
        self.assertEqual(completed_event["metadata"]["agency"], "SGS")

    def test_inspection_cancelled_timeline_event(self):
        """Cancelling an inspection projects deterministic INSPECTION_CANCELLED event."""
        schedule_inspection(self.execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=timezone.now(), agency="SGS")
        cancel_inspection(self.execution.id, expected_version=2, actor=self.supplier_user, notes="Cancelled due to logistical shift.")

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.INSPECTION_CANCELLED, event_types)

        cancel_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.INSPECTION_CANCELLED)
        self.assertEqual(cancel_event["type_priority"], 33)

    def test_deterministic_timeline_ordering_with_timestamp_tie(self):
        """Timestamp ties between events are deterministically broken by stable type priority then ID."""
        fixed_time = timezone.now()
        schedule_inspection(self.execution.id, expected_version=1, actor=self.supplier_user, scheduled_at=fixed_time, agency="SGS")

        timeline = project_execution_timeline(self.execution, actor=self.operator_user)

        # Assert timeline is strictly sorted: (event_at, type_priority, event_id)
        for i in range(len(timeline) - 1):
            e1 = timeline[i]
            e2 = timeline[i + 1]
            k1 = (e1["event_at"], e1["type_priority"], str(e1["event_id"]))
            k2 = (e2["event_at"], e2["type_priority"], str(e2["event_id"]))
            self.assertLessEqual(k1, k2)

    def test_historical_schema_rendering_unaffected_by_active_schema_update(self):
        """
        Historical Schema Invariant:
        Rendered quality specifications use DealTermsSnapshot.schema_version.
        Subsequent publication/activation of new schema versions never reinterprets or alters
        the Execution Deal specifications.
        """
        # 1. Render initial specifications
        specs_v1 = render_execution_deal_specifications(self.execution, actor=self.buyer_owner)
        self.assertTrue(len(specs_v1) > 0)
        initial_keys = {item["key"] for item in specs_v1}
        self.assertIn("penetration_grade", initial_keys)

        # 2. Create and activate a NEW schema version for this commodity
        v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )

        CommodityAttributeDefinition.objects.create(
            schema_version=v2,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=20,
        )
        v2.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        v2.save()
        self.commodity.active_schema_version = v2
        self.commodity.save()

        # 3. Render execution deal specifications again
        specs_after_v2 = render_execution_deal_specifications(self.execution, actor=self.buyer_owner)

        # Must still match v1 schema projection exactly; v2 attribute 'softening_point' is NOT present
        self.assertEqual(specs_v1, specs_after_v2)
        after_keys = {item["key"] for item in specs_after_v2}
        self.assertNotIn("softening_point", after_keys)
