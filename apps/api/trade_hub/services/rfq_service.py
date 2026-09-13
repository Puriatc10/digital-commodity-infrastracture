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
    RFQNotFoundError,
    RFQPermissionDeniedError,
    SpecificationValidationError,
    StaleVersionError,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import publish_rfq as lifecycle_publish_rfq
from trade_hub.services.visibility_service import (
    has_global_visibility,
    resolve_authoritative_organization,
)


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


def is_operator_or_admin(user: Any) -> bool:
    """Check if user holds OPERATOR or ADMIN system role."""
    return has_global_visibility(user)


def can_manage_rfq_builder(user: Any, rfq: RFQ, organization_hint: Any = None) -> bool:
    """
    Check if the user is authorized to edit or publish the RFQ.
    Allowed:
    - Platform Operator or Product Admin (via SystemRoleAssignment).
    - Owner or Manager of the RFQ's owning Buyer organization.
    Denied:
    - Member or Viewer of the RFQ's owning organization.
    - Foreign organizations / competitors.
    - Invited Suppliers or Brokers.
    - Django staff/superuser alone without system roles.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if is_operator_or_admin(user):
        return True

    current_org = resolve_authoritative_organization(user, organization_hint)
    if current_org is None or current_org.pk != rfq.organization_id:
        return False

    membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id=rfq.organization_id,
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


class RFQService:
    """Authoritative domain service governing RFQ Builder operations (create, update, publish)."""

    @staticmethod
    @transaction.atomic
    def create_draft(
        user: Any,
        data: dict,
        *,
        organization_hint: Any = None,
    ) -> RFQ:
        """
        Create a new Draft RFQ.
        - Enforces Buyer capability and Owner/Manager role (or Operator on-behalf).
        - Enforces active Commodity and published Schema Version belonging to that Commodity.
        - Validates dynamic specifications if provided.
        - Strictly prevents mass-assignment of status, version, timestamps, or buyer authority.
        """
        if not user or not getattr(user, "is_authenticated", False):
            raise RFQPermissionDeniedError("Authentication required.")

        operator_flag = is_operator_or_admin(user)

        if operator_flag:
            # Operator on-behalf: target organization can be specified via organization_id in data or hint
            target_org_id = data.get("organization_id") or organization_hint
            if not target_org_id:
                # Check if operator has an active membership in an organization
                current_org = resolve_authoritative_organization(user, None)
                if current_org:
                    target_org_id = current_org.pk
                else:
                    raise ValidationError(
                        {"organization_id": "Target buyer organization must be specified for operator actions."}
                    )

            try:
                buyer_org = Organization.objects.get(pk=target_org_id, is_active=True)
            except (Organization.DoesNotExist, ValueError):
                raise ValidationError(
                    {"organization_id": "Target organization does not exist or is inactive."}
                )

            # Check if operator is also an active member of the buyer org
            user_membership = OrganizationMembership.objects.filter(
                user=user,
                organization=buyer_org,
                is_active=True,
            ).first()
            if user_membership:
                operator_flag = False
        else:
            # Regular user: organization MUST come from authoritative session/membership context
            buyer_org = resolve_authoritative_organization(user, organization_hint)
            if buyer_org is None:
                raise RFQPermissionDeniedError(
                    "No active organization context found for user."
                )

            # Check membership role
            membership = OrganizationMembership.objects.filter(
                user=user,
                organization=buyer_org,
                is_active=True,
                organization__is_active=True,
            ).first()
            if not membership or membership.role not in (
                OrganizationMembership.OrganizationRole.OWNER,
                OrganizationMembership.OrganizationRole.MANAGER,
            ):
                raise RFQPermissionDeniedError(
                    "Only Organization Owner or Manager can create RFQ drafts."
                )

        # Enforce Buyer capability on the target organization
        has_buyer_capability = OrganizationCapability.objects.filter(
            organization=buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        ).exists()
        if not has_buyer_capability:
            raise RFQPermissionDeniedError(
                f"Organization '{buyer_org.name}' lacks Buyer capability."
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

        # Commercial & Delivery terms validation
        quantity = data.get("quantity")
        if quantity is None:
            raise ValidationError({"quantity": "quantity is required."})
        try:
            quantity_decimal = Decimal(str(quantity))
            if quantity_decimal <= 0:
                raise ValidationError({"quantity": "Quantity must be greater than zero."})
        except Exception:
            raise ValidationError({"quantity": "Invalid quantity."})

        target_price = data.get("target_price")
        target_price_decimal = None
        if target_price is not None and str(target_price).strip() != "":
            try:
                target_price_decimal = Decimal(str(target_price))
                if target_price_decimal < 0:
                    raise ValidationError({"target_price": "Target price must be non-negative."})
            except Exception:
                raise ValidationError({"target_price": "Invalid target price."})

        delivery_window_start = data.get("delivery_window_start")
        delivery_window_end = data.get("delivery_window_end")
        if delivery_window_start and delivery_window_end:
            if delivery_window_end < delivery_window_start:
                raise ValidationError(
                    {"delivery_window_end": "Delivery window end must be on or after delivery window start."}
                )

        visibility = data.get("visibility", RFQVisibility.PRIVATE)
        if visibility not in RFQVisibility.values:
            raise ValidationError({"visibility": f"Invalid visibility: '{visibility}'."})

        rfq = RFQ(
            organization=buyer_org,
            created_by=user,
            created_by_operator=operator_flag,
            commodity=commodity,
            schema_version=schema_version,
            specifications=specifications,
            quantity=quantity_decimal,
            unit=data.get("unit", "MT") or "MT",
            target_price=target_price_decimal,
            currency=data.get("currency", "USD") or "USD",
            payment_terms=data.get("payment_terms", "") or "",
            incoterm=data.get("incoterm", "") or "",
            origin=data.get("origin", "") or "",
            destination=data.get("destination", "") or "",
            delivery_window_start=delivery_window_start,
            delivery_window_end=delivery_window_end,
            submission_deadline=data.get("submission_deadline"),
            inspection_required=bool(data.get("inspection_required", False)),
            quality_notes=data.get("quality_notes", "") or "",
            notes=data.get("notes", "") or "",
            status=RFQStatus.DRAFT,
            visibility=visibility,
            version=1,
        )
        rfq.save()
        return rfq

    @staticmethod
    @transaction.atomic
    def update_draft(
        rfq_or_id: Any,
        data: dict,
        *,
        expected_version: Any,
        user: Any,
        organization_hint: Any = None,
    ) -> RFQ:
        """
        Update an existing Draft RFQ.
        - Synchronizes under exclusive row lock (select_for_update).
        - Enforces expected_version matches current aggregate version.
        - Enforces RFQ is in Draft status.
        - Enforces Owner/Manager or Operator authorization.
        - Safely handles commodity/schema switching by re-validating complete specifications.
        - Advances version by exactly 1 on success.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        rfq = _lock_rfq(rfq_id)

        _validate_expected_version(rfq, expected_version)

        if rfq.status != RFQStatus.DRAFT:
            raise InvalidTransitionError(
                f"Cannot modify RFQ in status '{rfq.status}'. Only draft RFQs can be modified."
            )

        if not can_manage_rfq_builder(user, rfq, organization_hint):
            raise RFQPermissionDeniedError(
                "User lacks permission to modify this RFQ draft."
            )

        # Check for commodity / schema changes
        new_commodity_id = data.get("commodity_id")
        new_schema_version_id = data.get("schema_version_id")

        target_commodity = rfq.commodity
        target_schema_version = rfq.schema_version
        commodity_or_schema_changed = False

        if new_commodity_id is not None and str(new_commodity_id) != str(rfq.commodity_id):
            try:
                target_commodity = CommodityDefinition.objects.get(
                    pk=new_commodity_id, is_active=True
                )
            except (CommodityDefinition.DoesNotExist, ValueError):
                raise ValidationError(
                    {"commodity_id": "Referenced commodity does not exist or is inactive."}
                )
            commodity_or_schema_changed = True

        if new_schema_version_id is not None and str(new_schema_version_id) != str(rfq.schema_version_id):
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

            # On commodity/schema change, validate complete specifications against selected exact schema.
            # Do not preserve invalid stale technical fields silently.
            candidate_specs = data.get("specifications") if "specifications" in data else rfq.specifications
            if not isinstance(candidate_specs, dict):
                raise ValidationError({"specifications": "Specifications must be an object."})
            validate_specifications_payload(target_schema_version, candidate_specs)

            rfq.commodity = target_commodity
            rfq.schema_version = target_schema_version
            rfq.specifications = candidate_specs
        elif "specifications" in data:
            specs = data["specifications"]
            if not isinstance(specs, dict):
                raise ValidationError({"specifications": "Specifications must be an object."})
            if specs:
                validate_specifications_payload(rfq.schema_version, specs)
            rfq.specifications = specs

        # Update approved editable fields
        if "quantity" in data:
            qty = data["quantity"]
            if qty is None:
                raise ValidationError({"quantity": "Quantity cannot be null."})
            try:
                qty_dec = Decimal(str(qty))
                if qty_dec <= 0:
                    raise ValidationError({"quantity": "Quantity must be greater than zero."})
                rfq.quantity = qty_dec
            except Exception:
                raise ValidationError({"quantity": "Invalid quantity."})

        if "unit" in data:
            rfq.unit = str(data["unit"]) if data["unit"] is not None else "MT"

        if "target_price" in data:
            tp = data["target_price"]
            if tp is None or str(tp).strip() == "":
                rfq.target_price = None
            else:
                try:
                    tp_dec = Decimal(str(tp))
                    if tp_dec < 0:
                        raise ValidationError({"target_price": "Target price must be non-negative."})
                    rfq.target_price = tp_dec
                except Exception:
                    raise ValidationError({"target_price": "Invalid target price."})

        if "currency" in data:
            rfq.currency = str(data["currency"]) if data["currency"] else "USD"

        if "payment_terms" in data:
            rfq.payment_terms = str(data["payment_terms"] or "")

        if "incoterm" in data:
            rfq.incoterm = str(data["incoterm"] or "")

        if "origin" in data:
            rfq.origin = str(data["origin"] or "")

        if "destination" in data:
            rfq.destination = str(data["destination"] or "")

        if "delivery_window_start" in data:
            rfq.delivery_window_start = data["delivery_window_start"]

        if "delivery_window_end" in data:
            rfq.delivery_window_end = data["delivery_window_end"]

        if rfq.delivery_window_start and rfq.delivery_window_end:
            if rfq.delivery_window_end < rfq.delivery_window_start:
                raise ValidationError(
                    {"delivery_window_end": "Delivery window end must be on or after delivery window start."}
                )

        if "submission_deadline" in data:
            rfq.submission_deadline = data["submission_deadline"]

        if "inspection_required" in data:
            rfq.inspection_required = bool(data["inspection_required"])

        if "quality_notes" in data:
            rfq.quality_notes = str(data["quality_notes"] or "")

        if "notes" in data:
            rfq.notes = str(data["notes"] or "")

        if "visibility" in data:
            vis = data["visibility"]
            if vis not in RFQVisibility.values:
                raise ValidationError({"visibility": f"Invalid visibility: '{vis}'."})
            rfq.visibility = vis

        rfq.version += 1
        rfq.save()
        return rfq

    @staticmethod
    @transaction.atomic
    def publish_draft(
        rfq_or_id: Any,
        *,
        expected_version: Any,
        user: Any,
        organization_hint: Any = None,
    ) -> RFQ:
        """
        Publish an RFQ draft.
        Authorizes actor, then delegates authoritatively to T0502 RFQLifecycleService.publish.
        """
        rfq_id = _extract_rfq_id(rfq_or_id)
        # Lock and check permission before publication
        rfq = _lock_rfq(rfq_id)

        if not can_manage_rfq_builder(user, rfq, organization_hint):
            raise RFQPermissionDeniedError(
                "User lacks permission to publish this RFQ."
            )

        return lifecycle_publish_rfq(
            rfq.id,
            expected_version=expected_version,
            actor=user,
        )


create_draft_rfq = RFQService.create_draft
update_draft_rfq = RFQService.update_draft
publish_draft_rfq = RFQService.publish_draft
