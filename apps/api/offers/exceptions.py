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


class DecisionExecutionError(DecisionDomainError):
    """Raised when an unexpected runtime provider or pipeline failure aborts the decision run."""

    pass


class RevisionRequestNotFoundError(OfferDomainError, ObjectDoesNotExist):
    """Raised when a RevisionRequest cannot be found."""

    pass


class AwardDomainError(OfferDomainError):
    """Base domain exception for Award operations (T0813)."""

    pass


class AwardNotFoundError(AwardDomainError, ObjectDoesNotExist):
    """Raised when an Award cannot be found."""

    pass


class AwardAllocationNotFoundError(AwardDomainError, ObjectDoesNotExist):
    """Raised when an AwardAllocation cannot be found."""

    pass


class AwardPermissionDeniedError(OfferPermissionDeniedError, AwardDomainError):
    """Raised when an actor lacks authorization to create, mutate, or finalize an Award."""

    pass


class AwardValidationError(AwardDomainError, ValueError):
    """Raised when domain validation, quantity limits, or schema constraints fail on Award."""

    pass


class AwardConflictError(OfferConflictError, AwardDomainError):
    """Raised when a concurrent award conflict or duplicate allocation occurs."""

    pass


class AwardImmutableError(AwardDomainError):
    """Raised when an attempt is made to mutate or re-finalize an already FINALIZED Award."""

    pass


class AwardEligibilityError(AwardDomainError, ValueError):
    """Raised when an offer version fails technical, trust, expiry, or provenance eligibility during award finalization."""

    pass



