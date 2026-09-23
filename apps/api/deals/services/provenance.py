from typing import Any, Optional

from deals.models import (
    Deal,
    DealBrokerAttribution,
    DealBrokerRole,
    DealOpportunityAttribution,
    DealOpportunityRole,
)
from offers.enums import OfferorRole


def _get_demand_opportunity(deal: Deal) -> Optional[Any]:
    """Safely retrieves the demand-originating Opportunity from RFQ conversion if present."""
    rfq = getattr(deal, "rfq", None)
    if not rfq:
        return None
    try:
        return rfq.source_opportunity
    except Exception:
        return None


def extract_deal_provenance(
    deal: Deal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deterministically extract explicit Broker and Opportunity provenance candidates
    for a Deal from its immutable source graph (Epic 9 Contract §50-§57, T0904).

    Extraction Sources:
    1. Demand Origin:
       - If RFQ originated from an Opportunity (rfq.source_opportunity), record
         DealOpportunityAttribution with role=DEMAND_ORIGIN.
       - If that Demand Opportunity has an attributed broker (opp.broker), record
         DealBrokerAttribution with role=DEMAND_ORIGINATOR and related_opportunity=opp.
    2. Supply Origin:
       - If Offer originated from a Supply Opportunity (offer.source_opportunity), record
         DealOpportunityAttribution with role=SUPPLY_ORIGIN.
       - If that Supply Opportunity has an attributed broker (opp.broker), record
         DealBrokerAttribution with role=SUPPLY_ORIGINATOR and related_opportunity=opp.
    3. Selected Offer Broker Party (Broker-as-Seller or Broker offering):
       - If offer.offeror_role == OfferorRole.BROKER and offer.offering_organization is set, record
         DealBrokerAttribution with role=SUPPLY_ORIGINATOR and related_opportunity=supply_opp.

    Critical Invariants:
    - No Capability Inference: Mere possession of Broker capability by an Organization
      WITHOUT explicit provenance NEVER generates a DealBrokerAttribution row.
    - No Free-Text IDs: Linkages strictly reference validated relational models.
    - Multiple Brokers: Distinct brokers (e.g. Broker A on Demand, Broker B on Supply)
      and the same broker holding both roles are fully supported.
    - Deduplication: Returns deduplicated candidate parameter dictionaries.
    """
    offer = deal.offer
    supply_opp = getattr(offer, "source_opportunity", None)
    demand_opp = _get_demand_opportunity(deal)

    opp_candidates: list[dict[str, Any]] = []
    broker_candidates: list[dict[str, Any]] = []

    seen_opp_keys: set[tuple[Any, str]] = set()
    seen_broker_keys: set[tuple[Any, str, Any]] = set()

    # 1. Demand Opportunity & Demand Broker Provenance
    if demand_opp:
        opp_key = (demand_opp.id, DealOpportunityRole.DEMAND_ORIGIN)
        if opp_key not in seen_opp_keys:
            seen_opp_keys.add(opp_key)
            opp_candidates.append({
                "deal": deal,
                "opportunity": demand_opp,
                "role": DealOpportunityRole.DEMAND_ORIGIN,
            })

        # Explicit Demand Broker referral
        if demand_opp.broker_id:
            broker_key = (
                demand_opp.broker_id,
                DealBrokerRole.DEMAND_ORIGINATOR,
                demand_opp.id,
            )
            if broker_key not in seen_broker_keys:
                seen_broker_keys.add(broker_key)
                broker_candidates.append({
                    "deal": deal,
                    "broker_organization": demand_opp.broker,
                    "role": DealBrokerRole.DEMAND_ORIGINATOR,
                    "related_opportunity": demand_opp,
                })

    # 2. Supply Opportunity & Supply Broker Provenance
    if supply_opp:
        opp_key = (supply_opp.id, DealOpportunityRole.SUPPLY_ORIGIN)
        if opp_key not in seen_opp_keys:
            seen_opp_keys.add(opp_key)
            opp_candidates.append({
                "deal": deal,
                "opportunity": supply_opp,
                "role": DealOpportunityRole.SUPPLY_ORIGIN,
            })

        # Explicit Supply Broker referral (e.g. Hero Case: Broker Referral -> External Supplier)
        if supply_opp.broker_id:
            broker_key = (
                supply_opp.broker_id,
                DealBrokerRole.SUPPLY_ORIGINATOR,
                supply_opp.id,
            )
            if broker_key not in seen_broker_keys:
                seen_broker_keys.add(broker_key)
                broker_candidates.append({
                    "deal": deal,
                    "broker_organization": supply_opp.broker,
                    "role": DealBrokerRole.SUPPLY_ORIGINATOR,
                    "related_opportunity": supply_opp,
                })

    # 3. Selected Offer Economic Party is Broker (OfferorRole.BROKER)
    if (
        offer.offeror_role == OfferorRole.BROKER
        and offer.offering_organization_id
    ):
        related_opp = supply_opp
        rel_opp_id = supply_opp.id if supply_opp else None
        broker_key = (
            offer.offering_organization_id,
            DealBrokerRole.SUPPLY_ORIGINATOR,
            rel_opp_id,
        )
        if broker_key not in seen_broker_keys:
            seen_broker_keys.add(broker_key)
            broker_candidates.append({
                "deal": deal,
                "broker_organization": offer.offering_organization,
                "role": DealBrokerRole.SUPPLY_ORIGINATOR,
                "related_opportunity": related_opp,
            })

    return opp_candidates, broker_candidates


def persist_deal_provenance(
    deal: Deal,
) -> tuple[list[DealOpportunityAttribution], list[DealBrokerAttribution]]:
    """
    Persist explicit Broker and Opportunity provenance rows for a Deal.

    Executed inside the caller's atomic materialization transaction.
    Guarantees that if source evidence supports Broker or Opportunity provenance,
    the records are persisted atomically with the parent Deal.
    """
    opp_candidates, broker_candidates = extract_deal_provenance(deal)

    persisted_opps: list[DealOpportunityAttribution] = []
    for candidate in opp_candidates:
        existing = DealOpportunityAttribution.objects.filter(
            deal=candidate["deal"],
            opportunity=candidate["opportunity"],
            role=candidate["role"],
        ).first()
        if existing:
            persisted_opps.append(existing)
        else:
            inst = DealOpportunityAttribution.objects.create(**candidate)
            persisted_opps.append(inst)

    persisted_brokers: list[DealBrokerAttribution] = []
    for candidate in broker_candidates:
        existing = DealBrokerAttribution.objects.filter(
            deal=candidate["deal"],
            broker_organization=candidate["broker_organization"],
            role=candidate["role"],
            related_opportunity=candidate["related_opportunity"],
        ).first()
        if existing:
            persisted_brokers.append(existing)
        else:
            inst = DealBrokerAttribution.objects.create(**candidate)
            persisted_brokers.append(inst)

    return persisted_opps, persisted_brokers
