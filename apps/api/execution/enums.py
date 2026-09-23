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
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED", "Inspection Scheduled"
    INSPECTION_COMPLETED = "INSPECTION_COMPLETED", "Inspection Completed"
    INSPECTION_CANCELLED = "INSPECTION_CANCELLED", "Inspection Cancelled"
    PAYMENT_REPORTED = "PAYMENT_REPORTED", "Payment Reported"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Payment Confirmed"
    EXECUTION_CLOSED = "EXECUTION_CLOSED", "Execution Closed"


class PaymentStatus(models.TextChoices):
    """
    Authoritative lifecycle status of an ExecutionPayment instance (Epic 10 Contract §50–§56, T1006).

    Exact statuses:
    - EXPECTED: Initial commercial expectation established from Deal terms.
    - REPORTED: Operational payment fact reported by buyer/seller/operator.
    - CONFIRMED: Authorized operational confirmation recorded by platform Operator/Admin.

    Invariants:
    - Exactly EXPECTED -> REPORTED -> CONFIRMED.
    - No reverse transitions.
    - No direct EXPECTED -> CONFIRMED.
    """

    EXPECTED = "EXPECTED", "Expected"
    REPORTED = "REPORTED", "Reported"
    CONFIRMED = "CONFIRMED", "Confirmed"


class InspectionStatus(models.TextChoices):
    """
    Authoritative lifecycle status of an ExecutionInspection instance (Epic 10 Contract §44, T1005).

    Exact statuses:
    - NOT_REQUIRED: Commercial terms or buyer waiver determined inspection is not required.
    - PENDING: Required inspection awaiting scheduling.
    - SCHEDULED: Inspection date and agency scheduled.
    - COMPLETED: Inspection took place; authoritative historical completion facts recorded.
    - CANCELLED: Scheduled or pending inspection cancelled.
    """

    NOT_REQUIRED = "NOT_REQUIRED", "Not Required"
    PENDING = "PENDING", "Pending"
    SCHEDULED = "SCHEDULED", "Scheduled"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class InspectionResult(models.TextChoices):
    """
    Authoritative quality outcome of an ExecutionInspection (Epic 10 Contract §45, T1005).

    Exact results:
    - PASS: Inspection passed quality requirements.
    - FAIL: Inspection failed quality requirements (milestone completes; issues handled in T1008).
    - CONDITIONAL: Passed conditionally upon further action or minor variance.
    - UNKNOWN: Result not yet known or inspection not completed/not required.
    """

    PASS = "PASS", "Pass"
    FAIL = "FAIL", "Fail"
    CONDITIONAL = "CONDITIONAL", "Conditional"
    UNKNOWN = "UNKNOWN", "Unknown"


class TransportMode(models.TextChoices):
    """
    Canonical transport mode for execution logistics (Epic 10 Contract §37, T1004).

    Invariants:
    - Canonical enum: ROAD, SEA, RAIL, AIR, MULTIMODAL, OTHER.
    - Never infer transport mode from geography or commercial delivery terms.
    - Explicit values only.
    """

    ROAD = "ROAD", "Road"
    SEA = "SEA", "Sea"
    RAIL = "RAIL", "Rail"
    AIR = "AIR", "Air"
    MULTIMODAL = "MULTIMODAL", "Multimodal"
    OTHER = "OTHER", "Other"


