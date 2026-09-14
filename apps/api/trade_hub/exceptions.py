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


class SpecificationValidationError(RFQDomainError):
    """Raised when dynamic commodity specification validation fails."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class RFQPermissionDeniedError(RFQDomainError):
    """Raised when an actor lacks authority to create, edit, or publish an RFQ."""

    pass


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


class SupplyListingDomainError(Exception):
    """Base domain exception for Supply Listing operations."""

    pass


class SupplyListingNotFoundError(SupplyListingDomainError, ObjectDoesNotExist):
    """Raised when a Supply Listing cannot be found or is hidden."""

    pass


class SupplyListingPermissionDeniedError(SupplyListingDomainError):
    """Raised when an actor lacks authority to create, edit, or activate a Supply Listing."""

    pass


class SupplyListingValidationError(SupplyListingDomainError):
    """Raised when Supply Listing activation prerequisites or dynamic specification validation fails."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
