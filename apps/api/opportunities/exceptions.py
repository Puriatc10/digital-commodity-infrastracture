from django.core.exceptions import ObjectDoesNotExist


class OpportunityDomainError(Exception):
    """Base domain exception for Opportunity operations."""

    pass


class OpportunityNotFoundError(OpportunityDomainError, ObjectDoesNotExist):
    """Raised when an Opportunity cannot be found."""

    pass


class StaleVersionError(OpportunityDomainError):
    """Raised when expected_version does not match current persisted aggregate version."""

    pass


class InvalidVersionError(OpportunityDomainError):
    """Raised when expected_version is missing, null, not an integer, or invalid."""

    pass


class InvalidTransitionError(OpportunityDomainError):
    """Raised when an illegal or unsupported lifecycle transition is attempted."""

    pass


class OpportunityPermissionDeniedError(OpportunityDomainError):
    """Raised when an actor lacks authority to perform an Opportunity lifecycle transition."""

    pass


class ReservedTransitionError(OpportunityDomainError):
    """
    Raised when a reserved lifecycle transition (e.g. Converted) is attempted
    without an authoritative conversion target entity (T0609 RFQ / T0610 Supply Listing).
    """

    pass


class ContactAttemptNotFoundError(OpportunityDomainError, ObjectDoesNotExist):
    """Raised when a Contact Attempt cannot be found."""

    pass


class OpportunityTaskNotFoundError(OpportunityDomainError, ObjectDoesNotExist):
    """Raised when an Opportunity Task cannot be found."""

    pass


class OpportunityQualificationError(OpportunityDomainError):
    """
    Raised when an Opportunity fails authoritative qualification requirements evaluation.
    Carries structured, machine-readable lists of missing and invalid requirements.
    """

    def __init__(
        self,
        message: str = "Opportunity cannot be qualified due to missing or invalid requirements.",
        missing_requirements: list | None = None,
        invalid_requirements: list | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.missing_requirements = list(missing_requirements) if missing_requirements else []
        self.invalid_requirements = list(invalid_requirements) if invalid_requirements else []


class OpportunityAlreadyConvertedError(OpportunityDomainError):
    """Raised when attempting to convert an Opportunity that has already been converted."""

    pass


class OpportunityConversionError(OpportunityDomainError):
    """Raised when conversion prerequisites are not met (e.g. wrong direction, counterparty policy)."""

    pass
