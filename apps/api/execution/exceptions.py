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
