from decimal import Decimal
from typing import Any, Dict

from django.db import transaction

from matching.enums import (
    CandidateLane,
    PolicyLifecycleStatus,
    SignalDimension,
)
from matching.exceptions import (
    InvalidPolicyConfigurationError,
    PolicySeedConflictError,
)
from matching.models.policy import MatchingPolicy, MatchingPolicyVersion
from matching.models.verification_rule import VerificationMatchingRule
from matching.rules.trust import DEFAULT_VERIFICATION_RULES

DEFAULT_POLICY_CODE = "default-commodity-matching"
DEFAULT_POLICY_NAME = "Default Commodity Matching Policy"
DEFAULT_POLICY_DESCRIPTION = "Authoritative platform default matching policy v1 for commodity procurement."

DEFAULT_POLICY_V1_CONFIGURATION: Dict[str, Any] = {
    "dimension_weights": {
        CandidateLane.DIRECT_SUPPLY.value: {
            SignalDimension.SPECIFICATION.value: 45,
            SignalDimension.QUANTITY.value: 10,
            SignalDimension.AVAILABILITY.value: 15,
            SignalDimension.GEOGRAPHY.value: 10,
            SignalDimension.TRUST.value: 15,
            SignalDimension.HISTORY.value: 5,
        },
        CandidateLane.POTENTIAL_SUPPLIER.value: {
            SignalDimension.GEOGRAPHY.value: 40,
            SignalDimension.TRUST.value: 60,
        },
        CandidateLane.BROKER_PATH.value: {
            SignalDimension.GEOGRAPHY.value: 40,
            SignalDimension.TRUST.value: 60,
        },
    }
}


def validate_policy_configuration(configuration: Dict[str, Any]) -> None:
    """
    Validate that matching policy configuration complies with platform invariants.
    Each configured candidate lane must have dimension weights totaling exactly 100.
    """
    if not isinstance(configuration, dict):
        raise InvalidPolicyConfigurationError("Policy configuration must be a dictionary.")

    dimension_weights = configuration.get("dimension_weights") or configuration.get("weights")
    if not dimension_weights or not isinstance(dimension_weights, dict):
        raise InvalidPolicyConfigurationError("Policy configuration must contain 'dimension_weights'.")

    for lane, dims in dimension_weights.items():
        if not isinstance(dims, dict):
            raise InvalidPolicyConfigurationError(f"Dimension weights for lane '{lane}' must be a dictionary.")
        total = Decimal("0")
        for dim, weight in dims.items():
            try:
                dec_w = Decimal(str(weight))
            except Exception as e:
                raise InvalidPolicyConfigurationError(
                    f"Invalid numeric weight for lane '{lane}', dimension '{dim}': {weight}"
                ) from e
            if dec_w < Decimal("0"):
                raise InvalidPolicyConfigurationError(
                    f"Weight for lane '{lane}', dimension '{dim}' cannot be negative: {dec_w}"
                )
            total += dec_w
        if total != Decimal("100"):
            raise InvalidPolicyConfigurationError(
                f"Configured dimension weights for lane '{lane}' total {total}, but must equal exactly 100."
            )


@transaction.atomic
def seed_matching_policy_v1() -> MatchingPolicyVersion:
    """
    Idempotently and deterministically seed Default Published Matching Policy v1.

    Guarantees:
    - Creates 'default-commodity-matching' policy aggregate if missing.
    - Creates version 1 with authoritative lane dimension weights:
        * Direct Supply: Spec 45, Qty 10, Avail 15, Geo 10, Trust 15, History 5
        * Potential Supplier: Geo 40, Trust 60
        * Broker Path: Geo 40, Trust 60
    - Seeds default VerificationMatchingRules under Draft lifecycle before publication.
    - Publishes the policy version to enforce immutability.
    - If version 1 exists with identical semantics: returns cleanly.
    - If version 1 exists with conflicting semantics: raises PolicySeedConflictError.
      Never silently rewrites Published history.
    """
    validate_policy_configuration(DEFAULT_POLICY_V1_CONFIGURATION)

    policy, _ = MatchingPolicy.objects.get_or_create(
        code=DEFAULT_POLICY_CODE,
        defaults={
            "name": DEFAULT_POLICY_NAME,
            "description": DEFAULT_POLICY_DESCRIPTION,
        },
    )

    existing_v1 = MatchingPolicyVersion.objects.filter(policy=policy, version=1).first()
    if existing_v1:
        # Verify structural configuration consistency
        existing_weights = (
            existing_v1.configuration.get("dimension_weights")
            or existing_v1.configuration.get("weights")
        )
        expected_weights = DEFAULT_POLICY_V1_CONFIGURATION["dimension_weights"]

        # Deep comparison of lane weights
        is_conflicting = False
        if not existing_weights or not isinstance(existing_weights, dict):
            is_conflicting = True
        else:
            for lane, exp_dims in expected_weights.items():
                act_dims = existing_weights.get(lane)
                if not act_dims or not isinstance(act_dims, dict):
                    is_conflicting = True
                    break
                for dim, exp_w in exp_dims.items():
                    act_w = act_dims.get(dim)
                    if act_w is None or Decimal(str(act_w)) != Decimal(str(exp_w)):
                        is_conflicting = True
                        break
                if is_conflicting:
                    break

        if is_conflicting:
            raise PolicySeedConflictError(
                f"Existing MatchingPolicyVersion '{policy.code}' v1 has conflicting configuration. "
                f"Existing: {existing_v1.configuration}, Expected: {DEFAULT_POLICY_V1_CONFIGURATION}. "
                "Silent rewriting of Published policy history is prohibited."
            )

        return existing_v1

    # Create Draft v1, populate rules, then publish
    v1 = MatchingPolicyVersion.objects.create(
        policy=policy,
        version=1,
        status=PolicyLifecycleStatus.DRAFT,
        description="Default commodity matching policy v1.",
        configuration=DEFAULT_POLICY_V1_CONFIGURATION,
    )

    # Seed verification rules for v1
    for state, rule_snap in DEFAULT_VERIFICATION_RULES.items():
        VerificationMatchingRule.objects.create(
            policy_version=v1,
            verification_state=state,
            raw_score=rule_snap.raw_score,
            hard_exclude=rule_snap.hard_exclude,
        )

    # Transition to Published immutable status
    v1.status = PolicyLifecycleStatus.PUBLISHED
    v1.save()
    return v1
