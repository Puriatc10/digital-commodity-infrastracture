from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from deals.exceptions import (
    AttributionAlreadyResolvedError,
    AttributionNotFoundError,
    DealPermissionDeniedError,
    DealValidationError,
    StaleVersionError,
)
from deals.models import (
    DealAttribution,
    DealAttributionChannel,
    DealAttributionResolutionMethod,
    DealAttributionStatus,
)
from identity.models import SystemRoleAssignment


def _is_operator_or_admin(user: Any) -> bool:
    """Verify if user holds OPERATOR or ADMIN system role authority."""
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


@transaction.atomic
def manual_resolve_deal_attribution(
    deal_id: Any,
    *,
    actor: Any,
    primary_channel: str,
    reason: str,
    expected_version: Optional[int] = None,
) -> DealAttribution:
    """
    Authoritative manual resolution action for a PENDING DealAttribution (Contract §47, §101, T0903).

    Responsibilities:
    1. Verify actor has Operator or Product Admin system authority (conferred strictly by SystemRoleAssignment).
       Buyer, Supplier, Broker, Viewer, Django staff-only, superuser-only, and anonymous are denied.
    2. Lock DealAttribution under exclusive row lock (select_for_update).
    3. Verify current status is PENDING. If already RESOLVED, reject with AttributionAlreadyResolvedError (409).
    4. If expected_version provided, verify optimistic concurrency version matching.
    5. Validate primary_channel is one of the 5 canonical roadmap categories.
    6. Validate non-empty explanation reason.
    7. Mutate attribution record:
       status = RESOLVED
       primary_channel = primary_channel
       resolution_method = MANUAL
       resolved_by = actor
       resolved_at = timezone.now()
       resolution_reason = reason.strip()
       version += 1
    8. Commit atomically.
    """
    if not _is_operator_or_admin(actor):
        raise DealPermissionDeniedError(
            "Only Platform Operators and Product Admins may manually resolve deal attribution."
        )

    if not reason or not reason.strip():
        raise DealValidationError("Resolution reason is strictly required for manual attribution resolution.")

    if primary_channel not in DealAttributionChannel.values:
        raise DealValidationError(
            f"Invalid primary_channel '{primary_channel}'. Must be one of: {', '.join(DealAttributionChannel.values)}."
        )

    if expected_version is not None:
        if type(expected_version) is not int or isinstance(expected_version, bool) or expected_version < 1:
            raise DealValidationError(
                f"expected_version must be a positive integer, got {expected_version}."
            )

    try:
        attribution = (
            DealAttribution.objects.select_for_update()
            .select_related("deal")
            .get(deal_id=deal_id)
        )
    except DealAttribution.DoesNotExist as exc:
        raise AttributionNotFoundError(
            f"DealAttribution does not exist for Deal '{deal_id}'."
        ) from exc

    if attribution.status == DealAttributionStatus.RESOLVED:
        raise AttributionAlreadyResolvedError(
            f"Attribution for Deal '{deal_id}' has already been resolved and is immutable."
        )

    if expected_version is not None and attribution.version != expected_version:
        raise StaleVersionError(
            f"Stale version error: DealAttribution version is {attribution.version}, expected {expected_version}."
        )

    now = timezone.now()
    attribution.status = DealAttributionStatus.RESOLVED
    attribution.primary_channel = primary_channel
    attribution.resolution_method = DealAttributionResolutionMethod.MANUAL
    attribution.resolved_by = actor
    attribution.resolved_at = now
    attribution.resolution_reason = reason.strip()
    attribution.version += 1
    attribution.save()

    return attribution
