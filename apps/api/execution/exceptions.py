class ExecutionError(Exception):
    """Base domain exception for the execution monitoring module."""


class ExecutionPermissionDeniedError(ExecutionError):
    """Raised when an actor lacks product authority for an execution action."""


class ExecutionValidationError(ExecutionError):
    """Raised when an execution or workflow domain rule is violated."""


class WorkflowTemplateNotFoundError(ExecutionError):
    """Raised when a workflow template cannot be found."""


class WorkflowVersionNotFoundError(ExecutionError):
    """Raised when a workflow template version cannot be found."""


class WorkflowMilestoneNotFoundError(ExecutionError):
    """Raised when a milestone definition cannot be found."""


class WorkflowTemplateInactiveError(ExecutionError):
    """Raised when an action is attempted on an inactive workflow template."""


class NoActiveWorkflowVersionError(ExecutionError):
    """Raised when a template does not have a usable active published version."""


class WorkflowImmutableError(ExecutionError):
    """Raised when a mutation is attempted on a published or retired workflow graph."""


class WorkflowLifecycleError(ExecutionError):
    """Raised when an illegal workflow version lifecycle transition is attempted."""


class WorkflowDependencyCycleError(ExecutionError):
    """Raised when a cycle is detected in milestone prerequisites."""


class WorkflowSeedConflictError(ExecutionError):
    """Raised when an existing published workflow version conflicts with seed specification, or when re-seeding retired version."""


class ExecutionNotFoundError(ExecutionError):
    """Raised when an execution instance cannot be found."""


class MilestoneNotFoundError(ExecutionError):
    """Raised when a milestone instance cannot be found."""


class MilestonePrerequisiteUnmetError(ExecutionError):
    """Raised when an action is attempted on a milestone whose prerequisites are not completed."""


class MilestoneAlreadyCompletedError(ExecutionError):
    """Raised when an action is attempted on an already COMPLETED milestone."""


class ExecutionClosedError(ExecutionError):
    """Raised when an action is attempted on an Execution that is already CLOSED."""


class InvalidMilestoneTransitionError(ExecutionError):
    """Raised when an illegal milestone lifecycle transition is requested."""


class StaleVersionError(ExecutionError):
    """Raised when optimistic concurrency check fails (expected_version != current version)."""


class CrossObjectIntegrityError(ExecutionError):
    """Raised when cross-referencing objects across disjoint deals or executions."""


class LogisticsNotFoundError(ExecutionError):
    """Raised when an execution logistics instance cannot be found."""


class InspectionNotFoundError(ExecutionError):
    """Raised when an execution inspection instance cannot be found."""


class InvalidInspectionTransitionError(ExecutionError):
    """Raised when an illegal inspection lifecycle transition is requested."""

