"""
Authoritative Opportunity -> RFQ and Supply Listing Conversion Services (T0609, T0610).

Governs the conversion of:
- Eligible Qualified Demand Opportunity into a real Draft RFQ via RFQService.create_draft.
- Eligible Qualified Supply Opportunity into a real Draft SupplyListing via SupplyService.create_draft.

Invariants:
- Strictly atomic execution in a single PostgreSQL transaction.
- Exclusive row-level locking via select_for_update prevents concurrent races.
- Reuses authoritative domain validations (commodity, schema version, dynamic specs,
  capability, quantity, delivery/availability window).
- Never maps to today's active schema; preserves exact schema version and dynamic specs.
- External Counterparty requires specifying a registered internal Organization.
- Relational durability via OneToOneField (converted_rfq / converted_supply_listing <-> source_opportunity).
- Dual conversion mutual exclusivity enforced at database constraint, model clean, and service level.
- Transitions Opportunity state Qualified -> Converted with a single version increment.
"""

from typing import Any

from django.db import transaction

from opportunities.api.permissions import is_operator_or_product_admin
from opportunities.exceptions import (
    OpportunityAlreadyConvertedError,
    OpportunityConversionError,
    OpportunityPermissionDeniedError,
)
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from opportunities.services_lifecycle import (
    OpportunityLifecycleService,
    _extract_opportunity_id,
    _lock_opportunity,
    _validate_expected_version,
)
from organizations.models import Organization, OrganizationCapability
from trade_hub.models import (
    RFQ,
    RFQVisibility,
    SupplyListing,
    SupplyListingVisibility,
)
from trade_hub.services.rfq_service import RFQService
from trade_hub.services.supply_service import SupplyService


@transaction.atomic
def convert_opportunity_to_rfq(
    opportunity_or_id: Any,
    *,
    expected_version: Any,
    actor: Any,
    data: dict | None = None,
) -> tuple[Opportunity, RFQ]:
    """
    Authoritatively converts an eligible qualified Demand Opportunity into a Draft RFQ.

    Parameters:
        opportunity_or_id: Opportunity instance, UUID, or string identifier.
        expected_version: Integer expected aggregate version for concurrency control.
        actor: Authenticated User with Operator or Product Admin system role.
        data: Optional dict carrying additional parameters (e.g. schema_version_id,
              specifications, buyer_organization_id, incoterm, notes, destination).

    Returns:
        tuple[Opportunity, RFQ]: (updated Converted Opportunity, newly created Draft RFQ)
    """
    if actor is None or not is_operator_or_product_admin(actor):
        raise OpportunityPermissionDeniedError(
            "Only Operators and Product Admins are authorized to convert Opportunities."
        )

    opp_id = _extract_opportunity_id(opportunity_or_id)
    opp = _lock_opportunity(opp_id)

    # 1. Optimistic Concurrency Control
    _validate_expected_version(opp, expected_version)

    # 2. Duplicate Conversion Guard
    if (
        opp.status == OpportunityStatus.CONVERTED
        or opp.converted_rfq_id is not None
        or opp.converted_supply_listing_id is not None
    ):
        if opp.converted_supply_listing_id is not None:
            raise OpportunityAlreadyConvertedError(
                f"Opportunity {opp.identifier or opp.id} has already been converted to a Supply Listing."
            )
        raise OpportunityAlreadyConvertedError(
            f"Opportunity {opp.identifier or opp.id} has already been converted to an RFQ."
        )

    # 3. Direction Invariant (Demand only)
    if opp.direction != OpportunityDirection.DEMAND:
        raise OpportunityConversionError(
            f"Cannot convert Opportunity with direction '{opp.direction}' to an RFQ. "
            f"Only Demand opportunities can be converted to an RFQ."
        )

    # 4. Lifecycle State Invariant (Qualified or Matching only)
    if opp.status not in (OpportunityStatus.QUALIFIED, OpportunityStatus.MATCHING):
        raise OpportunityConversionError(
            f"Cannot convert Opportunity in status '{opp.status}'. "
            f"Only Qualified or Matching opportunities can be converted to an RFQ."
        )

    extra_data = data or {}

    # 5. External Counterparty / Buyer Ownership Policy
    buyer_org_id = extra_data.get("buyer_organization_id")
    if not buyer_org_id:
        if opp.organization_id:
            buyer_org_id = opp.organization_id
        else:
            raise OpportunityConversionError(
                "Conversion of an external counterparty demand opportunity requires "
                "specifying an internal Buyer Organization (buyer_organization_id)."
            )

    # 6. Commodity & Schema Version Handling
    if not opp.commodity_id:
        raise OpportunityConversionError("Opportunity must reference an active commodity definition.")

    # Schema version: preserve exact schema from opportunity if stored; otherwise require from payload
    if opp.schema_version_id:
        schema_version_id = opp.schema_version_id
    else:
        schema_version_id = extra_data.get("schema_version_id")
        if not schema_version_id:
            raise OpportunityConversionError(
                "schema_version_id is required to create an RFQ. "
                "The referenced opportunity does not store a schema version."
            )

    # Specifications: preserve from opportunity if stored; otherwise take from payload (default empty dict)
    if opp.specifications:
        specifications = opp.specifications
    else:
        specifications = extra_data.get("specifications") or {}

    # 7. Delivery & Commercial Mapping
    destination = extra_data.get("destination") or opp.geography or ""
    origin = extra_data.get("origin") or ""
    incoterm = extra_data.get("incoterm") or ""
    visibility = extra_data.get("visibility") or RFQVisibility.PRIVATE

    # Notes Attribution & Provenance
    provenance_note = f"Converted from Opportunity {opp.identifier}."
    notes_parts = [provenance_note]
    if opp.notes and opp.notes.strip():
        notes_parts.append(opp.notes.strip())
    extra_notes = extra_data.get("notes")
    if extra_notes and extra_notes.strip() and extra_notes.strip() != opp.notes:
        notes_parts.append(extra_notes.strip())
    combined_notes = "\n\n".join(notes_parts)

    rfq_payload = {
        "organization_id": buyer_org_id,
        "commodity_id": opp.commodity_id,
        "schema_version_id": schema_version_id,
        "specifications": specifications,
        "quantity": opp.quantity,
        "unit": opp.unit or "MT",
        "target_price": opp.indicative_price,
        "currency": opp.currency or "USD",
        "payment_terms": opp.payment_terms or "",
        "incoterm": incoterm,
        "origin": origin,
        "destination": destination,
        "delivery_window_start": opp.delivery_window_start,
        "delivery_window_end": opp.delivery_window_end,
        "submission_deadline": extra_data.get("submission_deadline"),
        "inspection_required": bool(extra_data.get("inspection_required", False)),
        "quality_notes": extra_data.get("quality_notes", "") or "",
        "notes": combined_notes,
        "visibility": visibility,
    }

    # 8. Create RFQ Draft via Authoritative Epic 5 Domain Service
    rfq = RFQService.create_draft(user=actor, data=rfq_payload)

    # 9. Atomic Lifecycle Transition (opp.converted_rfq = rfq, status = Converted, version += 1)
    converted_opp = OpportunityLifecycleService.convert(
        opp,
        expected_version=expected_version,
        conversion_target=rfq,
        actor=actor,
    )

    return converted_opp, rfq


@transaction.atomic
def convert_opportunity_to_supply_listing(
    opportunity_or_id: Any,
    *,
    expected_version: Any,
    actor: Any,
    data: dict | None = None,
) -> tuple[Opportunity, SupplyListing]:
    """
    Authoritatively converts an eligible qualified Supply Opportunity into a Draft SupplyListing.

    Parameters:
        opportunity_or_id: Opportunity instance, UUID, or string identifier.
        expected_version: Integer expected aggregate version for concurrency control.
        actor: Authenticated User with Operator or Product Admin system role.
        data: Optional dict carrying additional parameters (e.g. schema_version_id,
              specifications, supplier_organization_id, incoterm, notes, origin, destination).

    Returns:
        tuple[Opportunity, SupplyListing]: (updated Converted Opportunity, newly created Draft SupplyListing)
    """
    if actor is None or not is_operator_or_product_admin(actor):
        raise OpportunityPermissionDeniedError(
            "Only Operators and Product Admins are authorized to convert Opportunities."
        )

    opp_id = _extract_opportunity_id(opportunity_or_id)
    opp = _lock_opportunity(opp_id)

    # 1. Optimistic Concurrency Control
    _validate_expected_version(opp, expected_version)

    # 2. Duplicate Conversion Guard
    if (
        opp.status == OpportunityStatus.CONVERTED
        or opp.converted_supply_listing_id is not None
        or opp.converted_rfq_id is not None
    ):
        if opp.converted_rfq_id is not None:
            raise OpportunityAlreadyConvertedError(
                f"Opportunity {opp.identifier or opp.id} has already been converted to an RFQ."
            )
        raise OpportunityAlreadyConvertedError(
            f"Opportunity {opp.identifier or opp.id} has already been converted to a Supply Listing."
        )

    # 3. Direction Invariant (Supply only)
    if opp.direction != OpportunityDirection.SUPPLY:
        raise OpportunityConversionError(
            f"Cannot convert Opportunity with direction '{opp.direction}' to a Supply Listing. "
            f"Only Supply opportunities can be converted to a Supply Listing."
        )

    # 4. Lifecycle State Invariant (Qualified or Matching only)
    if opp.status not in (OpportunityStatus.QUALIFIED, OpportunityStatus.MATCHING):
        raise OpportunityConversionError(
            f"Cannot convert Opportunity in status '{opp.status}'. "
            f"Only Qualified or Matching opportunities can be converted to a Supply Listing."
        )

    extra_data = data or {}

    # 5. External Counterparty / Supplier Ownership Policy
    supplier_org_id = extra_data.get("supplier_organization_id")
    if not supplier_org_id:
        if opp.organization_id:
            supplier_org_id = opp.organization_id
        else:
            raise OpportunityConversionError(
                "Conversion of an external counterparty supply opportunity requires "
                "specifying an internal Supplier Organization (supplier_organization_id)."
            )

    try:
        supplier_org = Organization.objects.get(pk=supplier_org_id, is_active=True)
    except (Organization.DoesNotExist, ValueError):
        raise OpportunityConversionError(
            f"Supplier organization '{supplier_org_id}' does not exist or is inactive."
        )

    if not OrganizationCapability.objects.filter(
        organization=supplier_org,
        capability=OrganizationCapability.CapabilityType.SUPPLIER,
    ).exists():
        raise OpportunityConversionError(
            f"Organization '{supplier_org.name}' lacks Supplier capability."
        )

    # 6. Commodity & Schema Version Handling
    if not opp.commodity_id:
        raise OpportunityConversionError("Opportunity must reference an active commodity definition.")

    # Schema version: preserve exact schema from opportunity if stored; otherwise require from payload
    if opp.schema_version_id:
        schema_version_id = opp.schema_version_id
    else:
        schema_version_id = extra_data.get("schema_version_id")
        if not schema_version_id:
            raise OpportunityConversionError(
                "schema_version_id is required to create a Supply Listing. "
                "The referenced opportunity does not store a schema version."
            )

    # Specifications: preserve from opportunity if stored; otherwise take from payload (default empty dict)
    if opp.specifications:
        specifications = opp.specifications
    else:
        specifications = extra_data.get("specifications") or {}

    # 7. Delivery, Geography & Commercial Mapping
    origin = extra_data.get("origin") or opp.geography or ""
    destination = extra_data.get("destination") or ""
    incoterm = extra_data.get("incoterm") or ""
    visibility = extra_data.get("visibility") or SupplyListingVisibility.PUBLIC
    availability_window_start = (
        extra_data.get("availability_window_start") or opp.delivery_window_start
    )
    availability_window_end = (
        extra_data.get("availability_window_end") or opp.delivery_window_end
    )

    # Notes Attribution & Provenance
    provenance_note = f"Converted from Opportunity {opp.identifier}."
    notes_parts = [provenance_note]
    if opp.notes and opp.notes.strip():
        notes_parts.append(opp.notes.strip())
    extra_notes = extra_data.get("notes")
    if extra_notes and extra_notes.strip() and extra_notes.strip() != opp.notes:
        notes_parts.append(extra_notes.strip())
    combined_notes = "\n\n".join(notes_parts)

    supply_payload = {
        "organization_id": supplier_org.id,
        "commodity_id": opp.commodity_id,
        "schema_version_id": schema_version_id,
        "specifications": specifications,
        "quantity": opp.quantity,
        "unit": opp.unit or "MT",
        "indicative_price": opp.indicative_price,
        "currency": opp.currency or "USD",
        "payment_terms": opp.payment_terms or "",
        "incoterm": incoterm,
        "origin": origin,
        "destination": destination,
        "availability_window_start": availability_window_start,
        "availability_window_end": availability_window_end,
        "quality_notes": extra_data.get("quality_notes", "") or "",
        "notes": combined_notes,
        "visibility": visibility,
    }

    # 8. Create Supply Listing Draft via Authoritative Epic 5 Domain Service
    listing = SupplyService.create_draft(user=actor, data=supply_payload)

    # 9. Atomic Lifecycle Transition (opp.converted_supply_listing = listing, status = Converted, version += 1)
    converted_opp = OpportunityLifecycleService.convert(
        opp,
        expected_version=expected_version,
        conversion_target=listing,
        actor=actor,
    )

    return converted_opp, listing
