from unittest.mock import patch
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile

from execution.enums import (
    ExecutionDocumentCategory,
    IssueSeverity,
    IssueStatus,
    IssueType,
    TimelineEventType,
)
from execution.services import (
    cancel_issue,
    create_or_get_execution_for_deal,
    open_issue,
    project_execution_timeline,
    publish_version,
    resolve_issue,
    start_issue,
    upload_execution_document,
)
from execution.tests.base import BaseExecutionTestCase


class IssueTimelineTests(BaseExecutionTestCase):
    """
    Tests for deterministic timeline projection of Issue Management domain events
    (Epic 10 Contract §32, §65–§74, T1008).
    """

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code=f"time_issue_{uuid.uuid4().hex[:6]}")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

    def test_issue_opened_timeline_event(self):
        """Opening an issue projects deterministic ISSUE_OPENED event (priority 36)."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Penetration grade test deviation",
            description="Lab report shows 80/100 instead of agreed 60/70.",
            severity=IssueSeverity.CRITICAL,
            blocks_execution=True,
            actor=self.buyer_owner,
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.ISSUE_OPENED, event_types)

        event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.ISSUE_OPENED)
        self.assertEqual(event["event_id"], f"issue-{issue.id}-opened")
        self.assertEqual(event["type_priority"], 36)
        self.assertEqual(event["event_at"], issue.opened_at)
        self.assertEqual(event["actor_id"], str(self.buyer_owner.id))
        self.assertEqual(event["metadata"]["issue_id"], str(issue.id))
        self.assertEqual(event["metadata"]["type"], IssueType.QUALITY)
        self.assertEqual(event["metadata"]["status"], IssueStatus.OPEN)
        self.assertEqual(event["metadata"]["severity"], IssueSeverity.CRITICAL)
        self.assertEqual(event["metadata"]["blocks_execution"], True)
        self.assertEqual(event["metadata"]["description"], issue.description)

    def test_issue_started_timeline_event(self):
        """Transitioning issue to IN_PROGRESS projects ISSUE_STARTED event (priority 37)."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.LOGISTICS,
            title="Truck delayed at border",
            actor=self.supplier_user,
        )
        start_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            actor=self.operator_user,
        )

        timeline = project_execution_timeline(self.execution, actor=self.operator_user)
        event_types = [ev["event_type"] for ev in timeline]
        self.assertIn(TimelineEventType.ISSUE_OPENED, event_types)
        self.assertIn(TimelineEventType.ISSUE_STARTED, event_types)

        start_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.ISSUE_STARTED)
        self.assertEqual(start_event["event_id"], f"issue-{issue.id}-started")
        self.assertEqual(start_event["type_priority"], 37)
        self.assertEqual(start_event["metadata"]["status"], IssueStatus.IN_PROGRESS)

    def test_issue_resolved_timeline_event(self):
        """Resolving issue projects ISSUE_RESOLVED event (priority 38) with actor and notes."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.PAYMENT,
            title="Currency discrepancy on invoice",
            actor=self.buyer_owner,
        )
        resolve_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            resolution_notes="Commercial credit note issued and verified.",
            actor=self.operator_user,
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        res_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.ISSUE_RESOLVED)
        self.assertEqual(res_event["event_id"], f"issue-{issue.id}-resolved")
        self.assertEqual(res_event["type_priority"], 38)
        self.assertEqual(res_event["actor_id"], str(self.operator_user.id))
        self.assertEqual(res_event["notes"], "Commercial credit note issued and verified.")
        self.assertEqual(res_event["metadata"]["resolution_notes"], "Commercial credit note issued and verified.")
        self.assertEqual(res_event["metadata"]["status"], IssueStatus.RESOLVED)

    def test_issue_cancelled_timeline_event(self):
        """Cancelling issue projects ISSUE_CANCELLED event (priority 39)."""
        issue = open_issue(
            self.execution.id,
            type=IssueType.OTHER,
            title="Mistaken issue filing",
            actor=self.supplier_user,
        )
        cancel_issue(
            self.execution.id,
            issue.id,
            expected_version=1,
            actor=self.supplier_user,
        )

        timeline = project_execution_timeline(self.execution, actor=self.supplier_user)
        cancel_event = next(ev for ev in timeline if ev["event_type"] == TimelineEventType.ISSUE_CANCELLED)
        self.assertEqual(cancel_event["event_id"], f"issue-{issue.id}-cancelled")
        self.assertEqual(cancel_event["type_priority"], 39)
        self.assertEqual(cancel_event["metadata"]["status"], IssueStatus.CANCELLED)

    @patch("execution.services.document_service.upload_document")
    def test_document_linked_to_issue_projects_issue_id_in_timeline_metadata(self, mock_upload):
        """Document uploaded against an issue includes issue_id in DOCUMENT_UPLOADED event metadata."""
        mock_upload.return_value = "s3://bucket/test_doc.pdf"
        dummy_file = SimpleUploadedFile("evidence.pdf", b"%PDF-1.4 content", content_type="application/pdf")

        issue = open_issue(
            self.execution.id,
            type=IssueType.QUALITY,
            title="Lab discrepancy",
            actor=self.buyer_owner,
        )

        doc = upload_execution_document(
            self.execution.id,
            file_obj=dummy_file,
            category=ExecutionDocumentCategory.OTHER,
            actor=self.buyer_owner,
            issue_id=issue.id,
        )

        timeline = project_execution_timeline(self.execution, actor=self.buyer_owner)
        doc_events = [ev for ev in timeline if ev["event_type"] == TimelineEventType.DOCUMENT_UPLOADED]
        self.assertTrue(len(doc_events) >= 1)

        issue_doc_event = next(ev for ev in doc_events if ev["event_id"] == f"document-{doc.id}-uploaded")
        self.assertEqual(issue_doc_event["metadata"]["issue_id"], str(issue.id))

    def test_deterministic_timeline_sorting(self):
        """
        Timeline events sort deterministically by (event_at, type_priority, event_id).
        """
        timeline = project_execution_timeline(self.execution, actor=self.operator_user)
        for i in range(len(timeline) - 1):
            curr_ev = timeline[i]
            next_ev = timeline[i + 1]
            curr_tuple = (curr_ev["event_at"], curr_ev["type_priority"], str(curr_ev["event_id"]))
            next_tuple = (next_ev["event_at"], next_ev["type_priority"], str(next_ev["event_id"]))
            self.assertLessEqual(
                curr_tuple,
                next_tuple,
                f"Timeline sort order violated between {curr_ev} and {next_ev}",
            )
