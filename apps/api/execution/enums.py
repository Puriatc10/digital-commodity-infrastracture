from django.db import models


class WorkflowVersionStatus(models.TextChoices):
    """
    Lifecycle status of an ExecutionWorkflowTemplateVersion (Epic 10 Contract §11).

    Lifecycle transitions:
        DRAFT -> PUBLISHED -> RETIRED

    Invariants:
    - DRAFT: editable definition and dependencies
    - PUBLISHED: immutable definition and dependency graph
    - RETIRED: immutable and historical; cannot be activated for new executions
    """

    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"
