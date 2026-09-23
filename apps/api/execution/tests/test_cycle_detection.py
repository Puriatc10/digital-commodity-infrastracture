from execution.exceptions import (
    ExecutionValidationError,
    WorkflowDependencyCycleError,
)
from execution.services import (
    add_milestone_definition,
    create_draft_version,
    publish_version,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowCycleDetectionAndTerminalTests(BaseExecutionTestCase):
    """Test cycle detection in prerequisite graphs and generic terminal milestone invariants."""

    def test_valid_linear_dag(self):
        """Linear DAG passes validation and publishes successfully."""
        version, _ = self.create_sample_linear_draft()
        published = publish_version(version, actor=self.operator_user)
        self.assertEqual(published.status, "PUBLISHED")

    def test_valid_diamond_dag(self):
        """Diamond DAG (A -> B, A -> C, B -> D, C -> D[terminal]) publishes successfully."""
        template = self.create_sample_template()
        version = create_draft_version(template, actor=self.operator_user)

        add_milestone_definition(
            version,
            code="A",
            name_fa="آ",
            name_en="A",
            sort_order=1,
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="B",
            name_fa="ب",
            name_en="B",
            sort_order=2,
            prerequisite_codes=["A"],
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="C",
            name_fa="پ",
            name_en="C",
            sort_order=3,
            prerequisite_codes=["A"],
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="D",
            name_fa="ت",
            name_en="D",
            sort_order=4,
            required=True,
            blocking=True,
            terminal=True,
            prerequisite_codes=["B", "C"],
            actor=self.operator_user,
        )

        published = publish_version(version, actor=self.operator_user)
        self.assertEqual(published.status, "PUBLISHED")

    def test_direct_dependency_cycle_rejected(self):
        """Direct cycle (A requires B, B requires A) is rejected upon publish."""
        template = self.create_sample_template()
        version = create_draft_version(template, actor=self.operator_user)

        add_milestone_definition(
            version,
            code="A",
            name_fa="آ",
            name_en="A",
            sort_order=1,
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="B",
            name_fa="ب",
            name_en="B",
            sort_order=2,
            prerequisite_codes=["A"],
            actor=self.operator_user,
        )
        # Make A depend on B as well
        m_a = version.milestones.get(code="A")
        m_b = version.milestones.get(code="B")
        from execution.models import ExecutionMilestoneDependency
        ExecutionMilestoneDependency.objects.create(milestone=m_a, prerequisite=m_b)

        # Also add a terminal milestone so terminal check isn't the failure cause
        add_milestone_definition(
            version,
            code="TERM",
            name_fa="پایان",
            name_en="Terminal",
            sort_order=3,
            required=True,
            blocking=True,
            terminal=True,
            actor=self.operator_user,
        )

        with self.assertRaises(WorkflowDependencyCycleError) as ctx:
            publish_version(version, actor=self.operator_user)
        self.assertIn("Dependency cycle detected", str(ctx.exception))

    def test_indirect_dependency_cycle_rejected(self):
        """Indirect cycle (A -> B -> C -> A) is rejected upon publish."""
        template = self.create_sample_template()
        version = create_draft_version(template, actor=self.operator_user)

        add_milestone_definition(
            version,
            code="X",
            name_fa="ایکس",
            name_en="X",
            sort_order=1,
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="Y",
            name_fa="وای",
            name_en="Y",
            sort_order=2,
            prerequisite_codes=["X"],
            actor=self.operator_user,
        )
        add_milestone_definition(
            version,
            code="Z",
            name_fa="زد",
            name_en="Z",
            sort_order=3,
            prerequisite_codes=["Y"],
            actor=self.operator_user,
        )
        # Create cycle Z -> X (X depends on Z)
        m_x = version.milestones.get(code="X")
        m_z = version.milestones.get(code="Z")
        from execution.models import ExecutionMilestoneDependency
        ExecutionMilestoneDependency.objects.create(milestone=m_x, prerequisite=m_z)

        # Terminal milestone
        add_milestone_definition(
            version,
            code="END",
            name_fa="پایان",
            name_en="End",
            sort_order=4,
            required=True,
            blocking=True,
            terminal=True,
            actor=self.operator_user,
        )

        with self.assertRaises(WorkflowDependencyCycleError) as ctx:
            publish_version(version, actor=self.operator_user)
        self.assertIn("Dependency cycle detected", str(ctx.exception))

    def test_terminal_milestone_invariants(self):
        """Generic terminal milestone invariants: exactly 1, required, blocking, no dependents."""
        template = self.create_sample_template()

        # Case 1: Zero terminal milestones
        v1 = create_draft_version(template, actor=self.operator_user)
        add_milestone_definition(
            v1, code="STEP", name_fa="قدم", name_en="Step", sort_order=1, terminal=False, actor=self.operator_user
        )
        with self.assertRaises(ExecutionValidationError) as ctx:
            publish_version(v1, actor=self.operator_user)
        self.assertIn("exactly one terminal milestone", str(ctx.exception))

        # Case 2: Multiple terminal milestones
        v2 = create_draft_version(template, actor=self.operator_user)
        add_milestone_definition(
            v2, code="T1", name_fa="پایان ۱", name_en="Term 1", sort_order=1, terminal=True, actor=self.operator_user
        )
        add_milestone_definition(
            v2, code="T2", name_fa="پایان ۲", name_en="Term 2", sort_order=2, terminal=True, actor=self.operator_user
        )
        with self.assertRaises(ExecutionValidationError) as ctx:
            publish_version(v2, actor=self.operator_user)
        self.assertIn("cannot have multiple terminal milestones", str(ctx.exception))

        # Case 3: Terminal milestone has downstream dependents
        v3 = create_draft_version(template, actor=self.operator_user)
        add_milestone_definition(
            v3,
            code="EARLY_TERM",
            name_fa="پایان زودرس",
            name_en="Early Term",
            sort_order=1,
            required=True,
            blocking=True,
            terminal=True,
            actor=self.operator_user,
        )
        add_milestone_definition(
            v3, code="AFTER_TERM", name_fa="بعد پایان", name_en="After Term", sort_order=2, terminal=False, prerequisite_codes=["EARLY_TERM"], actor=self.operator_user
        )
        with self.assertRaises(ExecutionValidationError) as ctx:
            publish_version(v3, actor=self.operator_user)
        self.assertIn("cannot be a prerequisite for any other milestone", str(ctx.exception))
