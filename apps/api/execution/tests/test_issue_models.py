from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from execution.enums import IssueSeverity, IssueStatus, IssueType
from execution.models.issue import ExecutionIssue
from execution.services import create_or_get_execution_for_deal, publish_version
from execution.tests.base import BaseExecutionTestCase


class ExecutionIssueModelTests(BaseExecutionTestCase):
    """Unit tests for ExecutionIssue model, fields, constraints, and invariants (Epic 10 Contract §65–§74, T1008)."""

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template(code="issue_model_test")
        self.version, _ = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)

        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            workflow_template_version_id=self.version.id,
            actor=self.operator_user,
        )

    def test_exact_issue_types_supported(self):
        """Verify that exactly the 7 authoritative issue types are accepted."""
        expected_types = [
            IssueType.QUALITY,
            IssueType.QUANTITY,
            IssueType.LOGISTICS,
            IssueType.PAYMENT,
            IssueType.DOCUMENT,
            IssueType.CONTRACT,
            IssueType.OTHER,
        ]
        self.assertEqual(len(IssueType.choices), 7)

        for itype in expected_types:
            issue = ExecutionIssue.objects.create(
                execution=self.execution,
                type=itype,
                status=IssueStatus.OPEN,
                title=f"Test issue for {itype}",
                opened_by=self.buyer_owner,
                opened_at=timezone.now(),
            )
            self.assertEqual(issue.type, itype)
            self.assertEqual(issue.status, IssueStatus.OPEN)

    def test_invalid_issue_type_rejected(self):
        """Invalid issue type outside canonical enum is rejected by clean and DB constraint."""
        issue = ExecutionIssue(
            execution=self.execution,
            type="INVALID_TYPE",
            status=IssueStatus.OPEN,
            title="Invalid",
            opened_by=self.buyer_owner,
            opened_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            issue.save()

        # Database CheckConstraint independently rejects when bypassing full_clean
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                super(ExecutionIssue, issue).save()

    def test_exact_issue_statuses_supported(self):
        """Verify that exactly the 4 authoritative issue statuses are accepted."""
        expected_statuses = [
            IssueStatus.OPEN,
            IssueStatus.IN_PROGRESS,
            IssueStatus.RESOLVED,
            IssueStatus.CANCELLED,
        ]
        self.assertEqual(len(IssueStatus.choices), 4)

        for istatus in expected_statuses:
            res_at = timezone.now() if istatus == IssueStatus.RESOLVED else None
            res_by = self.buyer_owner if istatus == IssueStatus.RESOLVED else None
            res_notes = "Resolved satisfactorily" if istatus == IssueStatus.RESOLVED else ""

            issue = ExecutionIssue.objects.create(
                execution=self.execution,
                type=IssueType.LOGISTICS,
                status=istatus,
                title=f"Test issue {istatus}",
                opened_by=self.buyer_owner,
                opened_at=timezone.now(),
                resolved_by=res_by,
                resolved_at=res_at,
                resolution_notes=res_notes,
            )
            self.assertEqual(issue.status, istatus)

    def test_exact_severities_supported_and_optional(self):
        """Verify optional exact severity levels (LOW, MEDIUM, HIGH, CRITICAL, None)."""
        expected_severities = [
            IssueSeverity.LOW,
            IssueSeverity.MEDIUM,
            IssueSeverity.HIGH,
            IssueSeverity.CRITICAL,
            None,
        ]
        for sev in expected_severities:
            issue = ExecutionIssue.objects.create(
                execution=self.execution,
                type=IssueType.QUALITY,
                status=IssueStatus.OPEN,
                severity=sev,
                title=f"Severity test {sev}",
                opened_by=self.buyer_owner,
                opened_at=timezone.now(),
            )
            self.assertEqual(issue.severity, sev)

    def test_blocking_not_inferred_from_severity_or_type(self):
        """
        Invariants (Epic 10 Contract §68, §70):
        Severity CRITICAL with blocks_execution=False does NOT block.
        Type QUALITY with blocks_execution=False does NOT block.
        Blocking comes ONLY from persisted blocks_execution=True.
        """
        issue_critical = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.QUALITY,
            status=IssueStatus.OPEN,
            severity=IssueSeverity.CRITICAL,
            blocks_execution=False,
            title="Critical non-blocking issue",
            opened_by=self.buyer_owner,
            opened_at=timezone.now(),
        )
        self.assertFalse(issue_critical.blocks_execution)
        self.assertFalse(issue_critical.is_active_blocker)

        issue_low_blocking = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.OTHER,
            status=IssueStatus.OPEN,
            severity=IssueSeverity.LOW,
            blocks_execution=True,
            title="Low blocking issue",
            opened_by=self.buyer_owner,
            opened_at=timezone.now(),
        )
        self.assertTrue(issue_low_blocking.blocks_execution)
        self.assertTrue(issue_low_blocking.is_active_blocker)

    def test_active_blocker_semantics(self):
        """
        Active blocker is true if and only if blocks_execution=True AND status in {OPEN, IN_PROGRESS}.
        RESOLVED and CANCELLED issues never actively block.
        """
        now = timezone.now()

        # OPEN + blocking=True -> Active
        i_open = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.PAYMENT,
            status=IssueStatus.OPEN,
            blocks_execution=True,
            title="Open blocker",
            opened_by=self.buyer_owner,
            opened_at=now,
        )
        self.assertTrue(i_open.is_active_blocker)

        # IN_PROGRESS + blocking=True -> Active
        i_progress = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.PAYMENT,
            status=IssueStatus.IN_PROGRESS,
            blocks_execution=True,
            title="In progress blocker",
            opened_by=self.buyer_owner,
            opened_at=now,
        )
        self.assertTrue(i_progress.is_active_blocker)

        # RESOLVED + blocking=True -> INACTIVE
        i_resolved = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.PAYMENT,
            status=IssueStatus.RESOLVED,
            blocks_execution=True,
            title="Resolved blocker",
            opened_by=self.buyer_owner,
            opened_at=now,
            resolved_by=self.buyer_owner,
            resolved_at=now,
            resolution_notes="Fixed",
        )
        self.assertFalse(i_resolved.is_active_blocker)

        # CANCELLED + blocking=True -> INACTIVE
        i_cancelled = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.PAYMENT,
            status=IssueStatus.CANCELLED,
            blocks_execution=True,
            title="Cancelled blocker",
            opened_by=self.buyer_owner,
            opened_at=now,
        )
        self.assertFalse(i_cancelled.is_active_blocker)

    def test_resolution_metadata_constraints(self):
        """
        PostgreSQL check constraints & clean() enforce:
        - RESOLVED requires resolved_at
        - OPEN and IN_PROGRESS require resolved_at and resolved_by to be null
        """
        now = timezone.now()

        # RESOLVED without resolved_at is rejected
        issue_no_time = ExecutionIssue(
            execution=self.execution,
            type=IssueType.CONTRACT,
            status=IssueStatus.RESOLVED,
            title="Invalid resolved",
            opened_by=self.buyer_owner,
            opened_at=now,
            resolved_at=None,
        )
        with self.assertRaises(ValidationError):
            issue_no_time.save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                super(ExecutionIssue, issue_no_time).save()

        # OPEN with resolution metadata is rejected
        issue_open_with_res = ExecutionIssue(
            execution=self.execution,
            type=IssueType.CONTRACT,
            status=IssueStatus.OPEN,
            title="Invalid open",
            opened_by=self.buyer_owner,
            opened_at=now,
            resolved_at=now,
            resolved_by=self.buyer_owner,
        )
        with self.assertRaises(ValidationError):
            issue_open_with_res.save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                super(ExecutionIssue, issue_open_with_res).save()

    def test_deletion_protection(self):
        """ExecutionIssue instances cannot be deleted (represent historical operational records)."""
        issue = ExecutionIssue.objects.create(
            execution=self.execution,
            type=IssueType.QUALITY,
            status=IssueStatus.OPEN,
            title="Permanent issue",
            opened_by=self.buyer_owner,
            opened_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            issue.delete()
