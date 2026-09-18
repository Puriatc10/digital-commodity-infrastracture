from decimal import Decimal
from typing import Mapping

from django.db import transaction

from offers.enums import DecisionDimension, DecisionProfileLifecycleStatus
from offers.exceptions import (
    DecisionPolicyError,
    DecisionProfileSeedConflictError,
)
from offers.models.decision import (
    DecisionDimensionWeight,
    DecisionProfile,
    DecisionProfileVersion,
)

DEFAULT_DECISION_PROFILE_CODE = "default-procurement-decision"
DEFAULT_DECISION_PROFILE_NAME = "Default Procurement Decision Profile"
DEFAULT_DECISION_PROFILE_DESCRIPTION = (
    "Authoritative platform default decision profile v1 for multi-criteria procurement evaluation."
)

REQUIRED_V1_DIMENSIONS: Mapping[DecisionDimension, Decimal] = {
    DecisionDimension.COST: Decimal("35.00"),
    DecisionDimension.QUALITY: Decimal("25.00"),
    DecisionDimension.DELIVERY: Decimal("15.00"),
    DecisionDimension.PAYMENT: Decimal("10.00"),
    DecisionDimension.TRUST: Decimal("10.00"),
    DecisionDimension.COMPLETENESS: Decimal("5.00"),
}

DEFAULT_V1_MINIMUM_COVERAGE = Decimal("70.00")


def validate_decision_profile_version(profile_version: DecisionProfileVersion) -> None:
    """
    Validate that a DecisionProfileVersion complies with platform invariants prior to publication.

    Invariants:
    - Must contain exactly the required dimensions (COST, QUALITY, DELIVERY, PAYMENT, TRUST, COMPLETENESS).
    - No duplicate dimensions.
    - Weights must sum to exactly 100.00.
    - Minimum coverage must be in [0.00, 100.00].
    """
    if profile_version.minimum_coverage is None or profile_version.minimum_coverage < Decimal("0") or profile_version.minimum_coverage > Decimal("100"):
        raise DecisionPolicyError(
            f"Decision profile version minimum coverage must be between 0 and 100, got: {profile_version.minimum_coverage}"
        )

    dimension_weights = list(profile_version.dimension_weights.all())
    if not dimension_weights:
        raise DecisionPolicyError("Decision profile version must contain dimension weights.")

    seen_dimensions: set[str] = set()
    total_weight = Decimal("0")

    for dw in dimension_weights:
        if dw.dimension in seen_dimensions:
            raise DecisionPolicyError(f"Duplicate dimension weight found for dimension: {dw.dimension}")
        seen_dimensions.add(dw.dimension)

        if dw.weight is None or dw.weight < Decimal("0"):
            raise DecisionPolicyError(f"Dimension weight for {dw.dimension} cannot be negative: {dw.weight}")

        total_weight += Decimal(str(dw.weight))

    required_dim_set = {d.value for d in REQUIRED_V1_DIMENSIONS.keys()}
    missing_dims = required_dim_set - seen_dimensions
    extra_dims = seen_dimensions - required_dim_set

    if missing_dims:
        raise DecisionPolicyError(f"Decision profile version is missing required dimensions: {sorted(missing_dims)}")
    if extra_dims:
        raise DecisionPolicyError(f"Decision profile version has unsupported extra dimensions: {sorted(extra_dims)}")

    if total_weight != Decimal("100.00") and total_weight != Decimal("100"):
        raise DecisionPolicyError(
            f"Configured dimension weights total {total_weight}%, but must equal exactly 100.00%."
        )


@transaction.atomic
def seed_decision_profile_v1() -> DecisionProfileVersion:
    """
    Idempotently and deterministically seed the default Published DecisionProfile v1 (T0808).

    Guarantees:
    - Creates 'default-procurement-decision' profile aggregate if missing.
    - If version 1 exists and matches exact published semantics (status=PUBLISHED,
      min_coverage=70, weights: Cost 35, Quality 25, Delivery 15, Payment 10, Trust 10, Completeness 5):
      returns existing version (no-op).
    - If version 1 exists with conflicting semantics: fails clearly with DecisionProfileSeedConflictError.
      Never overwrites or mutates Published history.
    - If version 1 does not exist: creates DRAFT, seeds exact dimension weights, validates,
      and transitions to PUBLISHED.
    """
    profile, _ = DecisionProfile.objects.get_or_create(
        code=DEFAULT_DECISION_PROFILE_CODE,
        defaults={
            "name": DEFAULT_DECISION_PROFILE_NAME,
            "description": DEFAULT_DECISION_PROFILE_DESCRIPTION,
        },
    )

    existing_v1 = (
        DecisionProfileVersion.objects.filter(profile=profile, version=1)
        .prefetch_related("dimension_weights")
        .first()
    )

    if existing_v1:
        # Verify status
        if existing_v1.status != DecisionProfileLifecycleStatus.PUBLISHED:
            raise DecisionProfileSeedConflictError(
                f"Existing DecisionProfileVersion v1 has status '{existing_v1.status}', "
                f"expected '{DecisionProfileLifecycleStatus.PUBLISHED}'."
            )

        # Verify minimum coverage
        if existing_v1.minimum_coverage != DEFAULT_V1_MINIMUM_COVERAGE:
            raise DecisionProfileSeedConflictError(
                f"Existing DecisionProfileVersion v1 minimum coverage {existing_v1.minimum_coverage} "
                f"differs from target seed {DEFAULT_V1_MINIMUM_COVERAGE}."
            )

        # Verify dimension weights
        existing_weights = {
            dw.dimension: Decimal(str(dw.weight))
            for dw in existing_v1.dimension_weights.all()
        }
        target_weights = {
            dim.value: weight for dim, weight in REQUIRED_V1_DIMENSIONS.items()
        }

        if existing_weights != target_weights:
            raise DecisionProfileSeedConflictError(
                f"Existing DecisionProfileVersion v1 dimension weights {existing_weights} "
                f"conflict with target seed {target_weights}."
            )

        # Identical published version exists -> clean no-op
        return existing_v1

    # Create new v1 version under DRAFT lifecycle
    v1 = DecisionProfileVersion.objects.create(
        profile=profile,
        version=1,
        status=DecisionProfileLifecycleStatus.DRAFT,
        minimum_coverage=DEFAULT_V1_MINIMUM_COVERAGE,
        description="Deterministic platform default procurement decision policy v1.",
    )

    for dim, weight in REQUIRED_V1_DIMENSIONS.items():
        DecisionDimensionWeight.objects.create(
            profile_version=v1,
            dimension=dim.value,
            weight=weight,
        )

    # Validate before publication
    validate_decision_profile_version(v1)

    # Transition to PUBLISHED
    v1.status = DecisionProfileLifecycleStatus.PUBLISHED
    v1.save(update_fields=["status", "updated_at"])

    return v1
