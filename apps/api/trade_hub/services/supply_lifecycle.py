from typing import Any
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from commodities.models import CommoditySchemaVersion
from commodities.services import validate_commodity_payload
from organizations.models import OrganizationCapability
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    StaleVersionError,
    SupplyListingNotFoundError,
    SupplyListingValidationError,
)
from trade_hub.models.supply import SupplyListing, SupplyListingStatus


def _extract_supply_id(supply_or_id: Any) -> uuid.UUID:
    if isinstance(supply_or_id, SupplyListing):
        return supply_or_id.pk
    if isinstance(supply_or_id, uuid.UUID):
        return supply_or_id
    if isinstance(supply_or_id, str):
        try:
            return uuid.UUID(supply_or_id)
        except (ValueError, AttributeError) as exc:
            raise SupplyListingNotFoundError(
                f"Invalid supply listing ID: '{supply_or_id}'"
            ) from exc
    raise SupplyListingNotFoundError(f"Invalid supply listing identifier: '{supply_or_id}'")


def _validate_expected_version(supply: SupplyListing, expected_version: Any) -> None:
    if expected_version is None:
        raise InvalidVersionError("expected_version is required.")
    if type(expected_version) is not int or isinstance(expected_version, bool):
        raise InvalidVersionError(
            f"expected_version must be an integer, got {type(expected_version).__name__}."
        )
    if expected_version < 1:
        raise InvalidVersionError("expected_version must be a positive integer.")
    if supply.version != expected_version:
        raise StaleVersionError(
            f"Stale version error: SupplyListing version is {supply.version}, expected {expected_version}."
        )


def _lock_supply(supply_id: uuid.UUID) -> SupplyListing:
    try:
        return (
            SupplyListing.objects.select_for_update()
            .select_related("commodity", "schema_version", "organization")
            .get(pk=supply_id)
        )
    except SupplyListing.DoesNotExist as exc:
        raise SupplyListingNotFoundError(
            f"Supply listing with id '{supply_id}' does not exist."
        ) from exc


class SupplyLifecycleService:
    """Authoritative domain service governing Supply Listing lifecycle state transitions."""

    @staticmethod
    @transaction.atomic
    def activate(
        supply_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> SupplyListing:
        """
        Transition a Supply Listing from Draft to Active.

        Validates expected_version under exclusive row lock, verifies activation
        prerequisites (supplier capability, active commodity, published schema version,
        exact dynamic specifications, positive quantity, valid availability window),
        advances version, records activated_at timestamp, and persists changes.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        _validate_expected_version(supply, expected_version)

        if supply.status != SupplyListingStatus.DRAFT:
            raise InvalidTransitionError(
                f"Cannot activate supply listing in status '{supply.status}'. "
                "Only draft listings can be activated."
            )

        # 1. Supplier eligibility
        if not supply.organization.is_active:
            raise SupplyListingValidationError(
                "Cannot activate supply listing: owning supplier organization is inactive."
            )

        has_supplier_cap = OrganizationCapability.objects.filter(
            organization=supply.organization,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        ).exists()
        if not has_supplier_cap:
            raise SupplyListingValidationError(
                f"Cannot activate supply listing: organization '{supply.organization.name}' "
                "lacks Supplier capability."
            )

        # 2. Commodity and schema version prerequisites
        if not supply.commodity.is_active:
            raise SupplyListingValidationError(
                "Cannot activate supply listing: referenced commodity is inactive."
            )

        if supply.schema_version.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
            raise SupplyListingValidationError(
                "Cannot activate supply listing: referenced commodity schema version is not published."
            )

        if supply.schema_version.commodity_id != supply.commodity_id:
            raise SupplyListingValidationError(
                "Cannot activate supply listing: schema version does not belong to referenced commodity."
            )

        # 3. Dynamic specifications validation against exact schema version
        try:
            validate_commodity_payload(supply.schema_version, supply.specifications)
        except ValidationError as exc:
            errors = []
            if hasattr(exc, "params") and isinstance(exc.params, dict):
                errors = exc.params.get("errors", [])
            err_msg = exc.message if hasattr(exc, "message") else str(exc)
            raise SupplyListingValidationError(
                f"Activation validation failed: {err_msg}",
                errors=errors,
            ) from exc

        # 4. Quantity and availability window validation
        if supply.quantity is None or supply.quantity <= 0:
            raise SupplyListingValidationError(
                "Cannot activate supply listing: quantity must be greater than zero."
            )

        if supply.availability_window_start and supply.availability_window_end:
            if supply.availability_window_end < supply.availability_window_start:
                raise SupplyListingValidationError(
                    "Cannot activate supply listing: availability window end must be on or after start."
                )

        supply.status = SupplyListingStatus.ACTIVE
        supply.activated_at = timezone.now()
        supply.version += 1
        supply.save(update_fields=["status", "activated_at", "version", "updated_at"])
        return supply

    @staticmethod
    @transaction.atomic
    def close(
        supply_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> SupplyListing:
        """
        Transition a Supply Listing from Draft or Active to Closed.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        _validate_expected_version(supply, expected_version)

        if supply.status not in (SupplyListingStatus.DRAFT, SupplyListingStatus.ACTIVE):
            raise InvalidTransitionError(
                f"Cannot close supply listing in status '{supply.status}'. "
                "Only draft or active listings can be closed."
            )

        supply.status = SupplyListingStatus.CLOSED
        supply.closed_at = timezone.now()
        supply.version += 1
        supply.save(update_fields=["status", "closed_at", "version", "updated_at"])
        return supply

    @staticmethod
    @transaction.atomic
    def expire(
        supply_or_id: Any,
        *,
        expected_version: Any,
        actor: Any = None,
    ) -> SupplyListing:
        """
        Transition a Supply Listing from Active to Expired.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        _validate_expected_version(supply, expected_version)

        if supply.status != SupplyListingStatus.ACTIVE:
            raise InvalidTransitionError(
                f"Cannot expire supply listing in status '{supply.status}'. "
                "Only active listings can be expired."
            )

        supply.status = SupplyListingStatus.EXPIRED
        supply.expired_at = timezone.now()
        supply.version += 1
        supply.save(update_fields=["status", "expired_at", "version", "updated_at"])
        return supply


# Module-level convenience functions
activate_supply = SupplyLifecycleService.activate
close_supply = SupplyLifecycleService.close
expire_supply = SupplyLifecycleService.expire
