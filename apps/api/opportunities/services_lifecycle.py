from typing import Any
import uuid

from django.db import transaction
from django.utils import timezone

from opportunities.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    OpportunityNotFoundError,
    ReservedTransitionError,
    StaleVersionError,
)
from opportunities.models import Opportunity, OpportunityStatus

TERMINAL_STATUSES = frozenset(
    {
        OpportunityStatus.CONVERTED,
        OpportunityStatus.REJECTED,
        OpportunityStatus.LOST,
        OpportunityStatus.EXPIRED,
    }
)


def _extract_opportunity_id(opportunity_or_id: Any) -> uuid.UUID:
    """Resolves an Opportunity instance, UUID, or string identifier to an authoritative UUID."""
    if isinstance(opportunity_or_id, Opportunity):
        return opportunity_or_id.pk
    if isinstance(opportunity_or_id, uuid.UUID):
        return opportunity_or_id
    if isinstance(opportunity_or_id, str):
        try:
            return uuid.UUID(opportunity_or_id)
        except (ValueError, AttributeError):
            # Attempt lookup by canonical human-readable identifier (e.g. OPP-2026-000124)
            opp = Opportunity.objects.filter(identifier=opportunity_or_id.strip()).only("id").first()
            if opp is not None:
                return opp.pk
            raise OpportunityNotFoundError(f"Invalid Opportunity identifier: '{opportunity_or_id}'")
    raise OpportunityNotFoundError(f"Invalid Opportunity identifier: '{opportunity_or_id}'")


def _validate_expected_version(opportunity: Opportunity, expected_version: Any) -> None:
    """Validates expected_version under row lock for optimistic concurrency control."""
    if expected_version is None:
        raise InvalidVersionError("expected_version is required.")
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if opportunity.version != expected_version:
        raise StaleVersionError(
            f"Stale version error: Opportunity version is {opportunity.version}, expected {expected_version}."
        )


def _lock_opportunity(opportunity_id: uuid.UUID) -> Opportunity:
    """Acquires an exclusive row-level lock on the persisted Opportunity aggregate."""
    try:
        return (
            Opportunity.objects.select_for_update()
            .get(pk=opportunity_id)
        )
    except Opportunity.DoesNotExist as exc:
        raise OpportunityNotFoundError(f"Opportunity with id '{opportunity_id}' does not exist.") from exc


class OpportunityLifecycleService:
    """Authoritative domain service governing Opportunity lifecycle state transitions."""

    @staticmethod
    @transaction.atomic
    def mark_contacted(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an Opportunity from Captured to Contacted.

        Validates expected_version under exclusive row lock, advances version,
        records contacted timestamp, and persists changes.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot mark Opportunity in terminal status '{opp.status}' as contacted."
            )

        if opp.status != OpportunityStatus.CAPTURED:
            raise InvalidTransitionError(
                f"Cannot mark Opportunity in status '{opp.status}' as contacted. Only Captured opportunities can transition to Contacted."
            )

        opp.status = OpportunityStatus.CONTACTED
        opp.contacted_at = timezone.now()
        opp.version += 1
        opp.save(update_fields=["status", "contacted_at", "version", "updated_at"])
        return opp

    @staticmethod
    @transaction.atomic
    def qualify(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an Opportunity to Qualified.

        Permitted from Captured or Contacted. Advances version, records
        qualified timestamp, and persists changes.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot qualify Opportunity in terminal status '{opp.status}'."
            )

        if opp.status not in (OpportunityStatus.CAPTURED, OpportunityStatus.CONTACTED):
            raise InvalidTransitionError(
                f"Cannot qualify Opportunity in status '{opp.status}'. Only Captured or Contacted opportunities can be qualified."
            )

        opp.status = OpportunityStatus.QUALIFIED
        opp.qualified_at = timezone.now()
        opp.version += 1
        opp.save(update_fields=["status", "qualified_at", "version", "updated_at"])
        return opp

    @staticmethod
    @transaction.atomic
    def start_matching(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition a Qualified Opportunity to Matching.

        Permitted only from Qualified.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot move Opportunity in terminal status '{opp.status}' to Matching."
            )

        if opp.status != OpportunityStatus.QUALIFIED:
            raise InvalidTransitionError(
                f"Cannot move Opportunity in status '{opp.status}' to Matching. Only Qualified opportunities can enter Matching."
            )

        opp.status = OpportunityStatus.MATCHING
        opp.version += 1
        opp.save(update_fields=["status", "version", "updated_at"])
        return opp

    @staticmethod
    @transaction.atomic
    def put_on_hold(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        reason: str,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an active Opportunity to On Hold.

        Permitted from Captured, Contacted, Qualified, or Matching.
        Requires a non-empty operational reason. Stores the pre-hold status
        to ensure safe, authoritative resumption.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot put Opportunity in terminal status '{opp.status}' on hold."
            )

        if opp.status == OpportunityStatus.ON_HOLD:
            raise InvalidTransitionError("Opportunity is already on hold.")

        clean_reason = str(reason).strip() if reason is not None else ""
        if not clean_reason:
            raise InvalidTransitionError("A non-empty reason is strictly required when putting an Opportunity on hold.")

        opp.status_before_hold = opp.status
        opp.status = OpportunityStatus.ON_HOLD
        opp.held_at = timezone.now()
        opp.hold_reason = clean_reason
        opp.version += 1
        opp.save(
            update_fields=[
                "status",
                "status_before_hold",
                "held_at",
                "hold_reason",
                "version",
                "updated_at",
            ]
        )
        return opp

    @staticmethod
    @transaction.atomic
    def resume(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> Opportunity:
        """
        Resume an Opportunity from On Hold back to its pre-hold status.

        Authoritatively restores the persisted status_before_hold.
        Arbitrary client-supplied target status is strictly prohibited.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status != OpportunityStatus.ON_HOLD:
            raise InvalidTransitionError(
                f"Cannot resume Opportunity in status '{opp.status}'. Only On Hold opportunities can be resumed."
            )

        target_status = opp.status_before_hold
        if not target_status or target_status not in (
            OpportunityStatus.CAPTURED,
            OpportunityStatus.CONTACTED,
            OpportunityStatus.QUALIFIED,
            OpportunityStatus.MATCHING,
        ):
            target_status = OpportunityStatus.CAPTURED

        opp.status = target_status
        opp.status_before_hold = ""
        opp.version += 1
        opp.save(update_fields=["status", "status_before_hold", "version", "updated_at"])
        return opp

    @staticmethod
    @transaction.atomic
    def reject(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        reason: str,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an Opportunity to Rejected (Terminal).

        Permitted from any non-terminal status (Captured, Contacted, Qualified, Matching, On Hold).
        Requires a non-empty rejection reason.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot reject Opportunity in terminal status '{opp.status}'."
            )

        clean_reason = str(reason).strip() if reason is not None else ""
        if not clean_reason:
            raise InvalidTransitionError("A non-empty reason is strictly required when rejecting an Opportunity.")

        opp.status = OpportunityStatus.REJECTED
        opp.rejected_at = timezone.now()
        opp.rejection_reason = clean_reason
        opp.status_before_hold = ""
        opp.version += 1
        opp.save(
            update_fields=[
                "status",
                "rejected_at",
                "rejection_reason",
                "status_before_hold",
                "version",
                "updated_at",
            ]
        )
        return opp

    @staticmethod
    @transaction.atomic
    def mark_lost(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        reason: str,
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an Opportunity to Lost (Terminal).

        Permitted from any non-terminal status (Captured, Contacted, Qualified, Matching, On Hold).
        Requires a non-empty lost reason.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot mark Opportunity in terminal status '{opp.status}' as lost."
            )

        clean_reason = str(reason).strip() if reason is not None else ""
        if not clean_reason:
            raise InvalidTransitionError("A non-empty reason is strictly required when marking an Opportunity as lost.")

        opp.status = OpportunityStatus.LOST
        opp.lost_at = timezone.now()
        opp.lost_reason = clean_reason
        opp.status_before_hold = ""
        opp.version += 1
        opp.save(
            update_fields=[
                "status",
                "lost_at",
                "lost_reason",
                "status_before_hold",
                "version",
                "updated_at",
            ]
        )
        return opp

    @staticmethod
    @transaction.atomic
    def expire(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        reason: str = "",
        actor: Any = None,
    ) -> Opportunity:
        """
        Transition an Opportunity to Expired (Terminal).

        Permitted from any non-terminal status (Captured, Contacted, Qualified, Matching, On Hold).
        Reason is optional.
        """
        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot expire Opportunity in terminal status '{opp.status}'."
            )

        clean_reason = str(reason).strip() if reason is not None else ""

        opp.status = OpportunityStatus.EXPIRED
        opp.expired_at = timezone.now()
        opp.expiration_reason = clean_reason
        opp.status_before_hold = ""
        opp.version += 1
        opp.save(
            update_fields=[
                "status",
                "expired_at",
                "expiration_reason",
                "status_before_hold",
                "version",
                "updated_at",
            ]
        )
        return opp

    @staticmethod
    @transaction.atomic
    def convert(
        opportunity_or_id: Any,
        *,
        expected_version: Any,
        conversion_target: Any = None,
        actor: Any = None,
    ) -> Opportunity:
        """
        Authoritative conversion into RFQ or Supply Listing.

        Critical Invariant:
        Direct conversion without an authoritative conversion target entity
        (T0609 RFQ / T0610 Supply Listing) is strictly forbidden.
        """
        if conversion_target is None:
            raise ReservedTransitionError(
                "Direct transition to Converted is strictly reserved. "
                "Opportunities can only be converted through authoritative conversion actions (T0609 RFQ / T0610 Supply Listing)."
            )

        opp_id = _extract_opportunity_id(opportunity_or_id)
        opp = _lock_opportunity(opp_id)

        _validate_expected_version(opp, expected_version)

        if opp.status in TERMINAL_STATUSES:
            raise InvalidTransitionError(
                f"Cannot convert Opportunity in terminal status '{opp.status}'."
            )

        if opp.status not in (OpportunityStatus.QUALIFIED, OpportunityStatus.MATCHING):
            raise InvalidTransitionError(
                f"Cannot convert Opportunity in status '{opp.status}'. Only Qualified or Matching opportunities can be converted."
            )

        opp.status = OpportunityStatus.CONVERTED
        opp.converted_at = timezone.now()
        opp.status_before_hold = ""
        opp.version += 1
        opp.save(
            update_fields=[
                "status",
                "converted_at",
                "status_before_hold",
                "version",
                "updated_at",
            ]
        )
        return opp


# Module-level convenience aliases
mark_opportunity_contacted = OpportunityLifecycleService.mark_contacted
qualify_opportunity = OpportunityLifecycleService.qualify
start_opportunity_matching = OpportunityLifecycleService.start_matching
put_opportunity_on_hold = OpportunityLifecycleService.put_on_hold
resume_opportunity = OpportunityLifecycleService.resume
reject_opportunity = OpportunityLifecycleService.reject
mark_opportunity_lost = OpportunityLifecycleService.mark_lost
expire_opportunity = OpportunityLifecycleService.expire
convert_opportunity = OpportunityLifecycleService.convert
