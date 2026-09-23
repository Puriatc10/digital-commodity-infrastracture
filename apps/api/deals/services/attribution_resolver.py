from typing import Any, Optional

from django.utils import timezone

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealAttributionResolutionMethod,
    DealAttributionStatus,
)
from offers.enums import OfferorRole
from opportunities.models import OpportunitySource
from trade_hub.models.invitation import RFQInvitation


OPPORTUNITY_DESK_SOURCES = {
    OpportunitySource.OPERATOR_SOURCING,
    OpportunitySource.INBOUND_LEAD,
    OpportunitySource.SUPPLIER_REFERRAL,
    OpportunitySource.BUYER_REFERRAL,
}


def _get_demand_opportunity(deal: Deal) -> Optional[Any]:
    """Safely retrieves the demand-originating Opportunity from RFQ conversion if present."""
    rfq = getattr(deal, "rfq", None)
    if not rfq:
        return None
    try:
        return rfq.source_opportunity
    except Exception:
        return None


def collect_deal_attribution_evidence(deal: Deal) -> dict[str, Any]:
    """
    Deterministically collect explicit persisted provenance evidence for a Deal (Contract §49).

    Invariants:
    - Only captures persisted, structured, verifiable references (Offer, RFQ, Opportunities, Invitations).
    - Preserves stable IDs and canonical enum machine values.
    - Strictly excludes personal / private data: phone, email, contact-attempt logs, private notes, verification docs.
    """
    offer = deal.offer
    supply_opp = getattr(offer, "source_opportunity", None)
    demand_opp = _get_demand_opportunity(deal)

    invitation = None
    if deal.seller_organization_id:
        invitation = RFQInvitation.objects.filter(
            rfq_id=deal.rfq_id,
            organization_id=deal.seller_organization_id,
        ).first()

    # Determine if direct participation fact exists
    # Direct participation: internal seller organization directly participating in SUPPLIER role without intermediary
    is_direct_participation = bool(
        deal.seller_organization_id
        and not deal.seller_external_counterparty_id
        and offer.offering_organization_id == deal.seller_organization_id
        and offer.offeror_role == OfferorRole.SUPPLIER
        and not offer.external_counterparty_id
        and not supply_opp
        and not demand_opp
    )

    detected_channels: list[str] = []

    # 1. Existing Relationship check
    has_existing_rel = bool(
        (supply_opp and supply_opp.source == OpportunitySource.EXISTING_RELATIONSHIP)
        or (demand_opp and demand_opp.source == OpportunitySource.EXISTING_RELATIONSHIP)
    )
    if has_existing_rel:
        detected_channels.append(DealAttributionChannel.BUYER_EXISTING_SUPPLIER)

    # 2. Broker check
    has_broker = bool(
        offer.offeror_role == OfferorRole.BROKER
        or (supply_opp and (supply_opp.source == OpportunitySource.BROKER_REFERRAL or supply_opp.broker_id is not None))
        or (demand_opp and (demand_opp.source == OpportunitySource.BROKER_REFERRAL or demand_opp.broker_id is not None))
    )
    if has_broker:
        detected_channels.append(DealAttributionChannel.BROKER)

    # 3. Opportunity Desk check
    has_opp_desk = bool(
        (supply_opp and supply_opp.source in OPPORTUNITY_DESK_SOURCES)
        or (demand_opp and demand_opp.source in OPPORTUNITY_DESK_SOURCES)
    )
    if has_opp_desk:
        detected_channels.append(DealAttributionChannel.OPPORTUNITY_DESK)

    # 4. Platform Network check (Report: no durable persisted link exists in current models)
    # Never infer from MatchingRun existing somewhere or general registration

    # 5. Direct Supplier check
    if is_direct_participation:
        detected_channels.append(DealAttributionChannel.DIRECT_SUPPLIER)

    evidence_snapshot: dict[str, Any] = {
        "deal_id": str(deal.id),
        "award_id": str(deal.award_id),
        "award_allocation_id": str(deal.award_allocation_id),
        "rfq_id": str(deal.rfq_id),
        "offer_id": str(deal.offer_id),
        "offer_version_id": str(deal.offer_version_id),
        "buyer_organization_id": str(deal.buyer_organization_id),
        "seller_organization_id": str(deal.seller_organization_id) if deal.seller_organization_id else None,
        "seller_external_counterparty_id": str(deal.seller_external_counterparty_id) if deal.seller_external_counterparty_id else None,
        "offeror_role": offer.offeror_role,
        "source_supply_opportunity_id": str(supply_opp.id) if supply_opp else None,
        "source_supply_opportunity_source": supply_opp.source if supply_opp else None,
        "source_supply_opportunity_broker_id": str(supply_opp.broker_id) if supply_opp and supply_opp.broker_id else None,
        "source_demand_opportunity_id": str(demand_opp.id) if demand_opp else None,
        "source_demand_opportunity_source": demand_opp.source if demand_opp else None,
        "source_demand_opportunity_broker_id": str(demand_opp.broker_id) if demand_opp and demand_opp.broker_id else None,
        "source_rfq_invitation_id": str(invitation.id) if invitation else None,
        "is_direct_participation": is_direct_participation,
        "detected_channels": detected_channels,
    }
    return evidence_snapshot


def resolve_deal_attribution(deal: Deal) -> tuple[str, Optional[str], dict[str, Any]]:
    """
    Central deterministic attribution resolver (Contract §40-§46, T0903).

    Applies the exact business priority order:
        1. BUYER_EXISTING_SUPPLIER
        2. BROKER
        3. OPPORTUNITY_DESK
        4. PLATFORM_NETWORK
        5. DIRECT_SUPPLIER
    Fallback:
        PENDING

    Returns:
        tuple[status, primary_channel, evidence_snapshot]
    """
    evidence = collect_deal_attribution_evidence(deal)
    detected = evidence.get("detected_channels", [])

    # Exact Precedence:
    # 1. BUYER_EXISTING_SUPPLIER
    if DealAttributionChannel.BUYER_EXISTING_SUPPLIER in detected:
        return (
            DealAttributionStatus.RESOLVED,
            DealAttributionChannel.BUYER_EXISTING_SUPPLIER,
            evidence,
        )

    # 2. BROKER
    if DealAttributionChannel.BROKER in detected:
        return (
            DealAttributionStatus.RESOLVED,
            DealAttributionChannel.BROKER,
            evidence,
        )

    # 3. OPPORTUNITY_DESK
    if DealAttributionChannel.OPPORTUNITY_DESK in detected:
        return (
            DealAttributionStatus.RESOLVED,
            DealAttributionChannel.OPPORTUNITY_DESK,
            evidence,
        )

    # 4. PLATFORM_NETWORK
    if DealAttributionChannel.PLATFORM_NETWORK in detected:
        return (
            DealAttributionStatus.RESOLVED,
            DealAttributionChannel.PLATFORM_NETWORK,
            evidence,
        )

    # 5. DIRECT_SUPPLIER
    if DealAttributionChannel.DIRECT_SUPPLIER in detected:
        return (
            DealAttributionStatus.RESOLVED,
            DealAttributionChannel.DIRECT_SUPPLIER,
            evidence,
        )

    # Genuinely unknown / ambiguous / external counterparty without opportunity provenance -> PENDING
    return (
        DealAttributionStatus.PENDING,
        None,
        evidence,
    )


def create_initial_deal_attribution(deal: Deal) -> DealAttribution:
    """
    Instantiate and save the initial DealAttribution aggregate for a newly materialized Deal.

    Executed inside the materialization atomic transaction.
    """
    status, primary_channel, evidence = resolve_deal_attribution(deal)
    now = timezone.now() if status == DealAttributionStatus.RESOLVED else None
    res_method = DealAttributionResolutionMethod.AUTOMATIC if status == DealAttributionStatus.RESOLVED else None

    attribution = DealAttribution(
        deal=deal,
        status=status,
        primary_channel=primary_channel,
        resolution_method=res_method,
        resolved_by=None,
        resolved_at=now,
        resolution_reason="",
        evidence_snapshot=evidence,
        version=1,
    )
    attribution.save()
    return attribution
