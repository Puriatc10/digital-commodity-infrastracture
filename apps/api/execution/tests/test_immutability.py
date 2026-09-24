from django.core.exceptions import ValidationError

from execution.exceptions import WorkflowImmutableError
from execution.models import (
    ExecutionMilestoneDefinition,
    ExecutionMilestoneDependency,
)
from execution.services import (
    add_milestone_definition,
    add_milestone_dependency,
    delete_milestone_definition,
    publish_version,
    retire_version,
    update_milestone_definition,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowImmutabilityTests(BaseExecutionTestCase):
    """Test strict immutability of PUBLISHED and RETIRED workflow versions and their graphs."""

    def test_cannot_modify_published_version_metadata(self):
        """Published version row cannot have its change_summary or version_number mutated."""
        version, _ = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        version.change_summary = "Mutated summary"
        with self.assertRaises(ValidationError):
            version.clean()

    def test_cannot_add_milestone_to_published_version(self):
        """Adding a milestone to a published version is strictly rejected."""
        version, _ = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        # Service level
        with self.assertRaises(WorkflowImmutableError):
            add_milestone_definition(
                version,
                code="NEW_STEP",
                name_fa="مرحله جدید",
                name_en="New Step",
                sort_order=4,
                actor=self.operator_user,
            )

        # Model level
        with self.assertRaises(ValidationError):
            m = ExecutionMilestoneDefinition(
                workflow_template_version=version,
                code="NEW_STEP",
                name_fa="مرحله جدید",
                name_en="New Step",
                sort_order=4,
            )
            m.full_clean()

    def test_cannot_edit_milestone_in_published_version(self):
        """Editing milestone name, sort_order, or flags in a published version is rejected."""
        version, (m1, _, _) = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        with self.assertRaises(WorkflowImmutableError):
            update_milestone_definition(
                m1,
                name_en="Step One Changed",
                actor=self.operator_user,
            )

        m1.name_en = "Step One Direct Edit"
        with self.assertRaises(ValidationError):
            m1.clean()

    def test_cannot_delete_milestone_from_published_version(self):
        """Deleting a milestone from a published version is rejected."""
        version, (m1, _, _) = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        with self.assertRaises(WorkflowImmutableError):
            delete_milestone_definition(m1, actor=self.operator_user)

        with self.assertRaises(ValidationError):
            m1.delete()

    def test_cannot_add_dependency_in_published_version(self):
        """Cannot add prerequisite relationships in a published version."""
        version, (m1, _, m3) = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)

        with self.assertRaises(WorkflowImmutableError):
            add_milestone_dependency(m3, m1, actor=self.operator_user)

        dep = ExecutionMilestoneDependency(milestone=m3, prerequisite=m1)
        with self.assertRaises(ValidationError):
            dep.clean()

    def test_cannot_delete_dependency_in_published_version(self):
        """Cannot delete prerequisite relationships from a published version."""
        version, (_, m2, _) = self.create_sample_linear_draft()
        dep = m2.prerequisite_dependencies.first()
        self.assertIsNotNone(dep)

        publish_version(version, actor=self.operator_user, set_active=False)

        with self.assertRaises(ValidationError):
            dep.delete()

    def test_retired_version_immutability(self):
        """Retired version and its graph are completely immutable and historical."""
        version, (m1, _, _) = self.create_sample_linear_draft()
        publish_version(version, actor=self.operator_user, set_active=False)
        retire_version(version, actor=self.operator_user)

        with self.assertRaises(WorkflowImmutableError):
            add_milestone_definition(
                version,
                code="POST_RETIRE",
                name_fa="پس از بازنشستگی",
                name_en="Post Retire",
                sort_order=10,
                actor=self.operator_user,
            )

        with self.assertRaises(WorkflowImmutableError):
            update_milestone_definition(m1, name_en="Mutate Retired", actor=self.operator_user)

        with self.assertRaises(WorkflowImmutableError):
            delete_milestone_definition(m1, actor=self.operator_user)

    def test_delete_protection_for_published_and_retired_versions(self):
        """Published and retired versions and their templates cannot be deleted."""
        template = self.create_sample_template()
        v1, _ = self.create_sample_linear_draft(template)
        publish_version(v1, actor=self.operator_user, set_active=False)

        # Cannot delete published version
        with self.assertRaises(ValidationError):
            v1.delete()

        # Cannot delete template
        with self.assertRaises(ValidationError):
            template.delete()

        # Retire version
        retire_version(v1, actor=self.operator_user)

        # Cannot delete retired version
        with self.assertRaises(ValidationError):
            v1.delete()

        # Cannot delete template with retired version
        with self.assertRaises(ValidationError):
            template.delete()
