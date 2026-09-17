from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from matching.constants import DEFAULT_ENGINE_VERSION
from matching.enums import MatchingAudience, PolicyLifecycleStatus
from matching.fingerprint import compute_fingerprint
from matching.models.policy import MatchingPolicyVersion
from matching.models.run import MatchingRun


def publish_policy_version(policy_version: MatchingPolicyVersion) -> MatchingPolicyVersion:
    """
    Publish a draft policy version, making its configuration permanently immutable.

    Allowed transitions:
        DRAFT -> PUBLISHED
    """
    if policy_version.status != PolicyLifecycleStatus.DRAFT:
        raise ValidationError(
            f"Cannot publish policy version in '{policy_version.status}' status. Only DRAFT versions can be published."
        )
    policy_version.status = PolicyLifecycleStatus.PUBLISHED
    policy_version.save()
    return policy_version


def retire_policy_version(policy_version: MatchingPolicyVersion) -> MatchingPolicyVersion:
    """
    Retire an existing published policy version.

    Allowed transitions:
        PUBLISHED -> RETIRED
    """
    if policy_version.status != PolicyLifecycleStatus.PUBLISHED:
        raise ValidationError(
            f"Cannot retire policy version in '{policy_version.status}' status. Only PUBLISHED versions can be retired."
        )
    policy_version.status = PolicyLifecycleStatus.RETIRED
    policy_version.save()
    return policy_version


@transaction.atomic
def create_matching_run(
    *,
    rfq: Any,
    rfq_version: int,
    audience: str,
    policy_version: MatchingPolicyVersion,
    requesting_organization: Optional[Any] = None,
    requested_by: Optional[Any] = None,
    target_snapshot: Optional[dict] = None,
    engine_version: str = DEFAULT_ENGINE_VERSION,
    input_fingerprint: str = "",
    result_fingerprint: str = "",
) -> MatchingRun:
    """
    Domain service entry point for persisting a new MatchingRun.

    Enforces that:
    - Target RFQ is provided and valid.
    - Policy version is in PUBLISHED lifecycle status.
    - Audience is either BUYER or OPERATOR.
    - Input fingerprint is deterministically computed if not provided.
    """
    if policy_version.status != PolicyLifecycleStatus.PUBLISHED:
        raise ValidationError(
            f"Matching runs can only be created against a PUBLISHED policy version (current status: '{policy_version.status}')."
        )

    if audience not in MatchingAudience.values:
        raise ValidationError(f"Invalid audience '{audience}'. Must be one of: {', '.join(MatchingAudience.values)}.")

    snapshot = target_snapshot or {}
    if not input_fingerprint and snapshot:
        input_fingerprint = compute_fingerprint(
            {
                "target_snapshot": snapshot,
                "policy_version": policy_version.version,
                "engine_version": engine_version,
                "audience": audience,
            }
        )

    run = MatchingRun(
        rfq=rfq,
        rfq_version=rfq_version,
        audience=audience,
        requesting_organization=requesting_organization,
        requested_by=requested_by,
        policy_version=policy_version,
        engine_version=engine_version,
        target_snapshot=snapshot,
        input_fingerprint=input_fingerprint,
        result_fingerprint=result_fingerprint,
    )
    run.full_clean()
    run.save()
    return run
