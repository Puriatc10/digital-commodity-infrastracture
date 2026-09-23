import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError

from execution.models import (
    ExecutionMilestoneDefinition,
    ExecutionMilestoneDependency,
    ExecutionWorkflowTemplate,
    ExecutionWorkflowTemplateVersion,
)
from execution.services import (
    add_milestone_definition,
    create_draft_version,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowTemplateModelTests(BaseExecutionTestCase):
    """Test data model invariants and relational constraints for workflow templates."""

    def test_unique_template_code(self):
        """Template code must be unique in PostgreSQL database."""
        code = f"tmpl_{uuid.uuid4().hex[:6]}"
        self.create_sample_template(code=code)

        # Attempt duplicate code via model
        with self.assertRaises(ValidationError):
            t_dup = ExecutionWorkflowTemplate(
                code=code,
                name_fa="تکراری",
                name_en="Duplicate",
            )
            t_dup.full_clean()

    def test_template_code_immutability(self):
        """Template code is a stable machine identifier and cannot be modified."""
        template = self.create_sample_template()
        template.code = "new_mutated_code"
        with self.assertRaises(ValidationError):
            template.clean()

    def test_unique_template_version_number(self):
        """Two versions cannot share the same version_number on the same template."""
        template = self.create_sample_template()
        v1 = create_draft_version(template, actor=self.operator_user)
        self.assertEqual(v1.version_number, 1)

        # Attempt to insert another version with version_number 1 directly
        with self.assertRaises(IntegrityError):
            ExecutionWorkflowTemplateVersion.objects.create(
                template=template,
                version_number=1,
            )

    def test_server_version_allocation(self):
        """Versions are allocated monotonically 1, 2, 3... per template."""
        template = self.create_sample_template()
        v1 = create_draft_version(template, actor=self.operator_user)
        v2 = create_draft_version(template, actor=self.operator_user)
        v3 = create_draft_version(template, actor=self.operator_user)

        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(v3.version_number, 3)

    def test_unique_milestone_code_in_version(self):
        """Milestone codes must be unique within a single template version."""
        version, _ = self.create_sample_linear_draft()

        with self.assertRaises(IntegrityError):
            ExecutionMilestoneDefinition.objects.create(
                workflow_template_version=version,
                code="STEP_ONE",  # Already exists
                name_fa="تکراری",
                name_en="Duplicate",
                sort_order=99,
            )

    def test_unique_milestone_sort_order_in_version(self):
        """Milestone sort_order must be unique within a single template version."""
        version, _ = self.create_sample_linear_draft()

        with self.assertRaises(IntegrityError):
            ExecutionMilestoneDefinition.objects.create(
                workflow_template_version=version,
                code="UNIQUE_CODE",
                name_fa="یکتا",
                name_en="Unique",
                sort_order=1,  # sort_order 1 already used by STEP_ONE
            )

    def test_self_dependency_rejection(self):
        """A milestone cannot depend on itself (rejected at both clean and DB CheckConstraint)."""
        version, (m1, _, _) = self.create_sample_linear_draft()

        dep = ExecutionMilestoneDependency(
            milestone=m1,
            prerequisite=m1,
        )
        with self.assertRaises(ValidationError):
            dep.clean()

        with self.assertRaises(IntegrityError):
            ExecutionMilestoneDependency.objects.bulk_create([
                ExecutionMilestoneDependency(
                    milestone=m1,
                    prerequisite=m1,
                )
            ])

    def test_cross_version_dependency_rejection(self):
        """Dependencies cannot cross different workflow versions."""
        v1, (v1_m1, _, _) = self.create_sample_linear_draft()
        v2, (v2_m1, _, _) = self.create_sample_linear_draft()

        dep = ExecutionMilestoneDependency(
            milestone=v2_m1,
            prerequisite=v1_m1,  # From v1!
        )
        with self.assertRaises(ValidationError):
            dep.clean()

    def test_multi_workflow_generic_behavior(self):
        """Multiple distinct workflow templates coexist without cross-interference or commodity coupling."""
        t1 = self.create_sample_template(code="workflow_alpha")
        t2 = self.create_sample_template(code="workflow_beta")

        v1_a = create_draft_version(t1, actor=self.operator_user)
        v1_b = create_draft_version(t2, actor=self.operator_user)

        # Both can have milestone with same code because versions differ
        m_a = add_milestone_definition(
            v1_a,
            code="INITIAL",
            name_fa="شروع",
            name_en="Initial",
            sort_order=1,
            terminal=True,
            actor=self.operator_user,
        )
        m_b = add_milestone_definition(
            v1_b,
            code="INITIAL",
            name_fa="شروع",
            name_en="Initial",
            sort_order=1,
            terminal=True,
            actor=self.operator_user,
        )

        self.assertEqual(m_a.code, m_b.code)
        self.assertNotEqual(m_a.workflow_template_version_id, m_b.workflow_template_version_id)
        self.assertEqual(v1_a.version_number, 1)
        self.assertEqual(v1_b.version_number, 1)
