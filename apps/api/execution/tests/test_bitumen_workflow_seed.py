from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from execution.enums import WorkflowVersionStatus
from execution.exceptions import WorkflowSeedConflictError
from execution.models.dependency import ExecutionMilestoneDependency
from execution.models.milestone_definition import ExecutionMilestoneDefinition
from execution.models.template import ExecutionWorkflowTemplate
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.seed import (
    BITUMEN_V1_MILESTONES,
    BITUMEN_WORKFLOW_TEMPLATE_CODE,
    BITUMEN_WORKFLOW_TEMPLATE_NAME_EN,
    BITUMEN_WORKFLOW_TEMPLATE_NAME_FA,
    seed_bitumen_workflow_v1,
)


class BitumenWorkflowSeedTests(TestCase):
    """
    Comprehensive tests for Bitumen Execution Workflow v1 Seed (Epic 10 Contract §21, T1002).
    """

    EXPECTED_CODES = [
        "AWARDED",
        "CONTRACT_SIGNED",
        "PAYMENT_REPORTED",
        "LOADING_SCHEDULED",
        "LOADED",
        "INSPECTION_COMPLETED",
        "IN_TRANSIT",
        "DELIVERED",
        "ACCEPTED",
        "CLOSED",
    ]

    def test_exact_identity(self):
        """Template code is stable bitumen_standard and names match canonical definition."""
        v1 = seed_bitumen_workflow_v1()
        template = v1.template

        self.assertEqual(template.code, BITUMEN_WORKFLOW_TEMPLATE_CODE)
        self.assertEqual(template.code, "bitumen_standard")
        self.assertEqual(template.name_fa, BITUMEN_WORKFLOW_TEMPLATE_NAME_FA)
        self.assertEqual(template.name_en, BITUMEN_WORKFLOW_TEMPLATE_NAME_EN)
        self.assertTrue(template.is_active)

    def test_exact_milestone_count(self):
        """Version 1 contains exactly 10 milestone definitions."""
        v1 = seed_bitumen_workflow_v1()
        milestones = v1.milestones.all()
        self.assertEqual(milestones.count(), 10)
        self.assertEqual(milestones.count(), len(BITUMEN_V1_MILESTONES))

    def test_exact_codes_and_order(self):
        """Milestones match exact machine codes and 1-based sequential sort order."""
        v1 = seed_bitumen_workflow_v1()
        milestones = list(v1.milestones.order_by("sort_order"))

        codes = [m.code for m in milestones]
        self.assertEqual(codes, self.EXPECTED_CODES)

        sort_orders = [m.sort_order for m in milestones]
        self.assertEqual(sort_orders, list(range(1, 11)))

    def test_localized_labels(self):
        """All 10 milestone definitions have non-empty Persian and English labels."""
        v1 = seed_bitumen_workflow_v1()
        for m in v1.milestones.all():
            self.assertTrue(bool(m.name_fa), f"Missing name_fa for {m.code}")
            self.assertTrue(bool(m.name_en), f"Missing name_en for {m.code}")
            self.assertIsInstance(m.name_fa, str)
            self.assertIsInstance(m.name_en, str)

    def test_published_and_active(self):
        """Canonical v1 is in PUBLISHED status with published_at populated and active on template."""
        v1 = seed_bitumen_workflow_v1()
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v1.status, WorkflowVersionStatus.PUBLISHED)
        self.assertIsNotNone(v1.published_at)

        template = ExecutionWorkflowTemplate.objects.get(code=BITUMEN_WORKFLOW_TEMPLATE_CODE)
        self.assertEqual(template.active_version, v1)
        self.assertTrue(v1.is_active)

    def test_idempotent_rerun(self):
        """Subsequent runs return identical published v1 without duplicate rows or changes."""
        v1_first = seed_bitumen_workflow_v1()

        template_count_before = ExecutionWorkflowTemplate.objects.count()
        version_count_before = ExecutionWorkflowTemplateVersion.objects.count()
        milestone_count_before = ExecutionMilestoneDefinition.objects.count()
        dependency_count_before = ExecutionMilestoneDependency.objects.count()

        v1_second = seed_bitumen_workflow_v1()

        self.assertEqual(v1_first.pk, v1_second.pk)
        self.assertEqual(ExecutionWorkflowTemplate.objects.count(), template_count_before)
        self.assertEqual(ExecutionWorkflowTemplateVersion.objects.count(), version_count_before)
        self.assertEqual(ExecutionMilestoneDefinition.objects.count(), milestone_count_before)
        self.assertEqual(ExecutionMilestoneDependency.objects.count(), dependency_count_before)

    def test_published_history_safety(self):
        """Published semantic rows and IDs remain completely unchanged after rerun."""
        v1 = seed_bitumen_workflow_v1()
        milestone_ids_before = list(
            v1.milestones.order_by("sort_order").values_list("id", "code", "sort_order", "name_en", "name_fa")
        )
        dependency_tuples_before = list(
            ExecutionMilestoneDependency.objects.filter(milestone__workflow_template_version=v1)
            .order_by("milestone__sort_order")
            .values_list("milestone__code", "prerequisite__code")
        )

        # Rerun seed
        seed_bitumen_workflow_v1()

        v1.refresh_from_db()
        milestone_ids_after = list(
            v1.milestones.order_by("sort_order").values_list("id", "code", "sort_order", "name_en", "name_fa")
        )
        dependency_tuples_after = list(
            ExecutionMilestoneDependency.objects.filter(milestone__workflow_template_version=v1)
            .order_by("milestone__sort_order")
            .values_list("milestone__code", "prerequisite__code")
        )

        self.assertEqual(milestone_ids_before, milestone_ids_after)
        self.assertEqual(dependency_tuples_before, dependency_tuples_after)

    def test_conflict_detection_different_code(self):
        """If published v1 has conflicting milestone code, seed raises WorkflowSeedConflictError without mutating."""
        v1 = seed_bitumen_workflow_v1()

        # Simulate historical mutation directly in DB bypass to test conflict detection
        ExecutionMilestoneDefinition.objects.filter(
            workflow_template_version=v1, code="ACCEPTED"
        ).update(code="BUYER_ACCEPTED")

        with self.assertRaises(WorkflowSeedConflictError) as ctx:
            seed_bitumen_workflow_v1()

        self.assertIn("conflicts with canonical seed specification", str(ctx.exception))
        # Ensure the row was not silently repaired
        self.assertTrue(
            ExecutionMilestoneDefinition.objects.filter(
                workflow_template_version=v1, code="BUYER_ACCEPTED"
            ).exists()
        )

    def test_conflict_detection_different_label(self):
        """If published v1 has conflicting labels, seed raises WorkflowSeedConflictError."""
        v1 = seed_bitumen_workflow_v1()

        ExecutionMilestoneDefinition.objects.filter(
            workflow_template_version=v1, code="CONTRACT_SIGNED"
        ).update(name_en="Sign Contract Now")

        with self.assertRaises(WorkflowSeedConflictError) as ctx:
            seed_bitumen_workflow_v1()

        self.assertIn("Milestone name_en mismatch", str(ctx.exception))

    def test_conflict_detection_missing_milestone(self):
        """If published v1 has missing milestone (9 instead of 10), seed raises WorkflowSeedConflictError."""
        v1 = seed_bitumen_workflow_v1()

        # Temporarily flip status to DRAFT in DB to delete rows and restore to PUBLISHED
        ExecutionWorkflowTemplateVersion.objects.filter(pk=v1.pk).update(status=WorkflowVersionStatus.DRAFT)
        ExecutionMilestoneDependency.objects.filter(
            milestone__workflow_template_version=v1, prerequisite__code="DELIVERED"
        ).delete()
        ExecutionMilestoneDependency.objects.filter(
            milestone__workflow_template_version=v1, milestone__code="DELIVERED"
        ).delete()
        ExecutionMilestoneDefinition.objects.filter(
            workflow_template_version=v1, code="DELIVERED"
        ).delete()
        ExecutionWorkflowTemplateVersion.objects.filter(pk=v1.pk).update(status=WorkflowVersionStatus.PUBLISHED)

        with self.assertRaises(WorkflowSeedConflictError) as ctx:
            seed_bitumen_workflow_v1()

        self.assertIn("Milestone count mismatch", str(ctx.exception))

    def test_conflict_detection_altered_dependencies(self):
        """If published v1 has altered prerequisite dependencies, seed raises WorkflowSeedConflictError."""
        v1 = seed_bitumen_workflow_v1()

        # Temporarily flip status to DRAFT in DB to delete dependency and restore to PUBLISHED
        ExecutionWorkflowTemplateVersion.objects.filter(pk=v1.pk).update(status=WorkflowVersionStatus.DRAFT)
        ExecutionMilestoneDependency.objects.filter(
            milestone__workflow_template_version=v1, milestone__code="CONTRACT_SIGNED"
        ).delete()
        ExecutionWorkflowTemplateVersion.objects.filter(pk=v1.pk).update(status=WorkflowVersionStatus.PUBLISHED)

        with self.assertRaises(WorkflowSeedConflictError) as ctx:
            seed_bitumen_workflow_v1()

        self.assertIn("Milestone prerequisites mismatch", str(ctx.exception))

    def test_retired_version_not_resurrected(self):
        """If canonical v1 exists but is RETIRED, seed raises WorkflowSeedConflictError and never resurrects it."""
        v1 = seed_bitumen_workflow_v1()

        # Manually retire v1 by creating v2, making v2 active, and retiring v1
        template = v1.template
        v2 = ExecutionWorkflowTemplateVersion.objects.create(
            template=template,
            version_number=2,
            status=WorkflowVersionStatus.PUBLISHED,
        )
        template.active_version = v2
        template.save()

        v1.status = WorkflowVersionStatus.RETIRED
        v1.save(update_fields=["status"])

        with self.assertRaises(WorkflowSeedConflictError) as ctx:
            seed_bitumen_workflow_v1()

        self.assertIn("version 1 is RETIRED", str(ctx.exception))
        v1.refresh_from_db()
        self.assertEqual(v1.status, WorkflowVersionStatus.RETIRED)

    def test_draft_safety_unrelated_draft_preserved(self):
        """Unrelated draft versions (e.g. v2 in DRAFT) are not destroyed when seeding v1."""
        template = ExecutionWorkflowTemplate.objects.create(
            code=BITUMEN_WORKFLOW_TEMPLATE_CODE,
            name_fa=BITUMEN_WORKFLOW_TEMPLATE_NAME_FA,
            name_en=BITUMEN_WORKFLOW_TEMPLATE_NAME_EN,
        )
        unrelated_draft_v2 = ExecutionWorkflowTemplateVersion.objects.create(
            template=template,
            version_number=2,
            status=WorkflowVersionStatus.DRAFT,
            change_summary="Unrelated future draft.",
        )

        v1 = seed_bitumen_workflow_v1()

        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v1.status, WorkflowVersionStatus.PUBLISHED)
        # Unrelated draft still exists
        self.assertTrue(
            ExecutionWorkflowTemplateVersion.objects.filter(pk=unrelated_draft_v2.pk).exists()
        )

    def test_prerequisite_chain_exact(self):
        """Prerequisites form the exact linear prerequisite sequence without branching."""
        v1 = seed_bitumen_workflow_v1()
        milestones = {m.code: m for m in v1.milestones.prefetch_related("prerequisite_dependencies__prerequisite")}

        # 1. AWARDED has no prerequisites
        self.assertEqual(milestones["AWARDED"].prerequisite_dependencies.count(), 0)

        # 2. CONTRACT_SIGNED requires AWARDED
        self.assertEqual(
            list(milestones["CONTRACT_SIGNED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["AWARDED"],
        )

        # 3. PAYMENT_REPORTED requires CONTRACT_SIGNED
        self.assertEqual(
            list(milestones["PAYMENT_REPORTED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["CONTRACT_SIGNED"],
        )

        # 4. LOADING_SCHEDULED requires PAYMENT_REPORTED
        self.assertEqual(
            list(milestones["LOADING_SCHEDULED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["PAYMENT_REPORTED"],
        )

        # 5. LOADED requires LOADING_SCHEDULED
        self.assertEqual(
            list(milestones["LOADED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["LOADING_SCHEDULED"],
        )

        # 6. INSPECTION_COMPLETED requires LOADED
        self.assertEqual(
            list(milestones["INSPECTION_COMPLETED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["LOADED"],
        )

        # 7. IN_TRANSIT requires INSPECTION_COMPLETED
        self.assertEqual(
            list(milestones["IN_TRANSIT"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["INSPECTION_COMPLETED"],
        )

        # 8. DELIVERED requires IN_TRANSIT
        self.assertEqual(
            list(milestones["DELIVERED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["IN_TRANSIT"],
        )

        # 9. ACCEPTED requires DELIVERED
        self.assertEqual(
            list(milestones["ACCEPTED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["DELIVERED"],
        )

        # 10. CLOSED requires ACCEPTED
        self.assertEqual(
            list(milestones["CLOSED"].prerequisite_dependencies.values_list("prerequisite__code", flat=True)),
            ["ACCEPTED"],
        )

    def test_terminal_closed_flag(self):
        """Only CLOSED has terminal=True (and blocking=True). Milestones 1-9 have terminal=False."""
        v1 = seed_bitumen_workflow_v1()
        for m in v1.milestones.all():
            if m.code == "CLOSED":
                self.assertTrue(m.terminal, "CLOSED must be terminal=True")
                self.assertTrue(m.blocking, "CLOSED must be blocking=True")
                self.assertTrue(m.required, "CLOSED must be required=True")
            else:
                self.assertFalse(m.terminal, f"{m.code} must not be terminal")
                self.assertTrue(m.required, f"{m.code} must be required")
                self.assertFalse(m.blocking, f"{m.code} must not be blocking")

    def test_no_runtime_execution_created(self):
        """T1002 seed creates zero runtime Execution or timeline instances."""
        seed_bitumen_workflow_v1()
        # Verify no runtime model instances exist
        from django.apps import apps
        if apps.is_installed("execution"):
            for model in apps.get_app_config("execution").get_models():
                if model.__name__ in ("Execution", "ExecutionMilestone"):
                    self.assertEqual(model.objects.count(), 0)

    def test_generic_engine_guard(self):
        """Generic execution services must not contain any commodity branching logic."""
        services_dir = Path(__file__).resolve().parent.parent / "services"
        for py_file in services_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            self.assertNotIn(
                'commodity.code == "bitumen"',
                content,
                f"Generic service {py_file.name} contains hard-coded commodity branching!",
            )
            self.assertNotIn(
                "commodity.code == 'bitumen'",
                content,
                f"Generic service {py_file.name} contains hard-coded commodity branching!",
            )

    def test_management_command_execution(self):
        """Management command seed_bitumen_workflow runs cleanly, idempotently, and handles errors."""
        out = StringIO()
        call_command("seed_bitumen_workflow", stdout=out)
        self.assertIn("Successfully seeded and published Bitumen execution workflow v1", out.getvalue())

        # Second run: identical warning
        out2 = StringIO()
        call_command("seed_bitumen_workflow", stdout=out2)
        self.assertIn("already exists and is identical", out2.getvalue())
        self.assertIn("Skipping mutation to preserve historical semantics", out2.getvalue())

        # Tampered state triggers CommandError
        v1 = ExecutionWorkflowTemplateVersion.objects.get(
            template__code=BITUMEN_WORKFLOW_TEMPLATE_CODE, version_number=1
        )
        ExecutionMilestoneDefinition.objects.filter(
            workflow_template_version=v1, code="CLOSED"
        ).update(terminal=False)

        out3 = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_bitumen_workflow", stdout=out3)

        self.assertIn("Bitumen workflow seed conflict", str(ctx.exception))
