from django.core.exceptions import ObjectDoesNotExist


class RFQDomainError(Exception):
    """Base domain exception for RFQ operations."""

    pass


class RFQNotFoundError(RFQDomainError, ObjectDoesNotExist):
    """Raised when an RFQ cannot be found."""

    pass


class StaleVersionError(RFQDomainError):
    """Raised when expected_version does not match current persisted aggregate version."""

    pass


class InvalidVersionError(RFQDomainError):
    """Raised when expected_version is missing, null, not an integer, or invalid."""

    pass


class InvalidTransitionError(RFQDomainError):
    """Raised when an illegal or unsupported lifecycle transition is attempted."""

    pass


class PublicationValidationError(RFQDomainError):
    """Raised when RFQ publication prerequisites or dynamic specification validation fails."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
