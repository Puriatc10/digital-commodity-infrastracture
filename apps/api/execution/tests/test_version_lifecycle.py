from django.core.exceptions import ValidationError

from execution.enums import WorkflowVersionStatus
from execution.exceptions import (
    ExecutionValidationError,
    WorkflowLifecycleError,
)
from execution.models import ExecutionWorkflowTemplateVersion
from execution.services import (
    add_milestone_definition,
    create_draft_version,
    publish_version,
    retire_version,
    update_milestone_definition,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowVersionLifecycleTests(BaseExecutionTestCase):
    """Test lifecycle state machine of workflow template versions: DRAFT -> PUBLISHED -> RETIRED."""

    def test_draft_mutability(self):
        """In DRAFT status, milestones can be freely added, updated, and reordered."""
        template = self.create_sample_template()
        version = create_draft_version(template, actor=self.operator_user)

        m1 = add_milestone_definition(
            version,
            code="STEP_A",
            name_fa="الف",
            name_en="Alpha",
            sort_order=1,
            actor=self.operator_user,
        )
        self.assertEqual(m1.name_en, "Alpha")

        # Update in draft
        update_milestone_definition(
            m1,
            name_en="Alpha Updated",
            sort_order=5,
            actor=self.operator_user,
        )
        m1.refresh_from_db()
        self.assertEqual(m1.name_en, "Alpha Updated")
        self.assertEqual(m1.sort_order, 5)

    def test_valid_lifecycle_transitions(self):
        """DRAFT -> PUBLISHED -> RETIRED is the canonical valid lifecycle progression."""
        template = self.create_sample_template()
        version, _ = self.create_sample_linear_draft(template)

        self.assertEqual(version.status, WorkflowVersionStatus.DRAFT)

        # 1. Publish (set_active=False so we can retire directly without clearing active)
        publish_version(version, actor=self.operator_user, set_active=False)
        version.refresh_from_db()
        self.assertEqual(version.status, WorkflowVersionStatus.PUBLISHED)
        self.assertIsNotNone(version.published_at)
        self.assertEqual(version.published_by, self.operator_user)

        # 2. Retire
        retire_version(version, actor=self.operator_user)
        version.refresh_from_db()
        self.assertEqual(version.status, WorkflowVersionStatus.RETIRED)
        self.assertIsNotNone(version.retired_at)
        self.assertEqual(version.retired_by, self.operator_user)

    def test_draft_cannot_transition_directly_to_retired(self):
        """DRAFT versions cannot jump directly to RETIRED."""
        version, _ = self.create_sample_linear_draft()

        with self.assertRaises(WorkflowLifecycleError):
            retire_version(version, actor=self.operator_user)

        # Also at model level clean()
        version.status = WorkflowVersionStatus.RETIRED
        with self.assertRaises(ValidationError):
            version.clean()

    def test_published_cannot_revert_to_draft(self):
        """PUBLISHED versions cannot revert back to DRAFT."""
        version, _ = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        version.status = WorkflowVersionStatus.DRAFT
        with self.assertRaises(ValidationError):
            version.clean()

    def test_retired_cannot_transition_to_any_status(self):
        """RETIRED is final; cannot transition to PUBLISHED or DRAFT."""
        version, _ = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)
        retire_version(version, actor=self.operator_user)

        version.status = WorkflowVersionStatus.PUBLISHED
        with self.assertRaises(ValidationError):
            version.clean()

        version.status = WorkflowVersionStatus.DRAFT
        with self.assertRaises(ValidationError):
            version.clean()

    def test_cannot_create_version_directly_in_retired_status(self):
        """New versions cannot be instantiated in RETIRED status."""
        template = self.create_sample_template()
        v = ExecutionWorkflowTemplateVersion(
            template=template,
            version_number=1,
            status=WorkflowVersionStatus.RETIRED,
        )
        with self.assertRaises(ValidationError):
            v.clean()

    def test_cannot_publish_empty_version(self):
        """Publishing requires at least one milestone."""
        template = self.create_sample_template()
        empty_version = create_draft_version(template, actor=self.operator_user)

        with self.assertRaises(ExecutionValidationError) as ctx:
            publish_version(empty_version, actor=self.operator_user)
        self.assertIn("at least one milestone", str(ctx.exception))
