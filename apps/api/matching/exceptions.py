from django.core.exceptions import PermissionDenied


class MatchingError(Exception):
    """Base exception for all matching domain errors."""

    def __init__(self, message: str, code: str = "matching_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class RFQNotMatchableError(MatchingError):
    """Raised when an RFQ target is not in an approved matchable state (i.e. not Published)."""

    def __init__(self, message: str = "RFQ must be in Published status to execute matching.", code: str = "rfq_not_matchable"):
        super().__init__(message, code=code)


class RFQNotFoundError(MatchingError):
    """Raised when an RFQ target cannot be found or is hidden from the caller."""

    def __init__(self, message: str = "RFQ target not found or inaccessible.", code: str = "not_found_or_hidden"):
        super().__init__(message, code=code)


class NoPublishedPolicyError(MatchingError):
    """Raised when no valid Published MatchingPolicyVersion can be resolved."""

    def __init__(self, message: str = "No valid Published matching policy version found.", code: str = "no_published_policy"):
        super().__init__(message, code=code)


class UnsupportedAudienceError(MatchingError):
    """Raised when an unsupported matching audience is requested."""

    def __init__(self, message: str = "Unsupported matching audience requested.", code: str = "unsupported_audience"):
        super().__init__(message, code=code)


class InvalidPolicyConfigurationError(MatchingError):
    """Raised when a matching policy configuration fails validation (e.g. lane weights != 100)."""

    def __init__(self, message: str = "Matching policy configuration is invalid.", code: str = "invalid_policy_configuration"):
        super().__init__(message, code=code)


class PolicySeedConflictError(MatchingError):
    """Raised when an existing Published matching policy version has conflicting structural configuration during seed."""

    def __init__(self, message: str = "Conflicting configuration for Published matching policy version.", code: str = "policy_seed_conflict"):
        super().__init__(message, code=code)


class MatchingAuthorizationError(PermissionDenied):
    """Raised when an actor lacks authority to trigger matching or access candidate intelligence."""

    def __init__(self, message: str = "Actor is not authorized to execute matching or access results.", code: str = "unauthorized"):
        super().__init__(message)
        self.message = message
        self.code = code
