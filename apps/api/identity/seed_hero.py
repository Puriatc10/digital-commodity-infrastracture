"""
Deterministic and Idempotent Hero Scenario Seed (Epic 13, T1302).

Establishes the deterministic supporting context for the canonical Hero Demo Scenario:
    500 MT Bitumen 60/70
    -> Dynamic Commodity Form
    -> Matching (7 Suppliers, 3 Brokers)
    -> two existing Supplier Offers
    -> Broker introduces external supply
    -> OPP-2026-00124 (OPP-2026-000124)
    -> qualification
    -> external Offer
    -> comparison
    -> revision
    -> award
    -> Deal
    -> execution
    -> intelligence

BOUNDARY INVARIANTS (T1302 vs T1307):
- T1302 establishes the starting world; T1307 creates the business outcome.
- Zero fake completed artifacts: NO awarded Hero Offer, NO Hero Deal,
  NO Hero Execution Complete, NO fake Hero Analytics.
- Canonical Participants:
  * Canonical Buyer: Demo Buyer Corp (buyer@demo.local)
  * Canonical Supplier 1: Demo Supplier LLC (supplier@demo.local)
  * Canonical Supplier 2: Isfahan Bitumen Refining Co. (supplier.isfahan@demo.local)
  * Canonical Broker: Demo Brokerage (broker@demo.local)
  * ExternalCounterparty: Gulf Petrochemicals FZE (strictly external, no User/Org)
  * Operator: operator@demo.local
- Matching Context:
  * Candidate universe strictly evaluates to 7 Suppliers and 3 Brokers using the real
    MatchingRunService and CandidateDiscoveryService.
  * No fake API responses, no frontend-only mocks, no hard-coded branching in matching engine.
- Idempotent and deterministic: repeated executions converge to the identical state.
"""

from datetime import date, timedelta
from decimal import Decimal
import logging
from typing import Any, Dict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.utils import timezone

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from deals.models import Deal
from matching.candidates.context import ActorScope
from matching.enums import CandidateLane, MatchingAudience
from matching.models.run import MatchingRun
from matching.services import MatchingRunService
from offers.models import Offer
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity
from organizations.models import (
    Organization,
    OrganizationCommodity,
)
from trade_hub.models import RFQ, RFQVisibility
from trade_hub.services.rfq_lifecycle import RFQLifecycleService
from trade_hub.services.rfq_service import RFQService

logger = logging.getLogger(__name__)
User = get_user_model()

HERO_SEED_VERSION = "1.0.0"
HERO_OPP_IDENTIFIER = "OPP-2026-000124"
HERO_OPP_TAG = "[DEMO-OPP-HERO]"
HERO_RFQ_TAG = "[DEMO-HERO-RFQ]"


def seed_hero_scenario(stdout=None) -> Dict[str, Any]:
    """
    Seed the deterministic Hero Scenario context into the database.

    Guarantees:
    - Deterministic participants and identifiers.
    - Matching produces exactly 7 Suppliers and 3 Brokers against Bitumen 60/70.
    - Hero Opportunity OPP-2026-000124 exists in Captured status with Broker referral attribution.
    - Hero RFQ exists in Published status without pre-completed offers or deal.
    - Fully idempotent across multiple executions.
    """
    if not getattr(settings, "DEMO_PERSONA_SWITCHER_ENABLED", False):
        raise CommandError("DEMO_PERSONA_SWITCHER_ENABLED must be enabled in settings before seeding Demo data.")

    if stdout:
        stdout.write("Seeding Hero Scenario Context (T1302)...")

    # 1. Ensure realistic dataset baseline (prerequisites, orgs, commodities)
    from identity.seed_dataset import _ensure_prerequisites, _seed_external_counterparties, _seed_organizations_and_users
    prereqs = _ensure_prerequisites(stdout=stdout)
    entities = _seed_organizations_and_users()
    ext_cps = _seed_external_counterparties(entities["operator_user"])

    bitumen = prereqs["bitumen"]
    bitumen_schema = prereqs["bitumen_schema"]
    base_oil = prereqs.get("base_oil")

    buyer_user = entities["users"]["buyer_1"]
    buyer_org = entities["orgs"]["buyer_1"]
    supplier_1_org = entities["orgs"]["supplier_1"]
    supplier_2_org = entities["orgs"]["supplier_2"]
    broker_org = entities["orgs"]["broker_1"]
    operator_user = entities["operator_user"]
    ext_cp = ext_cps["gulf_petro"]

    # 2. Synchronize commodity network participation to ensure intended discovery universe:
    # 7 Bitumen suppliers (suppliers 1-7)
    # 3 Bitumen brokers (brokers 1-3)
    # 2 Base Oil suppliers (suppliers 8-9)
    # 3 Base Oil brokers (brokers 4-6)
    _ensure_commodity_network_participation(entities["orgs"], bitumen, base_oil)

    # 3. Seed / Ensure Canonical Hero Opportunity (OPP-2026-000124)
    hero_opp = _ensure_hero_opportunity(
        operator_user=operator_user,
        broker_org=broker_org,
        ext_cp=ext_cp,
        bitumen=bitumen,
        bitumen_schema=bitumen_schema,
    )

    # 4. Seed / Ensure Canonical Hero RFQ (500 MT Bitumen 60/70)
    hero_rfq = _ensure_hero_rfq(
        buyer_user=buyer_user,
        buyer_org=buyer_org,
        bitumen=bitumen,
        bitumen_schema=bitumen_schema,
    )

    # 5. Ensure Initial Matching Run for Hero RFQ
    matching_run = _ensure_hero_matching_run(
        hero_rfq=hero_rfq,
        buyer_user=buyer_user,
        buyer_org=buyer_org,
    )

    # 6. Verify Critical Boundaries
    _verify_hero_boundary_invariants(hero_rfq, hero_opp, ext_cp)

    candidates_qs = matching_run.candidates.all()
    suppliers_count = candidates_qs.filter(lane=CandidateLane.POTENTIAL_SUPPLIER).count()
    brokers_count = candidates_qs.filter(lane=CandidateLane.BROKER_PATH).count()
    direct_supply_count = candidates_qs.filter(lane=CandidateLane.DIRECT_SUPPLY).count()

    summary = {
        "version": HERO_SEED_VERSION,
        "hero_buyer": buyer_org.name,
        "hero_supplier_1": supplier_1_org.name,
        "hero_supplier_2": supplier_2_org.name,
        "hero_broker": broker_org.name,
        "hero_external_counterparty": ext_cp.company_name,
        "hero_opportunity_identifier": hero_opp.identifier,
        "hero_opportunity_status": hero_opp.status,
        "hero_rfq_id": str(hero_rfq.id),
        "hero_rfq_status": hero_rfq.status,
        "matching_run_id": str(matching_run.id),
        "matching_suppliers_count": suppliers_count,
        "matching_brokers_count": brokers_count,
        "matching_direct_supply_count": direct_supply_count,
    }

    if stdout:
        stdout.write(
            f"Hero Scenario Seed complete: RFQ={hero_rfq.id} "
            f"Matching=[{suppliers_count} Suppliers, {brokers_count} Brokers] "
            f"Opportunity={hero_opp.identifier} ({hero_opp.status})"
        )

    return summary


def _ensure_commodity_network_participation(orgs: Dict[str, Organization], bitumen: CommodityDefinition, base_oil: Any) -> None:
    """Ensure exact commodity participation so Bitumen discovery produces 7 Suppliers & 3 Brokers."""
    participation_map = {
        "supplier_1": ["bitumen"],
        "supplier_2": ["bitumen"],
        "supplier_3": ["bitumen", "base_oil"],
        "supplier_4": ["bitumen"],
        "supplier_5": ["bitumen"],
        "supplier_6": ["bitumen"],
        "supplier_7": ["bitumen", "base_oil"],
        "supplier_8": ["base_oil"],
        "supplier_9": ["base_oil"],
        "broker_1": ["bitumen"],
        "broker_2": ["bitumen"],
        "broker_3": ["bitumen"],
        "broker_4": ["base_oil"],
        "broker_5": ["base_oil"],
        "broker_6": ["base_oil"],
    }

    for org_key, comm_codes in participation_map.items():
        org = orgs.get(org_key)
        if not org:
            continue
        valid_ids = []
        for code in comm_codes:
            if code == "bitumen" and bitumen:
                oc, _ = OrganizationCommodity.objects.get_or_create(organization=org, commodity=bitumen)
                valid_ids.append(oc.id)
            elif code == "base_oil" and base_oil:
                oc, _ = OrganizationCommodity.objects.get_or_create(organization=org, commodity=base_oil)
                valid_ids.append(oc.id)
        OrganizationCommodity.objects.filter(organization=org).exclude(id__in=valid_ids).delete()


def _ensure_hero_opportunity(
    *,
    operator_user: Any,
    broker_org: Organization,
    ext_cp: ExternalCounterparty,
    bitumen: CommodityDefinition,
    bitumen_schema: CommoditySchemaVersion,
) -> Opportunity:
    """Ensure the canonical Hero Supply Opportunity exists in Captured status."""
    existing = (
        Opportunity.objects.filter(identifier=HERO_OPP_IDENTIFIER).first()
        or Opportunity.objects.filter(notes__contains=HERO_OPP_TAG).first()
    )
    if existing:
        return existing

    opp = create_opportunity(
        identifier=HERO_OPP_IDENTIFIER,
        direction=OpportunityDirection.SUPPLY,
        external_counterparty_id=ext_cp.id,
        commodity_id=bitumen.id,
        schema_version_id=bitumen_schema.id,
        specifications={"penetration_grade": "60/70"},
        quantity=Decimal("500.000"),
        unit="MT",
        indicative_price=Decimal("375.00"),
        currency="USD",
        delivery_window_start=date(2026, 10, 1),
        delivery_window_end=date(2026, 10, 31),
        payment_terms="LC 30 Days",
        geography="UAE / Jebel Ali",
        notes=f"{HERO_OPP_TAG} [OPP-2026-00124] Canonical Hero Broker-referred supply opportunity from Demo Brokerage.",
        source=OpportunitySource.BROKER_REFERRAL,
        broker_id=broker_org.id,
        created_by=operator_user,
    )
    return opp


def _ensure_hero_rfq(
    *,
    buyer_user: Any,
    buyer_org: Organization,
    bitumen: CommodityDefinition,
    bitumen_schema: CommoditySchemaVersion,
) -> RFQ:
    """Ensure the canonical Hero RFQ exists in Published status."""
    existing = RFQ.objects.filter(notes__contains=HERO_RFQ_TAG).first()
    if existing:
        return existing

    rfq = RFQService.create_draft(
        user=buyer_user,
        data={
            "commodity_id": bitumen.id,
            "schema_version_id": bitumen_schema.id,
            "specifications": {"penetration_grade": "60/70"},
            "quantity": Decimal("500.000"),
            "unit": "MT",
            "target_price": Decimal("380.00"),
            "currency": "USD",
            "payment_terms": "LC 30 Days",
            "incoterm": "FOB",
            "origin": "Iran",
            "destination": "Bandar Abbas",
            "delivery_window_start": date(2026, 10, 15),
            "delivery_window_end": date(2026, 11, 15),
            "submission_deadline": timezone.now() + timedelta(days=30),
            "inspection_required": True,
            "visibility": RFQVisibility.PUBLIC,
            "notes": f"{HERO_RFQ_TAG} 500 MT Bitumen 60/70 Hero procurement RFQ.",
        },
        organization_hint=buyer_org.id,
    )
    rfq = RFQLifecycleService.publish(rfq.id, expected_version=rfq.version, actor=buyer_user)
    return rfq


def _ensure_hero_matching_run(
    *,
    hero_rfq: RFQ,
    buyer_user: Any,
    buyer_org: Organization,
) -> MatchingRun:
    """Ensure a deterministic matching run exists for the Hero RFQ under Buyer audience."""
    existing_run = (
        MatchingRun.objects.filter(rfq=hero_rfq, audience=MatchingAudience.BUYER)
        .order_by("-generated_at")
        .first()
    )
    if existing_run:
        return existing_run

    actor_scope = ActorScope(user=buyer_user, organization=buyer_org)
    run = MatchingRunService.execute_matching_run(
        rfq_id=hero_rfq.id,
        audience=MatchingAudience.BUYER,
        actor_scope=actor_scope,
    )
    return run


def _verify_hero_boundary_invariants(
    hero_rfq: RFQ,
    hero_opp: Opportunity,
    ext_cp: ExternalCounterparty,
) -> None:
    """Verify that T1302 does not pre-complete any Hero flow milestones."""
    # 1. Hero RFQ must have NO offers submitted yet (offers are submitted during T1307 E2E)
    hero_offers_count = Offer.objects.filter(rfq=hero_rfq).count()
    if hero_offers_count > 0:
        raise AssertionError(
            f"Boundary violation: Hero RFQ {hero_rfq.id} already has {hero_offers_count} offers. "
            "T1302 must NOT pre-complete hero offers."
        )

    # 2. Hero RFQ must have NO deal associated
    hero_deals_count = Deal.objects.filter(rfq=hero_rfq).count()
    if hero_deals_count > 0:
        raise AssertionError(
            f"Boundary violation: Hero RFQ {hero_rfq.id} has {hero_deals_count} deals. "
            "T1302 must NOT pre-complete hero deals."
        )

    # 3. Hero Opportunity must be in Captured status
    if hero_opp.status != OpportunityStatus.CAPTURED:
        raise AssertionError(
            f"Boundary violation: Hero Opportunity {hero_opp.identifier} is in '{hero_opp.status}'. "
            "Expected 'Captured' for qualification during Hero flow."
        )

    # 4. ExternalCounterparty must NOT have a platform User or Organization account
    if User.objects.filter(email=ext_cp.email).exists():
        raise AssertionError(
            f"Boundary violation: External counterparty email '{ext_cp.email}' exists as platform User."
        )
    if Organization.objects.filter(name=ext_cp.company_name).exists():
        raise AssertionError(
            f"Boundary violation: External counterparty '{ext_cp.company_name}' exists as platform Organization."
        )
