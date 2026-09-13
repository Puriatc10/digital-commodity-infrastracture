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


class InvitationError(RFQDomainError):
    """Base domain exception for RFQ invitation operations."""

    pass


class InvitationNotFoundError(InvitationError, ObjectDoesNotExist):
    """Raised when an invitation cannot be found or is hidden."""

    pass


class DuplicateInvitationError(InvitationError):
    """Raised when the target organization is already invited to this RFQ."""

    pass


class InviteeIneligibleError(InvitationError):
    """Raised when the target organization is ineligible (e.g. buyer-only, self-invite, inactive)."""

    pass


class InvalidInvitationStatusError(InvitationError):
    """Raised when an invalid state transition or action on an invitation is attempted."""

    pass


class InvitationPermissionDeniedError(InvitationError):
    """Raised when the actor lacks authorization to manage or act on the invitation."""

    pass
