from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from execution.enums import ExecutionStatus, MilestoneStatus
from execution.models.execution import Execution
from execution.models.milestone import ExecutionMilestone
from execution.services import (
    create_draft_version,
    publish_version,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionModelTests(BaseExecutionTestCase):
    """Tests for Execution and ExecutionMilestone models and constraints (Epic 10 Contract §5, §6, §8, §15, §16, §17)."""

    def setUp(self):
        super().setUp()
        self.template = self.create_sample_template()
        self.version, (self.m1, self.m2, self.m3) = self.create_sample_linear_draft(self.template)
        publish_version(self.version, actor=self.operator_user, set_active=True)
        self.deal = self.create_sample_deal()


    def test_one_deal_exactly_one_execution_cardinality(self):
        """1 Deal -> exactly 1 Execution. Second Execution for same deal violates DB uniqueness."""
        exec1 = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        self.assertIsNotNone(exec1.id)

        # Attempting second Execution for same deal
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                Execution.objects.create(
                    deal=self.deal,
                    workflow_template_version=self.version,
                    status=ExecutionStatus.OPEN,
                )

    def test_execution_status_strictly_open_or_closed(self):
        """Execution status only permits OPEN and CLOSED. Arbitrary status rejected."""
        execution = Execution(
            deal=self.deal,
            workflow_template_version=self.version,
            status="INVALID_STATUS",
        )
        with self.assertRaises(ValidationError):
            execution.full_clean()

    def test_bound_workflow_template_version_is_immutable(self):
        """Execution cannot be rebound to a different workflow version after creation."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )

        v2 = create_draft_version(self.template, actor=self.operator_user)
        # Attempt to change workflow_template_version
        execution.workflow_template_version = v2
        with self.assertRaises(ValidationError) as ctx:
            execution.save()
        self.assertIn("workflow_template_version", ctx.exception.message_dict)

    def test_execution_deal_is_immutable(self):
        """Execution deal cannot be altered after creation."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        other_deal = self.create_sample_deal()
        execution.deal = other_deal
        with self.assertRaises(ValidationError) as ctx:
            execution.save()
        self.assertIn("deal", ctx.exception.message_dict)

    def test_cannot_bind_draft_or_retired_version_to_new_execution(self):
        """New execution cannot bind to DRAFT or RETIRED workflow version."""
        draft_v = create_draft_version(self.template, actor=self.operator_user)
        execution = Execution(
            deal=self.deal,
            workflow_template_version=draft_v,
            status=ExecutionStatus.OPEN,
        )
        with self.assertRaises(ValidationError) as ctx:
            execution.full_clean()
        self.assertIn("workflow_template_version", ctx.exception.message_dict)

    def test_milestone_definition_must_belong_to_execution_bound_version(self):
        """ExecutionMilestone definition must belong to the same bound version as the Execution."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )

        # Another template version's milestone definition
        other_template = self.create_sample_template(code="other_tmpl")
        other_version, (other_m1, _, _) = self.create_sample_linear_draft(other_template)
        publish_version(other_version, actor=self.operator_user)


        foreign_milestone = ExecutionMilestone(
            execution=execution,
            definition=other_m1,
            status=MilestoneStatus.PENDING,
        )
        with self.assertRaises(ValidationError) as ctx:
            foreign_milestone.full_clean()
        self.assertIn("definition", ctx.exception.message_dict)

    def test_milestone_unique_per_execution_and_definition(self):
        """(execution, definition) must be unique. Duplicate instance fails."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        ExecutionMilestone.objects.create(
            execution=execution,
            definition=self.m1,
            status=MilestoneStatus.PENDING,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExecutionMilestone.objects.create(
                    execution=execution,
                    definition=self.m1,
                    status=MilestoneStatus.PENDING,
                )

    def test_completed_milestone_cannot_be_reopened(self):
        """Once COMPLETED, milestone cannot be moved back to PENDING or other statuses."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        now = timezone.now()
        milestone = ExecutionMilestone.objects.create(
            execution=execution,
            definition=self.m1,
            status=MilestoneStatus.COMPLETED,
            actual_at=now,
            recorded_at=now,
            completed_by=self.operator_user,
        )

        milestone.status = MilestoneStatus.PENDING
        with self.assertRaises(ValidationError) as ctx:
            milestone.save()
        self.assertIn("status", ctx.exception.message_dict)

    def test_completed_milestone_facts_cannot_be_overwritten(self):
        """Once COMPLETED, actual_at, completed_by, and recorded_at are immutable."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        now = timezone.now()
        milestone = ExecutionMilestone.objects.create(
            execution=execution,
            definition=self.m1,
            status=MilestoneStatus.COMPLETED,
            actual_at=now,
            recorded_at=now,
            completed_by=self.operator_user,
        )

        milestone.actual_at = now - timezone.timedelta(days=2)
        with self.assertRaises(ValidationError) as ctx:
            milestone.save()
        self.assertIn("actual_at", ctx.exception.message_dict)

    def test_execution_milestone_deletion_protection_signal(self):
        """ExecutionMilestone records cannot be deleted."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        milestone = ExecutionMilestone.objects.create(
            execution=execution,
            definition=self.m1,
            status=MilestoneStatus.PENDING,
        )
        with self.assertRaises(ValidationError):
            milestone.delete()

    def test_execution_deletion_protection_signal(self):
        """Execution aggregates cannot be deleted."""
        execution = Execution.objects.create(
            deal=self.deal,
            workflow_template_version=self.version,
            status=ExecutionStatus.OPEN,
        )
        with self.assertRaises(ValidationError):
            execution.delete()

