from offers.exceptions import StaleVersionError, AwardNotFoundError


class DealDomainError(Exception):
    """Base domain exception for Deal operations."""


class AwardNotFinalizedError(DealDomainError):
    """Raised when materializing deals for an award that is not in FINALIZED status."""


class DealSourceIntegrityError(DealDomainError):
    """Raised when source graph references fail referential or authoritative validation."""


class DealPermissionDeniedError(DealDomainError):
    """Raised when an actor lacks authority to materialize or access deals."""


class DealNotFoundError(DealDomainError):
    """Raised when a referenced Deal entity does not exist."""


class DealValidationError(DealDomainError):
    """Raised when Deal data fails domain validation."""


class AttributionAlreadyResolvedError(DealDomainError):
    """Raised when attempting to resolve or modify an attribution that is already RESOLVED."""




class AttributionNotFoundError(DealDomainError):
    """Raised when an attribution aggregate does not exist for a Deal."""


__all__ = [
    "DealDomainError",
    "AwardNotFinalizedError",
    "DealSourceIntegrityError",
    "DealPermissionDeniedError",
    "DealNotFoundError",
    "DealValidationError",
    "StaleVersionError",
    "AwardNotFoundError",
    "AttributionAlreadyResolvedError",
    "AttributionNotFoundError",
]

