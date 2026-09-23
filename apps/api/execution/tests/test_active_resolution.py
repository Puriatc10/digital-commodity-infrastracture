from execution.exceptions import (
    ExecutionValidationError,
    NoActiveWorkflowVersionError,
    WorkflowTemplateInactiveError,
)
from execution.services import (
    activate_version,
    get_active_workflow_template_version,
    publish_version,
    retire_version,
    update_workflow_template,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowActiveResolutionTests(BaseExecutionTestCase):
    """Test deterministic active published version resolution and invariants."""

    def test_deterministic_active_resolution(self):
        """Active published version is resolved deterministically by code, ID, or instance."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        # By code
        res_by_code = get_active_workflow_template_version(template.code)
        self.assertEqual(res_by_code.id, v1.id)

        # By UUID
        res_by_id = get_active_workflow_template_version(template.id)
        self.assertEqual(res_by_id.id, v1.id)

        # By instance
        res_by_instance = get_active_workflow_template_version(template)
        self.assertEqual(res_by_instance.id, v1.id)

    def test_active_version_updates_on_new_publish(self):
        """Publishing v2 with set_active=True updates the template's active version."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        v2, _ = self.create_sample_linear_draft(template)
        publish_version(v2, actor=self.operator_user, set_active=True)

        active = get_active_workflow_template_version(template)
        self.assertEqual(active.id, v2.id)
        self.assertEqual(active.version_number, 2)

    def test_inactive_template_raises_error(self):
        """An inactive template raises WorkflowTemplateInactiveError upon active version resolution."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        update_workflow_template(template, is_active=False, actor=self.operator_user)

        with self.assertRaises(WorkflowTemplateInactiveError):
            get_active_workflow_template_version(template.code)

    def test_template_without_active_version_raises_error(self):
        """Template with only draft versions raises NoActiveWorkflowVersionError."""
        template = self.create_sample_template()
        self.create_sample_linear_draft(template)

        with self.assertRaises(NoActiveWorkflowVersionError):
            get_active_workflow_template_version(template.code)

    def test_retired_version_never_resolves_as_active(self):
        """A retired version cannot be activated or resolved as active."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=False)
        retire_version(v1, actor=self.operator_user)

        # Attempt to activate retired version
        with self.assertRaises(ExecutionValidationError) as ctx:
            activate_version(v1, actor=self.operator_user)
        self.assertIn("only PUBLISHED versions can be active", str(ctx.exception))

    def test_cannot_retire_currently_active_version(self):
        """Active published version cannot be retired while still designated as the active version."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=True)

        with self.assertRaises(ExecutionValidationError) as ctx:
            retire_version(v1, actor=self.operator_user)
        self.assertIn("Cannot retire the currently active workflow version", str(ctx.exception))

        # Once v2 is published and activated, v1 can be retired safely
        v2, _ = self.create_sample_linear_draft(template)
        publish_version(v2, actor=self.operator_user, set_active=True)

        retire_version(v1, actor=self.operator_user)
        v1.refresh_from_db()
        self.assertEqual(v1.status, "RETIRED")

    def test_draft_version_cannot_be_activated(self):
        """A DRAFT version cannot be designated as the active version."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)

        with self.assertRaises(ExecutionValidationError):
            activate_version(v1, actor=self.operator_user)
