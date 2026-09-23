from django.core.management.base import BaseCommand, CommandError

from execution.enums import WorkflowVersionStatus
from execution.exceptions import WorkflowSeedConflictError
from execution.models.version import ExecutionWorkflowTemplateVersion
from execution.seed import (
    BITUMEN_WORKFLOW_TEMPLATE_CODE,
    seed_bitumen_workflow_v1,
)


class Command(BaseCommand):
    help = "Seeds deterministic platform standard Bitumen execution workflow v1 (Epic 10 Contract §21, T1002)."

    def handle(self, *args, **options):
        self.stdout.write(
            f"Seeding canonical Bitumen execution workflow v1 ({BITUMEN_WORKFLOW_TEMPLATE_CODE})..."
        )
        existing = ExecutionWorkflowTemplateVersion.objects.filter(
            template__code=BITUMEN_WORKFLOW_TEMPLATE_CODE,
            version_number=1,
        ).first()
        is_already_published = (
            existing is not None and existing.status == WorkflowVersionStatus.PUBLISHED
        )

        try:
            version = seed_bitumen_workflow_v1()
        except WorkflowSeedConflictError as exc:
            raise CommandError(f"Bitumen workflow seed conflict: {exc}") from exc

        if is_already_published:
            self.stdout.write(
                self.style.WARNING(
                    f"Published Bitumen execution workflow v1 already exists and is identical ({version}). "
                    "Skipping mutation to preserve historical semantics."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully seeded and published Bitumen execution workflow v1 ({version})."
                )
            )
