from typing import Any, Optional
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from identity.models import SystemRoleAssignment
from offers.enums import OfferorRole
from offers.exceptions import (
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
)
from offers.models import Offer
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus
from trade_hub.services.visibility_service import RFQVisibilityService


def _has_system_role_authority(user: Any) -> bool:
    """
    Verify whether a user holds global Operator or Product Admin system authority.

    Critical Invariant:
    Conferred strictly by SystemRoleAssignment(OPERATOR or ADMIN).
    Django is_staff and is_superuser alone grant NO product operational authority.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return SystemRoleAssignment.objects.filter(
        user=user,
        role__in=[
            SystemRoleAssignment.SystemRole.OPERATOR,
            SystemRoleAssignment.SystemRole.ADMIN,
        ],
    ).exists()


def create_offer(
    *,
    actor: Any,
    rfq: RFQ | uuid.UUID | str,
    offeror_role: str,
    offering_organization: Optional[Organization | uuid.UUID | str] = None,
    external_counterparty: Optional[ExternalCounterparty | uuid.UUID | str] = None,
    source_opportunity: Optional[Opportunity | uuid.UUID | str] = None,
    **extra_kwargs: Any,
) -> Offer:
    """
    Authoritative domain service to instantiate a stable Offer parent aggregate (T0801).

    Enforces:
    - Actor authentication and authority (strictly prevents actor/creator spoofing).
    - Target RFQ existence, open lifecycle state, and non-expired deadline.
    - Strict economic party exclusivity (offering_organization XOR external_counterparty).
    - Offeror role validation (SUPPLIER or BROKER only; no TRADER).
    - Internal offering organization capability matching (SUPPLIER -> Supplier capability,
      BROKER -> Broker capability; multi-capability org may explicitly choose either).
    - Internal actor active membership in organization (Owner, Manager, Member allowed; Viewer rejected).
    - Internal organization RFQ visibility and buyer-self-offering prevention.
    - External counterparty creation authority restricted to Operator/Product Admin via SystemRoleAssignment.
    - External counterparty provenance requirement: must provide a Qualified Supply Opportunity
      for the same ExternalCounterparty.
    - Controlled conflict handling for thread uniqueness races under PostgreSQL concurrency.
    - Invariant: does NOT mutate RFQ lifecycle (T0803 owns transitions upon submission).
    - Invariant: does NOT create fake User, Organization, or Membership rows.
    """
    # 1. Actor Authentication
    if not actor or not getattr(actor, "is_authenticated", False):
        raise OfferPermissionDeniedError("Authentication is required to create an offer.")

    # 2. Resolve RFQ target
    if not isinstance(rfq, RFQ):
        rfq_obj = RFQ.objects.filter(pk=rfq).first()
        if not rfq_obj:
            raise OfferValidationError(f"Target RFQ '{rfq}' does not exist.")
        rfq = rfq_obj

    # 3. Validate RFQ State & Deadline
    if rfq.status not in [RFQStatus.PUBLISHED, RFQStatus.COLLECTING_OFFERS]:
        raise OfferStateError(
            f"RFQ is in '{rfq.status}' status and cannot accept offers. "
            f"Offers may only be created against Published or Collecting Offers RFQs."
        )

    if rfq.submission_deadline and timezone.now() > rfq.submission_deadline:
        raise OfferValidationError("RFQ offer submission deadline has passed.")

    # 4. Resolve Economic Party Arguments
    if isinstance(offering_organization, (str, uuid.UUID)):
        org_obj = Organization.objects.filter(pk=offering_organization).first()
        if not org_obj:
            raise OfferValidationError(
                f"Offering organization '{offering_organization}' does not exist."
            )
        offering_organization = org_obj

    if isinstance(external_counterparty, (str, uuid.UUID)):
        ext_obj = ExternalCounterparty.objects.filter(pk=external_counterparty).first()
        if not ext_obj:
            raise OfferValidationError(
                f"External counterparty '{external_counterparty}' does not exist."
            )
        external_counterparty = ext_obj

    if isinstance(source_opportunity, (str, uuid.UUID)):
        opp_obj = Opportunity.objects.filter(pk=source_opportunity).first()
        if not opp_obj:
            raise OfferValidationError(
                f"Source opportunity '{source_opportunity}' does not exist."
            )
        source_opportunity = opp_obj

    # 5. Exactly One Economic Party (offering_organization XOR external_counterparty)
    has_org = offering_organization is not None
    has_ext = external_counterparty is not None
    if has_org == has_ext:
        raise OfferValidationError(
            "Offer must specify exactly one economic party: "
            "offering_organization XOR external_counterparty."
        )

    # 6. Offeror Role Validation
    if offeror_role not in [OfferorRole.SUPPLIER, OfferorRole.BROKER]:
        raise OfferValidationError(
            f"Invalid offeror role '{offeror_role}'. Role must be SUPPLIER or BROKER."
        )

    # 7. Internal Organization Path Validation
    if offering_organization is not None:
        # Owning Buyer Organization cannot submit offer to own RFQ
        if rfq.organization_id == offering_organization.id:
            raise OfferValidationError(
                "Owning buyer organization cannot create an offer for its own RFQ."
            )

        # Active Membership check
        membership = OrganizationMembership.objects.filter(
            user=actor,
            organization=offering_organization,
            is_active=True,
            organization__is_active=True,
        ).first()
        if not membership:
            raise OfferPermissionDeniedError(
                "Actor does not have active membership in the offering organization."
            )

        # Membership role authorization: Owner, Manager, Member allowed; Viewer read-only
        if membership.role == OrganizationMembership.OrganizationRole.VIEWER:
            raise OfferPermissionDeniedError(
                "Viewers have read-only access and cannot create offers."
            )

        # Organization Capability check
        if offeror_role == OfferorRole.SUPPLIER:
            has_capability = OrganizationCapability.objects.filter(
                organization=offering_organization,
                capability=OrganizationCapability.CapabilityType.SUPPLIER,
            ).exists()
            if not has_capability:
                raise OfferValidationError(
                    f"Organization '{offering_organization.name}' lacks required Supplier capability."
                )
        elif offeror_role == OfferorRole.BROKER:
            has_capability = OrganizationCapability.objects.filter(
                organization=offering_organization,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists()
            if not has_capability:
                raise OfferValidationError(
                    f"Organization '{offering_organization.name}' lacks required Broker capability."
                )

        # Visibility to RFQ
        if not RFQVisibilityService.is_rfq_visible(rfq, actor, organization=offering_organization):
            raise OfferPermissionDeniedError(
                "Target RFQ is not visible or accessible to the offering organization."
            )

        # Optional internal source opportunity check
        if source_opportunity is not None:
            if source_opportunity.direction != OpportunityDirection.SUPPLY:
                raise OfferValidationError(
                    "Source Opportunity for an offer must have SUPPLY direction."
                )
            if (
                source_opportunity.organization_id
                and source_opportunity.organization_id != offering_organization.id
            ):
                raise OfferValidationError(
                    "Source Opportunity organization does not match the offering organization."
                )
            if source_opportunity.external_counterparty_id:
                raise OfferValidationError(
                    "Internal organization offer cannot reference an external counterparty opportunity."
                )

    # 8. External Counterparty Path Validation
    elif external_counterparty is not None:
        # Operator / Product Admin authority check (SystemRoleAssignment)
        if not _has_system_role_authority(actor):
            raise OfferPermissionDeniedError(
                "External counterparty offers may only be created by platform Operators "
                "or Product Admins."
            )

        # Source Opportunity is MANDATORY for external counterparty offers
        if source_opportunity is None:
            raise OfferValidationError(
                "External counterparty offer requires a source Opportunity."
            )

        # Validate Opportunity Provenance
        if source_opportunity.direction != OpportunityDirection.SUPPLY:
            raise OfferValidationError(
                f"Source Opportunity direction must be SUPPLY (found '{source_opportunity.direction}')."
            )

        if source_opportunity.status != OpportunityStatus.QUALIFIED:
            raise OfferStateError(
                f"Source Opportunity must be in Qualified status to create an external offer "
                f"(current status: '{source_opportunity.status}')."
            )

        if source_opportunity.external_counterparty_id != external_counterparty.id:
            raise OfferValidationError(
                "Source Opportunity external counterparty does not match the offer external counterparty."
            )

    # 9. Thread Uniqueness & Creation under PostgreSQL Transaction
    try:
        with transaction.atomic():
            # Application-level check
            if offering_organization is not None:
                if Offer.objects.filter(
                    rfq=rfq,
                    offering_organization=offering_organization,
                    offeror_role=offeror_role,
                ).exists():
                    raise OfferConflictError(
                        f"An offer already exists for RFQ '{rfq.id}', "
                        f"organization '{offering_organization.id}', and role '{offeror_role}'."
                    )
            else:
                if Offer.objects.filter(
                    rfq=rfq,
                    external_counterparty=external_counterparty,
                    offeror_role=offeror_role,
                ).exists():
                    raise OfferConflictError(
                        f"An offer already exists for RFQ '{rfq.id}', "
                        f"external counterparty '{external_counterparty.id}', and role '{offeror_role}'."
                    )

            # Persist Offer with server-authenticated actor (anti-spoofing)
            offer = Offer.objects.create(
                rfq=rfq,
                offeror_role=offeror_role,
                offering_organization=offering_organization,
                external_counterparty=external_counterparty,
                source_opportunity=source_opportunity,
                aggregate_version=1,
                created_by=actor,
            )
            return offer

    except IntegrityError as exc:
        raise OfferConflictError(
            "An offer thread already exists for this RFQ, economic party, and role."
        ) from exc
