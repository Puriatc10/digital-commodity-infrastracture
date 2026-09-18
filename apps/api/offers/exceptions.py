from django.core.exceptions import ObjectDoesNotExist, PermissionDenied


class OfferDomainError(Exception):
    """Base domain exception for Offer operations."""

    pass


class OfferNotFoundError(OfferDomainError, ObjectDoesNotExist):
    """Raised when an Offer cannot be found."""

    pass


class OfferPermissionDeniedError(OfferDomainError, PermissionDenied):
    """Raised when an actor lacks authority to create or access an Offer."""

    pass


class OfferValidationError(OfferDomainError, ValueError):
    """Raised when domain validation or constraint rules fail."""

    pass


class OfferConflictError(OfferDomainError):
    """Raised when a duplicate offer thread or concurrent creation conflict occurs."""

    pass


class OfferStateError(OfferDomainError):
    """Raised when an operation is invalid for the target RFQ lifecycle state."""

    pass
