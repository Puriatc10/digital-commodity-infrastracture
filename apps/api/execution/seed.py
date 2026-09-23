"""
Deterministic Bitumen Execution Workflow v1 Seed (Epic 10 Contract §21, T1002).

Invariants:
- Exactly 10 milestones in exact order:
    1. AWARDED
    2. CONTRACT_SIGNED
    3. PAYMENT_REPORTED
    4. LOADING_SCHEDULED
    5. LOADED
    6. INSPECTION_COMPLETED
    7. IN_TRANSIT
    8. DELIVERED
    9. ACCEPTED
    10. CLOSED
- Localized labels for `fa` and `en`.
- Published v1 lifecycle: Version 1, PUBLISHED, active.
- Idempotency & Three-way Semantics:
    * Missing -> Create draft v1, add 10 milestones with prerequisites, publish.
    * Identical Existing Published v1 -> Clean no-op, returns existing published version.
    * Conflicting Existing Published v1 -> Explicit WorkflowSeedConflictError, zero mutations.
    * Retired Existing v1 -> Explicit WorkflowSeedConflictError, no silent resurrection.
- History Safety: Published workflow history is immutable; no `update_or_create` on published rows.
- Draft Safety: Unrelated draft versions are preserved.
- Sequential prerequisite chain: AWARDED -> CONTRACT_SIGNED -> ... -> CLOSED.
- Terminal milestone: Only CLOSED has terminal=True (and blocking=True).
- Genericity: No commodity-specific branching in generic workflow engine.
"""

from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from execution.enums import WorkflowVersionStatus
from execution.exceptions import WorkflowSeedConflictError
from execution.models.dependency import ExecutionMilestoneDependency
from execution.models.milestone_definition import ExecutionMilestoneDefinition
from execution.models.template import ExecutionWorkflowTemplate, lock_workflow_templates
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.permissions import check_workflow_management_authority
from execution.services.validation_service import validate_version_for_publish

BITUMEN_WORKFLOW_TEMPLATE_CODE = "bitumen_standard"
BITUMEN_WORKFLOW_TEMPLATE_NAME_FA = "گردش‌کار اجرای استاندارد قیر"
BITUMEN_WORKFLOW_TEMPLATE_NAME_EN = "Standard Bitumen Execution Workflow"
BITUMEN_WORKFLOW_TEMPLATE_DESCRIPTION = (
    "Authoritative platform standard physical execution workflow v1 for bitumen trade and delivery."
)

BITUMEN_V1_MILESTONES: Tuple[Dict[str, Any], ...] = (
    {
        "code": "AWARDED",
        "name_fa": "واگذاری معامله",
        "name_en": "Awarded",
        "sort_order": 1,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": (),
    },
    {
        "code": "CONTRACT_SIGNED",
        "name_fa": "امضای قرارداد",
        "name_en": "Contract Signed",
        "sort_order": 2,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("AWARDED",),
    },
    {
        "code": "PAYMENT_REPORTED",
        "name_fa": "گزارش پرداخت",
        "name_en": "Payment Reported",
        "sort_order": 3,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("CONTRACT_SIGNED",),
    },
    {
        "code": "LOADING_SCHEDULED",
        "name_fa": "زمان‌بندی بارگیری",
        "name_en": "Loading Scheduled",
        "sort_order": 4,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("PAYMENT_REPORTED",),
    },
    {
        "code": "LOADED",
        "name_fa": "بارگیری شده",
        "name_en": "Loaded",
        "sort_order": 5,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("LOADING_SCHEDULED",),
    },
    {
        "code": "INSPECTION_COMPLETED",
        "name_fa": "تکمیل بازرسی",
        "name_en": "Inspection Completed",
        "sort_order": 6,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("LOADED",),
    },
    {
        "code": "IN_TRANSIT",
        "name_fa": "در حال حمل",
        "name_en": "In Transit",
        "sort_order": 7,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("INSPECTION_COMPLETED",),
    },
    {
        "code": "DELIVERED",
        "name_fa": "تحویل داده شده",
        "name_en": "Delivered",
        "sort_order": 8,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("IN_TRANSIT",),
    },
    {
        "code": "ACCEPTED",
        "name_fa": "پذیرش کالا",
        "name_en": "Accepted",
        "sort_order": 9,
        "required": True,
        "blocking": False,
        "terminal": False,
        "prerequisites": ("DELIVERED",),
    },
    {
        "code": "CLOSED",
        "name_fa": "پایان اجرا",
        "name_en": "Closed",
        "sort_order": 10,
        "required": True,
        "blocking": True,
        "terminal": True,
        "prerequisites": ("ACCEPTED",),
    },
)


def verify_published_v1_identical(
    version: ExecutionWorkflowTemplateVersion,
) -> Tuple[bool, Optional[str]]:
    """
    Verify whether an existing published version 1 strictly matches the canonical Bitumen v1 specification.
    Returns (True, None) if identical, or (False, reason) if any discrepancy is found.
    """
    milestones = list(
        ExecutionMilestoneDefinition.objects.filter(workflow_template_version=version)
        .prefetch_related("prerequisite_dependencies__prerequisite")
        .order_by("sort_order")
    )

    if len(milestones) != len(BITUMEN_V1_MILESTONES):
        return (
            False,
            f"Milestone count mismatch: expected {len(BITUMEN_V1_MILESTONES)}, got {len(milestones)}.",
        )

    for actual, expected in zip(milestones, BITUMEN_V1_MILESTONES):
        if actual.code != expected["code"]:
            return (
                False,
                f"Milestone code mismatch at sort_order {expected['sort_order']}: "
                f"expected '{expected['code']}', got '{actual.code}'.",
            )
        if actual.sort_order != expected["sort_order"]:
            return (
                False,
                f"Milestone sort_order mismatch for '{expected['code']}': "
                f"expected {expected['sort_order']}, got {actual.sort_order}.",
            )
        if actual.name_fa != expected["name_fa"]:
            return (
                False,
                f"Milestone name_fa mismatch for '{expected['code']}': "
                f"expected '{expected['name_fa']}', got '{actual.name_fa}'.",
            )
        if actual.name_en != expected["name_en"]:
            return (
                False,
                f"Milestone name_en mismatch for '{expected['code']}': "
                f"expected '{expected['name_en']}', got '{actual.name_en}'.",
            )
        if actual.required != expected["required"]:
            return (
                False,
                f"Milestone required flag mismatch for '{expected['code']}': "
                f"expected {expected['required']}, got {actual.required}.",
            )
        if actual.blocking != expected["blocking"]:
            return (
                False,
                f"Milestone blocking flag mismatch for '{expected['code']}': "
                f"expected {expected['blocking']}, got {actual.blocking}.",
            )
        if actual.terminal != expected["terminal"]:
            return (
                False,
                f"Milestone terminal flag mismatch for '{expected['code']}': "
                f"expected {expected['terminal']}, got {actual.terminal}.",
            )

        actual_prereq_codes = tuple(
            dep.prerequisite.code
            for dep in actual.prerequisite_dependencies.all().order_by("prerequisite__sort_order")
        )
        expected_prereq_codes = expected["prerequisites"]
        if actual_prereq_codes != expected_prereq_codes:
            return (
                False,
                f"Milestone prerequisites mismatch for '{expected['code']}': "
                f"expected {expected_prereq_codes}, got {actual_prereq_codes}.",
            )

    return (True, None)


@transaction.atomic
def seed_bitumen_workflow_v1(
    *,
    actor: Any = None,
) -> ExecutionWorkflowTemplateVersion:
    """
    Deterministically and idempotently seed the canonical Bitumen execution workflow v1.

    Three-Way Semantics:
    1. Missing: Creates template and draft v1, materializes exact 10 milestones and dependencies, publishes.
    2. Identical Published v1: Returns cleanly without mutating published history (no-op).
    3. Conflicting Published v1: Raises WorkflowSeedConflictError without mutating history.
    4. Retired v1: Raises WorkflowSeedConflictError; never silently resurrects retired versions.
    5. Draft Safety: Preserves any unrelated drafts (e.g. v2).
    """
    if actor is not None:
        check_workflow_management_authority(actor)

    # 1. Resolve or create Template Aggregate
    template, _ = ExecutionWorkflowTemplate.objects.get_or_create(
        code=BITUMEN_WORKFLOW_TEMPLATE_CODE,
        defaults={
            "name_fa": BITUMEN_WORKFLOW_TEMPLATE_NAME_FA,
            "name_en": BITUMEN_WORKFLOW_TEMPLATE_NAME_EN,
            "description": BITUMEN_WORKFLOW_TEMPLATE_DESCRIPTION,
            "is_active": True,
        },
    )

    lock_workflow_templates([template.pk])
    template.refresh_from_db()

    # 2. Inspect version 1
    existing_v1 = (
        ExecutionWorkflowTemplateVersion.objects.select_for_update()
        .filter(template=template, version_number=1)
        .first()
    )

    if existing_v1:
        # Check if RETIRED
        if existing_v1.status == WorkflowVersionStatus.RETIRED:
            raise WorkflowSeedConflictError(
                f"Workflow template '{template.code}' version 1 is RETIRED. "
                "Retired workflow versions cannot be re-seeded, overwritten, or resurrected."
            )

        # Check if PUBLISHED
        if existing_v1.status == WorkflowVersionStatus.PUBLISHED:
            is_identical, reason = verify_published_v1_identical(existing_v1)
            if not is_identical:
                raise WorkflowSeedConflictError(
                    f"Existing Published Workflow template '{template.code}' v1 conflicts with canonical seed specification: {reason} "
                    "Published workflow history is immutable and cannot be overwritten."
                )

            # Identical existing published v1 - ensure active version is set if template has no active version
            if template.active_version_id is None:
                template.active_version = existing_v1
                template.save()

            return existing_v1

        # existing_v1 is DRAFT - we can clean and populate draft milestones
        if existing_v1.status == WorkflowVersionStatus.DRAFT:
            # Delete any existing draft dependencies and milestones for this version
            ExecutionMilestoneDependency.objects.filter(
                milestone__workflow_template_version=existing_v1
            ).delete()
            ExecutionMilestoneDefinition.objects.filter(
                workflow_template_version=existing_v1
            ).delete()
            draft_v1 = existing_v1
    else:
        # Create draft v1
        draft_v1 = ExecutionWorkflowTemplateVersion(
            template=template,
            version_number=1,
            status=WorkflowVersionStatus.DRAFT,
            change_summary="Authoritative canonical Bitumen physical execution workflow v1.",
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        draft_v1.save()

    # 3. Add milestone definitions in exact sequential order
    for spec in BITUMEN_V1_MILESTONES:
        milestone = ExecutionMilestoneDefinition(
            workflow_template_version=draft_v1,
            code=spec["code"],
            name_fa=spec["name_fa"],
            name_en=spec["name_en"],
            sort_order=spec["sort_order"],
            required=spec["required"],
            blocking=spec["blocking"],
            terminal=spec["terminal"],
        )
        milestone.save()

        if spec["prerequisites"]:
            for p_code in spec["prerequisites"]:
                prereq = ExecutionMilestoneDefinition.objects.get(
                    workflow_template_version=draft_v1,
                    code=p_code,
                )
                ExecutionMilestoneDependency.objects.create(
                    milestone=milestone,
                    prerequisite=prereq,
                )

    # 4. Validate graph & semantic invariants via authoritative T1001 validation
    validate_version_for_publish(draft_v1)

    # 5. Transition to PUBLISHED
    draft_v1.status = WorkflowVersionStatus.PUBLISHED
    draft_v1.published_at = timezone.now()
    if actor and getattr(actor, "is_authenticated", False):
        draft_v1.published_by = actor
    draft_v1.save()

    # 6. Activate if template has no active version
    if template.active_version_id is None:
        template.active_version = draft_v1
        template.save()

    return draft_v1
