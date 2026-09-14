from decimal import Decimal
from typing import Any
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from commodities.services import validate_commodity_payload
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.exceptions import (
    InvalidTransitionError,
    InvalidVersionError,
    SpecificationValidationError,
    StaleVersionError,
    SupplyListingNotFoundError,
    SupplyListingPermissionDeniedError,
)
from trade_hub.models.supply import (
    SupplyListing,
    SupplyListingStatus,
    SupplyListingVisibility,
)
from trade_hub.services.supply_lifecycle import (
    activate_supply as lifecycle_activate_supply,
    close_supply as lifecycle_close_supply,
)
from trade_hub.services.visibility_service import (
    has_global_visibility,
    resolve_authoritative_organization,
)


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


def is_operator_or_admin(user: Any) -> bool:
    """Check if user holds OPERATOR or ADMIN system role."""
    return has_global_visibility(user)


def can_manage_supply_listing(
    user: Any, listing: SupplyListing, organization_hint: Any = None
) -> bool:
    """
    Check if the user is authorized to edit, activate, or close the supply listing.
    Allowed:
    - Platform Operator or Product Admin (via SystemRoleAssignment).
    - Owner or Manager of the listing's owning Supplier organization.
    Denied:
    - Member or Viewer of the listing's owning organization.
    - Foreign organizations / competitors.
    - Organizations lacking Supplier capability.
    - Django staff/superuser alone without system roles.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_operator_or_admin(user):
        return True

    current_org = resolve_authoritative_organization(user, organization_hint)
    if current_org is None or current_org.pk != listing.organization_id:
        return False

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id=listing.organization_id,
        is_active=True,
        organization__is_active=True,
    ).first()
    if not membership:
        return False

    return membership.role in (
        OrganizationMembership.OrganizationRole.OWNER,
        OrganizationMembership.OrganizationRole.MANAGER,
    )


def validate_specifications_payload(
    schema_version: CommoditySchemaVersion, payload: dict
) -> None:
    """
    Validates dynamic specifications payload against the exact CommoditySchemaVersion.
    Translates Django ValidationError into domain SpecificationValidationError with structured errors.
    """
    try:
        validate_commodity_payload(schema_version, payload)
    except ValidationError as exc:
        errors = []
        if hasattr(exc, "params") and isinstance(exc.params, dict):
            errors = exc.params.get("errors", [])
        err_msg = exc.message if hasattr(exc, "message") else str(exc)
        raise SpecificationValidationError(
            f"Dynamic specification validation failed: {err_msg}",
            errors=errors,
        ) from exc


class SupplyService:
    """Authoritative domain service governing Supply Listing operations (create, update, activate, close)."""

    @staticmethod
    @transaction.atomic
    def create_draft(
        user: Any,
        data: dict,
        *,
        organization_hint: Any = None,
    ) -> SupplyListing:
        """
        Create a new Draft Supply Listing.
        - Enforces Supplier capability and Owner/Manager role (or Operator on-behalf).
        - Enforces active Commodity and published Schema Version belonging to that Commodity.
        - Validates dynamic specifications if provided.
        - Strictly prevents mass-assignment of status, version, timestamps, or supplier authority.
        """
        if not user or not getattr(user, "is_authenticated", False):
            raise SupplyListingPermissionDeniedError("Authentication required.")

        operator_flag = is_operator_or_admin(user)

        if operator_flag:
            target_org_id = data.get("organization_id") or organization_hint
            if not target_org_id:
                current_org = resolve_authoritative_organization(user, None)
                if current_org:
                    target_org_id = current_org.pk
                else:
                    raise ValidationError(
                        {"organization_id": "Target supplier organization must be specified for operator actions."}
                    )

            try:
                supplier_org = Organization.objects.get(pk=target_org_id, is_active=True)
            except (Organization.DoesNotExist, ValueError):
                raise ValidationError(
                    {"organization_id": "Target organization does not exist or is inactive."}
                )

            user_membership = OrganizationMembership.objects.filter(
                user=user,
                organization=supplier_org,
                is_active=True,
            ).first()
            if user_membership:
                operator_flag = False
        else:
            supplier_org = resolve_authoritative_organization(user, organization_hint)
            if supplier_org is None:
                raise SupplyListingPermissionDeniedError(
                    "No active organization context found for user."
                )

            membership = OrganizationMembership.objects.filter(
                user=user,
                organization=supplier_org,
                is_active=True,
                organization__is_active=True,
            ).first()
            if not membership or membership.role not in (
                OrganizationMembership.OrganizationRole.OWNER,
                OrganizationMembership.OrganizationRole.MANAGER,
            ):
                raise SupplyListingPermissionDeniedError(
                    "Only Organization Owner or Manager can create supply listings."
                )

        # Enforce Supplier capability on target organization
        has_supplier_capability = OrganizationCapability.objects.filter(
            organization=supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        ).exists()
        if not has_supplier_capability:
            raise SupplyListingPermissionDeniedError(
                f"Organization '{supplier_org.name}' lacks Supplier capability."
            )

        # Resolve Commodity
        commodity_id = data.get("commodity_id")
        if not commodity_id:
            raise ValidationError({"commodity_id": "commodity_id is required."})
        try:
            commodity = CommodityDefinition.objects.get(pk=commodity_id, is_active=True)
        except (CommodityDefinition.DoesNotExist, ValueError):
            raise ValidationError(
                {"commodity_id": "Referenced commodity does not exist or is inactive."}
            )

        # Resolve Schema Version
        schema_version_id = data.get("schema_version_id")
        if not schema_version_id:
            raise ValidationError({"schema_version_id": "schema_version_id is required."})
        try:
            schema_version = CommoditySchemaVersion.objects.get(pk=schema_version_id)
        except (CommoditySchemaVersion.DoesNotExist, ValueError):
            raise ValidationError(
                {"schema_version_id": "Referenced commodity schema version does not exist."}
            )

        if schema_version.commodity_id != commodity.id:
            raise ValidationError(
                {"schema_version_id": "Schema version does not belong to the referenced commodity."}
            )

        if schema_version.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
            raise ValidationError(
                {"schema_version_id": "Referenced commodity schema version must be published."}
            )

        # Dynamic Specifications
        specifications = data.get("specifications") or {}
        if not isinstance(specifications, dict):
            raise ValidationError({"specifications": "Specifications must be an object."})

        if specifications:
            validate_specifications_payload(schema_version, specifications)

        # Commercial & Supply terms validation
        quantity = data.get("quantity")
        if quantity is None:
            raise ValidationError({"quantity": "quantity is required."})
        try:
            quantity_decimal = Decimal(str(quantity))
            if quantity_decimal <= 0:
                raise ValidationError({"quantity": "Quantity must be greater than zero."})
        except Exception:
            raise ValidationError({"quantity": "Invalid quantity."})

        indicative_price = data.get("indicative_price")
        indicative_price_decimal = None
        if indicative_price is not None and str(indicative_price).strip() != "":
            try:
                indicative_price_decimal = Decimal(str(indicative_price))
                if indicative_price_decimal < 0:
                    raise ValidationError(
                        {"indicative_price": "Indicative price must be non-negative."}
                    )
            except Exception:
                raise ValidationError({"indicative_price": "Invalid indicative price."})

        availability_window_start = data.get("availability_window_start")
        availability_window_end = data.get("availability_window_end")
        if availability_window_start and availability_window_end:
            if availability_window_end < availability_window_start:
                raise ValidationError(
                    {
                        "availability_window_end": (
                            "Availability window end must be on or after availability window start."
                        )
                    }
                )

        visibility = data.get("visibility", SupplyListingVisibility.PUBLIC)
        if visibility not in SupplyListingVisibility.values:
            raise ValidationError({"visibility": f"Invalid visibility: '{visibility}'."})

        listing = SupplyListing(
            organization=supplier_org,
            created_by=user,
            created_by_operator=operator_flag,
            commodity=commodity,
            schema_version=schema_version,
            specifications=specifications,
            quantity=quantity_decimal,
            unit=data.get("unit", "MT") or "MT",
            indicative_price=indicative_price_decimal,
            currency=data.get("currency", "USD") or "USD",
            payment_terms=data.get("payment_terms", "") or "",
            incoterm=data.get("incoterm", "") or "",
            origin=data.get("origin", "") or "",
            destination=data.get("destination", "") or "",
            availability_window_start=availability_window_start,
            availability_window_end=availability_window_end,
            quality_notes=data.get("quality_notes", "") or "",
            notes=data.get("notes", "") or "",
            status=SupplyListingStatus.DRAFT,
            visibility=visibility,
            version=1,
        )
        listing.save()
        return listing

    @staticmethod
    @transaction.atomic
    def update_draft(
        supply_or_id: Any,
        data: dict,
        *,
        expected_version: Any,
        user: Any,
        organization_hint: Any = None,
    ) -> SupplyListing:
        """
        Update an existing Draft Supply Listing.
        - Synchronizes under exclusive row lock (select_for_update).
        - Enforces expected_version matches current aggregate version.
        - Enforces SupplyListing is in Draft status.
        - Enforces Owner/Manager or Operator authorization.
        - Safely handles commodity/schema switching by re-validating complete specifications.
        - Advances version by exactly 1 on success.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        _validate_expected_version(supply, expected_version)

        if supply.status != SupplyListingStatus.DRAFT:
            raise InvalidTransitionError(
                f"Cannot modify supply listing in status '{supply.status}'. "
                "Only draft listings can be modified."
            )

        if not can_manage_supply_listing(user, supply, organization_hint):
            raise SupplyListingPermissionDeniedError(
                "User lacks permission to modify this supply listing draft."
            )

        # Check for commodity / schema changes
        new_commodity_id = data.get("commodity_id")
        new_schema_version_id = data.get("schema_version_id")

        target_commodity = supply.commodity
        target_schema_version = supply.schema_version
        commodity_or_schema_changed = False

        if new_commodity_id is not None and str(new_commodity_id) != str(supply.commodity_id):
            try:
                target_commodity = CommodityDefinition.objects.get(
                    pk=new_commodity_id, is_active=True
                )
            except (CommodityDefinition.DoesNotExist, ValueError):
                raise ValidationError(
                    {"commodity_id": "Referenced commodity does not exist or is inactive."}
                )
            commodity_or_schema_changed = True

        if new_schema_version_id is not None and str(new_schema_version_id) != str(supply.schema_version_id):
            try:
                target_schema_version = CommoditySchemaVersion.objects.get(
                    pk=new_schema_version_id
                )
            except (CommoditySchemaVersion.DoesNotExist, ValueError):
                raise ValidationError(
                    {"schema_version_id": "Referenced schema version does not exist."}
                )
            commodity_or_schema_changed = True

        if commodity_or_schema_changed:
            if target_schema_version.commodity_id != target_commodity.id:
                raise ValidationError(
                    {"schema_version_id": "Schema version does not belong to the referenced commodity."}
                )
            if target_schema_version.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
                raise ValidationError(
                    {"schema_version_id": "Referenced commodity schema version must be published."}
                )

            candidate_specs = (
                data.get("specifications") if "specifications" in data else supply.specifications
            )
            if not isinstance(candidate_specs, dict):
                raise ValidationError({"specifications": "Specifications must be an object."})
            validate_specifications_payload(target_schema_version, candidate_specs)

            supply.commodity = target_commodity
            supply.schema_version = target_schema_version
            supply.specifications = candidate_specs
        elif "specifications" in data:
            specs = data["specifications"]
            if not isinstance(specs, dict):
                raise ValidationError({"specifications": "Specifications must be an object."})
            if specs:
                validate_specifications_payload(supply.schema_version, specs)
            supply.specifications = specs

        # Update approved editable fields
        if "quantity" in data:
            qty = data["quantity"]
            if qty is None:
                raise ValidationError({"quantity": "Quantity cannot be null."})
            try:
                qty_dec = Decimal(str(qty))
                if qty_dec <= 0:
                    raise ValidationError({"quantity": "Quantity must be greater than zero."})
                supply.quantity = qty_dec
            except Exception:
                raise ValidationError({"quantity": "Invalid quantity."})

        if "unit" in data:
            supply.unit = str(data["unit"]) if data["unit"] is not None else "MT"

        if "indicative_price" in data:
            ip = data["indicative_price"]
            if ip is None or str(ip).strip() == "":
                supply.indicative_price = None
            else:
                try:
                    ip_dec = Decimal(str(ip))
                    if ip_dec < 0:
                        raise ValidationError(
                            {"indicative_price": "Indicative price must be non-negative."}
                        )
                    supply.indicative_price = ip_dec
                except Exception:
                    raise ValidationError({"indicative_price": "Invalid indicative price."})

        if "currency" in data:
            supply.currency = str(data["currency"]) if data["currency"] else "USD"

        if "payment_terms" in data:
            supply.payment_terms = str(data["payment_terms"] or "")

        if "incoterm" in data:
            supply.incoterm = str(data["incoterm"] or "")

        if "origin" in data:
            supply.origin = str(data["origin"] or "")

        if "destination" in data:
            supply.destination = str(data["destination"] or "")

        if "availability_window_start" in data:
            supply.availability_window_start = data["availability_window_start"]

        if "availability_window_end" in data:
            supply.availability_window_end = data["availability_window_end"]

        if supply.availability_window_start and supply.availability_window_end:
            if supply.availability_window_end < supply.availability_window_start:
                raise ValidationError(
                    {
                        "availability_window_end": (
                            "Availability window end must be on or after availability window start."
                        )
                    }
                )

        if "quality_notes" in data:
            supply.quality_notes = str(data["quality_notes"] or "")

        if "notes" in data:
            supply.notes = str(data["notes"] or "")

        if "visibility" in data:
            vis = data["visibility"]
            if vis not in SupplyListingVisibility.values:
                raise ValidationError({"visibility": f"Invalid visibility: '{vis}'."})
            supply.visibility = vis

        supply.version += 1
        supply.save()
        return supply

    @staticmethod
    @transaction.atomic
    def activate_draft(
        supply_or_id: Any,
        *,
        expected_version: Any,
        user: Any,
        organization_hint: Any = None,
    ) -> SupplyListing:
        """
        Activate a Supply Listing draft.
        Authorizes actor, then delegates authoritatively to SupplyLifecycleService.activate.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        if not can_manage_supply_listing(user, supply, organization_hint):
            raise SupplyListingPermissionDeniedError(
                "User lacks permission to activate this supply listing."
            )

        return lifecycle_activate_supply(
            supply.id,
            expected_version=expected_version,
            actor=user,
        )

    @staticmethod
    @transaction.atomic
    def close(
        supply_or_id: Any,
        *,
        expected_version: Any,
        user: Any,
        organization_hint: Any = None,
    ) -> SupplyListing:
        """
        Close a Draft or Active Supply Listing.
        Authorizes actor, then delegates to SupplyLifecycleService.close.
        """
        supply_id = _extract_supply_id(supply_or_id)
        supply = _lock_supply(supply_id)

        if not can_manage_supply_listing(user, supply, organization_hint):
            raise SupplyListingPermissionDeniedError(
                "User lacks permission to close this supply listing."
            )

        return lifecycle_close_supply(
            supply.id,
            expected_version=expected_version,
            actor=user,
        )


create_draft_supply = SupplyService.create_draft
update_draft_supply = SupplyService.update_draft
activate_draft_supply = SupplyService.activate_draft
close_supply = SupplyService.close
