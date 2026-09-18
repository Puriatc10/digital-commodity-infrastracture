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


class OfferVersionNotFoundError(OfferDomainError, ObjectDoesNotExist):
    """Raised when an OfferVersion cannot be found."""

    pass


class OfferImmutableError(OfferDomainError):
    """Raised when an attempt is made to mutate or delete an immutable submitted OfferVersion."""

    pass


class InvalidVersionError(OfferDomainError, ValueError):
    """Raised when expected_version is missing, not an integer, or less than 1."""

    pass


class StaleVersionError(OfferConflictError):
    """Raised when expected_version does not match current aggregate_version."""

    pass


class OfferNormalizationError(OfferDomainError, ValueError):
    """Raised when offer normalisation fails due to invalid snapshot or policy inputs."""

    pass


class DecisionDomainError(OfferDomainError):
    """Base exception for decision support operations."""

    pass


class DecisionPolicyError(DecisionDomainError, ValueError):
    """Raised when decision policy configuration, lifecycle, or weighting invariants fail."""

    pass


class DecisionProfileNotFoundError(DecisionDomainError, ObjectDoesNotExist):
    """Raised when a requested DecisionProfile or DecisionProfileVersion cannot be found."""

    pass


class DecisionProfileSeedConflictError(DecisionPolicyError):
    """Raised when seeding encounters an existing profile version with conflicting semantics."""

    pass


class DecisionRunError(DecisionDomainError):
    """Raised when decision run creation or candidate materialization fails."""

    pass


class DecisionPermissionDeniedError(OfferPermissionDeniedError, DecisionDomainError):
    """Raised when an actor lacks authorization to execute or view decision intelligence."""

    pass


class DecisionValidationError(DecisionDomainError, ValueError):
    """Raised when candidate, signal, or run validation constraints fail."""

    pass

