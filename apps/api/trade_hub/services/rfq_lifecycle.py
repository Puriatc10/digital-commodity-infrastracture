import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from commodities.models import CommoditySchemaVersion
from commodities.services import validate_commodity_payload
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    PublicationValidationError,
    RFQNotFoundError,
    StaleVersionError,
)
from trade_hub.models import RFQ, RFQStatus


def _extract_rfq_id(rfq_or_id: Any) -> uuid.UUID:
    if isinstance(rfq_or_id, RFQ):
        return rfq_or_id.pk
    if isinstance(rfq_or_id, uuid.UUID):
        return rfq_or_id
    if isinstance(rfq_or_id, str):
        try:
            return uuid.UUID(rfq_or_id)
        except (ValueError, AttributeError) as exc:
            raise RFQNotFoundError(f"Invalid RFQ ID: '{rfq_or_id}'") from exc
    raise RFQNotFoundError(f"Invalid RFQ identifier: '{rfq_or_id}'")


def _validate_expected_version(rfq: RFQ, expected_version: Any) -> None:
    if expected_version is None:
        raise InvalidVersionError("expected_version is required.")
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if rfq.version != expected_version:
        raise StaleVersionError(
            f"Stale version error: RFQ version is {rfq.version}, expected {expected_version}."
        )


def _lock_rfq(rfq_id: uuid.UUID) -> RFQ:
    try:
        return (
            RFQ.objects.select_for_update()
            .select_related("commodity", "schema_version", "organization")
            .get(pk=rfq_id)
        )
    except RFQ.DoesNotExist as exc:
        raise RFQNotFoundError(f"RFQ with id '{rfq_id}' does not exist.") from exc


class RFQLifecycleService:
    """Authoritative domain service governing RFQ lifecycle state transitions."""

    @staticmethod
    @transaction.atomic
    def publish(rfq_or_id: Any, *, expected_version: Any, actor: Any = None) -> RFQ:
        """
        Transition an RFQ from Draft to Published.

        Validates expected_version under exclusive row lock, verifies publication
        prerequisites against the RFQ's stored schema version, advances version,
        records publication timestamp, and persists changes.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        rfq = _lock_rfq(rfq_id)

        _validate_expected_version(rfq, expected_version)

        if rfq.status != RFQStatus.DRAFT:
            raise InvalidTransitionError(
                f"Cannot publish RFQ in status '{rfq.status}'. Only draft RFQs can be published."
            )

        # Validate publication prerequisites
        if not rfq.commodity.is_active:
            raise PublicationValidationError("Cannot publish RFQ: referenced commodity is inactive.")

        if rfq.schema_version.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
            raise PublicationValidationError(
                "Cannot publish RFQ: referenced commodity schema version is not published."
            )

        # Validate dynamic specifications against the RFQ's stored schema version
        try:
            validate_commodity_payload(rfq.schema_version, rfq.specifications)
        except ValidationError as exc:
            errors = []
            if hasattr(exc, "params") and isinstance(exc.params, dict):
                errors = exc.params.get("errors", [])
            err_msg = exc.message if hasattr(exc, "message") else str(exc)
            raise PublicationValidationError(
                f"Publication validation failed: {err_msg}",
                errors=errors,
            ) from exc

        rfq.status = RFQStatus.PUBLISHED
        rfq.published_at = timezone.now()
        rfq.version += 1
        rfq.save(update_fields=["status", "published_at", "version", "updated_at"])
        return rfq

    @staticmethod
    @transaction.atomic
    def cancel(
        rfq_or_id: Any,
        *,
        expected_version: Any,
        reason: str = "",
        actor: Any = None,
    ) -> RFQ:
        """
        Transition an RFQ to Cancelled.

        Permitted from Draft, Published, or Collecting Offers. When cancelling a Published
        or Collecting Offers RFQ, a non-empty reason is strictly required.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        rfq = _lock_rfq(rfq_id)

        _validate_expected_version(rfq, expected_version)

        if rfq.status not in (RFQStatus.DRAFT, RFQStatus.PUBLISHED):
            raise InvalidTransitionError(
                f"Cannot cancel RFQ in status '{rfq.status}'. Only draft or published RFQs can be cancelled."
            )

        clean_reason = str(reason).strip() if reason is not None else ""
        if rfq.status == RFQStatus.PUBLISHED and not clean_reason:
            raise InvalidTransitionError(
                "Cancellation of a published RFQ requires a non-empty cancellation reason."
            )

        rfq.status = RFQStatus.CANCELLED
        rfq.cancelled_at = timezone.now()
        rfq.cancellation_reason = clean_reason
        rfq.version += 1
        rfq.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancellation_reason",
                "version",
                "updated_at",
            ]
        )
        return rfq

    @staticmethod
    @transaction.atomic
    def close(rfq_or_id: Any, *, expected_version: Any, actor: Any = None) -> RFQ:
        """
        Transition an RFQ from Published to Closed.

        Permitted only from Published.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        rfq = _lock_rfq(rfq_id)

        _validate_expected_version(rfq, expected_version)

        if rfq.status != RFQStatus.PUBLISHED:
            raise InvalidTransitionError(
                f"Cannot close RFQ in status '{rfq.status}'. Only published RFQs can be closed."
            )


        rfq.status = RFQStatus.CLOSED
        rfq.closed_at = timezone.now()
        rfq.version += 1
        rfq.save(update_fields=["status", "closed_at", "version", "updated_at"])
        return rfq

    @staticmethod
    def start_collecting_offers(rfq_or_id: Any, *, actor: Any = None) -> RFQ:
        """
        Transition an RFQ from Published to Collecting Offers.

        Authoritative lifecycle transition invoked when the first valid offer is
        successfully submitted against a Published RFQ.
        Advances RFQ version and updates status.
        Idempotent if the RFQ is already in Collecting Offers.
        """
        if isinstance(rfq_or_id, RFQ):
            rfq = rfq_or_id
        else:
            rfq_id = _extract_rfq_id(rfq_or_id)
            rfq = _lock_rfq(rfq_id)

        if rfq.status == RFQStatus.COLLECTING_OFFERS:
            return rfq

        if rfq.status != RFQStatus.PUBLISHED:
            raise InvalidTransitionError(
                f"Cannot transition RFQ to Collecting Offers from status '{rfq.status}'. "
                f"Only Published RFQs can transition to Collecting Offers."
            )

        rfq.status = RFQStatus.COLLECTING_OFFERS
        rfq.version += 1
        rfq.save(update_fields=["status", "version", "updated_at"])
        return rfq

    @staticmethod
    def start_negotiating(rfq_or_id: Any, *, actor: Any = None) -> RFQ:
        """
        Transition an RFQ from Collecting Offers to Negotiating (Epic 8 Contract §14, §56).

        Authoritative lifecycle transition invoked when a formal RevisionRequest
        is opened against an offer on the RFQ.
        Advances RFQ version and updates status.
        Idempotent if the RFQ is already in Negotiating.
        Rejects if RFQ is in a terminal status (Closed, Cancelled, Awarded)
        or other non-negotiating status (Draft, Published).
        """
        if isinstance(rfq_or_id, RFQ):
            rfq = rfq_or_id
        else:
            rfq_id = _extract_rfq_id(rfq_or_id)
            rfq = _lock_rfq(rfq_id)

        if rfq.status == RFQStatus.NEGOTIATING:
            return rfq

        if rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
            raise InvalidTransitionError(
                f"Cannot transition terminal RFQ in status '{rfq.status}' to Negotiating."
            )

        if rfq.status != RFQStatus.COLLECTING_OFFERS:
            raise InvalidTransitionError(
                f"Cannot transition RFQ to Negotiating from status '{rfq.status}'. "
                f"Only RFQs in Collecting Offers can transition to Negotiating."
            )

        rfq.status = RFQStatus.NEGOTIATING
        rfq.version += 1
        rfq.save(update_fields=["status", "version", "updated_at"])
        return rfq

    @staticmethod
    def award_rfq(rfq_or_id: Any, *, actor: Any = None) -> RFQ:
        """
        Transition an RFQ to Awarded (Epic 8 Contract §14, §68).

        Authoritative lifecycle transition invoked when an Award is finalized.
        Advances RFQ version and updates status to AWARDED.
        Permitted only from Collecting Offers or Negotiating.
        Rejects terminal statuses (Closed, Cancelled, Awarded) and other statuses (Draft, Published).
        """
        if isinstance(rfq_or_id, RFQ):
            rfq = rfq_or_id
        else:
            rfq_id = _extract_rfq_id(rfq_or_id)
            rfq = _lock_rfq(rfq_id)

        if rfq.status in (RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED):
            raise InvalidTransitionError(
                f"Cannot transition terminal RFQ in status '{rfq.status}' to Awarded."
            )

        if rfq.status not in (RFQStatus.COLLECTING_OFFERS, RFQStatus.NEGOTIATING):
            raise InvalidTransitionError(
                f"Cannot transition RFQ to Awarded from status '{rfq.status}'. "
                f"Only RFQs in Collecting Offers or Negotiating can transition to Awarded."
            )

        rfq.status = RFQStatus.AWARDED
        rfq.version += 1
        rfq.save(update_fields=["status", "version", "updated_at"])
        return rfq


# Module-level convenience functions
publish_rfq = RFQLifecycleService.publish
cancel_rfq = RFQLifecycleService.cancel
close_rfq = RFQLifecycleService.close
start_collecting_offers = RFQLifecycleService.start_collecting_offers
start_negotiating = RFQLifecycleService.start_negotiating
award_rfq = RFQLifecycleService.award_rfq

