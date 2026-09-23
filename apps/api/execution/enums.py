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


class ExecutionStatus(models.TextChoices):
    """
    Lifecycle status of an Execution instance (Epic 10 Contract §8).

    Invariants:
    - Minimal lifecycle: OPEN, CLOSED.
    - No milestone names duplicated in execution status.
    - CLOSED is reached atomically upon terminal milestone completion.
    """

    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class MilestoneStatus(models.TextChoices):
    """
    Runtime status of an ExecutionMilestone instance (Epic 10 Contract §16).

    Invariants:
    - COMPLETED is authoritative historical fact; cannot be casually reverted or altered.
    - SKIPPED requires explicit reason and authorization.
    - BLOCKED requires explicit reason and reference.
    """

    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    BLOCKED = "BLOCKED", "Blocked"
    SKIPPED = "SKIPPED", "Skipped"


class TimelineEventType(models.TextChoices):
    """
    Deterministic domain event type for Execution Timeline projections (Epic 10 Contract §32, §33, §34).

    Order priority (stable_type_priority):
    - EXECUTION_CREATED: 10
    - MILESTONE_STARTED: 20
    - MILESTONE_COMPLETED: 30
    - MILESTONE_BLOCKED: 35
    - MILESTONE_SKIPPED: 40
    - EXECUTION_CLOSED: 50
    """

    EXECUTION_CREATED = "EXECUTION_CREATED", "Execution Created"
    MILESTONE_STARTED = "MILESTONE_STARTED", "Milestone Started"
    MILESTONE_COMPLETED = "MILESTONE_COMPLETED", "Milestone Completed"
    MILESTONE_BLOCKED = "MILESTONE_BLOCKED", "Milestone Blocked"
    MILESTONE_SKIPPED = "MILESTONE_SKIPPED", "Milestone Skipped"
    EXECUTION_CLOSED = "EXECUTION_CLOSED", "Execution Closed"

