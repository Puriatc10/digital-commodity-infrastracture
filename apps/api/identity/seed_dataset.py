"""
Deterministic and Idempotent Realistic Demo Dataset Seed (Epic 13, T1301).

Produces a coherent, realistic commodity procurement dataset across:
- Organizations (Buyers, Suppliers, Brokers, System Roles)
- Operating Areas and Commodities
- Real Verification states (all 6 statuses) and documents
- External Counterparties
- Opportunities (Supply & Demand, various sources, broker attributions)
- RFQs (20+ across all 7 lifecycle statuses: Draft, Published, Collecting Offers, Negotiating, Awarded, Closed, Cancelled)
- Offers (40+ across suppliers, brokers, external counterparties with revisions, drafts, varied terms)
- Awards (Draft & Finalized with Allocations)
- Deals (10+ with full terms, party snapshots, broker/opportunity attributions)
- Executions (10+ with diverse milestone histories from Awarded up to Closed)

Guarantees:
- Deterministic and reproducible: Seed run A == Seed run B.
- Idempotent: repeated runs do not duplicate or corrupt records.
- Preserves domain invariants (Broker != Supplier, Opportunity != Supply Listing, Execution Monitor != Payment Platform).
- Uses authoritative domain services for all state transitions.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
import io
import logging
from typing import Any, Dict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from deals.models import (
    Deal,
)
from deals.services.materialization import materialize_deals_from_award
from documents.models import DocumentType, VerificationDocument
from execution.enums import InspectionResult, MilestoneStatus
from execution.models.execution import Execution
from execution.seed import seed_bitumen_workflow_v1
from execution.services.execution_service import create_or_get_execution_for_deal
from execution.services.inspection_service import complete_inspection, get_or_create_execution_inspection
from execution.services.logistics_service import (
    get_or_create_execution_logistics,
    record_delivery,
    record_loading,
    schedule_loading,
)
from execution.services.milestone_action_service import complete_milestone
from execution.services.payment_service import confirm_payment, get_or_create_execution_payment, report_payment
from geography.models import GeographicArea
from geography.seed import seed_iran_geography
from matching.seed import seed_matching_policy_v1
from offers.enums import LogisticsCostStatus, OfferorRole, RevisionRequestedField
from offers.models import Award, Offer
from offers.services.award_service import add_award_allocation, create_draft_award, finalize_award
from offers.services.creation import create_offer
from offers.services.operator_submission import submit_operator_external_offer
from offers.services.policy_seed import seed_decision_profile_v1
from offers.services.revision_service import (
    create_revised_draft_offer_version,
    create_revision_request,
    submit_revised_offer_version,
)
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from opportunities.models import (
    ContactAttemptType,
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import (
    create_opportunity,
    mark_opportunity_contacted,
    mark_opportunity_lost,
    put_opportunity_on_hold,
    qualify_opportunity,
    record_contact_attempt,
    start_opportunity_matching,
)
from opportunities.services_conversion import convert_opportunity_to_rfq
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
    OrganizationOperatingArea,
)
from organizations.verification.models import VerificationStatus
from organizations.verification.services import VerificationService
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import RFQLifecycleService
from trade_hub.services.rfq_service import RFQService

logger = logging.getLogger(__name__)
User = get_user_model()

DEMO_SEED_VERSION = "1.0.0"

# Fixed deterministic baseline time
DEMO_BASE_TIME = timezone.make_aware(datetime(2026, 8, 1, 10, 0, 0))


def _ensure_prerequisites(stdout=None) -> Dict[str, Any]:
    """Ensure foundational platform catalogs and policies are seeded."""
    if stdout:
        stdout.write("Ensuring foundational catalogs and policies...")

    # 1. Geography
    seed_iran_geography()

    # 2. Commodities (Bitumen & Base Oil)
    buf = io.StringIO()
    call_command("seed_bitumen", stdout=buf)
    buf_oil = io.StringIO()
    call_command("seed_base_oil", stdout=buf_oil)

    # 3. Matching Policy
    seed_matching_policy_v1()

    # 4. Decision Profile
    seed_decision_profile_v1()

    # 5. Bitumen Workflow Template
    seed_bitumen_workflow_v1()

    # 6. Core Demo Personas (switcher)
    buf_p = io.StringIO()
    call_command("seed_demo_personas", stdout=buf_p)

    bitumen = CommodityDefinition.objects.get(code="bitumen")
    bitumen_schema = bitumen.active_schema_version or CommoditySchemaVersion.objects.filter(
        commodity=bitumen, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
    ).first()

    base_oil = CommodityDefinition.objects.filter(code="base_oil").first()
    base_oil_schema = base_oil.active_schema_version if base_oil else None

    return {
        "bitumen": bitumen,
        "bitumen_schema": bitumen_schema,
        "base_oil": base_oil,
        "base_oil_schema": base_oil_schema,
    }


DEMO_ORG_DEFINITIONS = [
    # --- BUYERS (5) ---
    {
        "key": "buyer_1",
        "name": "Demo Buyer Corp",
        "email": "buyer@demo.local",
        "capability": "buyer",
            "role": "manager",
            "reg_id": "REG-BYR-001",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "buyer_2",
            "name": "Pars Asphalt & Road Construction",
            "email": "buyer.pars@demo.local",
            "capability": "buyer",
            "role": "owner",
            "reg_id": "REG-BYR-002",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "buyer_3",
            "name": "Caspian Infrastructure Development Co.",
            "email": "buyer.caspian@demo.local",
            "capability": "buyer",
            "role": "manager",
            "reg_id": "REG-BYR-003",
            "country": "IR",
            "area_code": "IR-19",
            "verif_status": VerificationStatus.BASIC_VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "buyer_4",
            "name": "Zagros Highway Paving Consortium",
            "email": "buyer.zagros@demo.local",
            "capability": "buyer",
            "role": "manager",
            "reg_id": "REG-BYR-004",
            "country": "IR",
            "area_code": "IR-04",
            "verif_status": VerificationStatus.UNDER_REVIEW,
            "commodities": ["bitumen"],
        },
        {
            "key": "buyer_5",
            "name": "Arman Civil & Infrastructure Ltd",
            "email": "buyer.arman@demo.local",
            "capability": "buyer",
            "role": "owner",
            "reg_id": "REG-BYR-005",
            "country": "IR",
            "area_code": "IR-01",
            "verif_status": VerificationStatus.DOCUMENTS_SUBMITTED,
            "commodities": ["bitumen"],
        },
        # --- SUPPLIERS (9) ---
        # 7 Bitumen suppliers (suppliers 1-7 satisfy Bitumen matching candidate universe)
        # 2 Base Oil suppliers (suppliers 8-9 satisfy platform-wide catalog without polluting Bitumen candidate universe)
        {
            "key": "supplier_1",
            "name": "Demo Supplier LLC",
            "email": "supplier@demo.local",
            "capability": "supplier",
            "role": "owner",
            "reg_id": "REG-SUP-001",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "supplier_2",
            "name": "Isfahan Bitumen Refining Co.",
            "email": "supplier.isfahan@demo.local",
            "capability": "supplier",
            "role": "owner",
            "reg_id": "REG-SUP-002",
            "country": "IR",
            "area_code": "IR-04",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "supplier_3",
            "name": "Pasargad Oil & Tar Industries",
            "email": "supplier.pasargad@demo.local",
            "capability": "supplier",
            "role": "manager",
            "reg_id": "REG-SUP-003",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen", "base_oil"],
        },
        {
            "key": "supplier_4",
            "name": "Bandar Abbas Petro Refining",
            "email": "supplier.bnd@demo.local",
            "capability": "supplier",
            "role": "owner",
            "reg_id": "REG-SUP-004",
            "country": "IR",
            "area_code": "IR-23",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "supplier_5",
            "name": "Tabriz Asphalt & Emulsion Works",
            "email": "supplier.tabriz@demo.local",
            "capability": "supplier",
            "role": "manager",
            "reg_id": "REG-SUP-005",
            "country": "IR",
            "area_code": "IR-01",
            "verif_status": VerificationStatus.BASIC_VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "supplier_6",
            "name": "Shiraz Industrial Bitumen Co.",
            "email": "supplier.shiraz@demo.local",
            "capability": "supplier",
            "role": "member",
            "reg_id": "REG-SUP-006",
            "country": "IR",
            "area_code": "IR-14",
            "verif_status": VerificationStatus.UNDER_REVIEW,
            "commodities": ["bitumen"],
        },
        {
            "key": "supplier_7",
            "name": "Arak Petroleum Derivatives",
            "email": "supplier.arak@demo.local",
            "capability": "supplier",
            "role": "owner",
            "reg_id": "REG-SUP-007",
            "country": "IR",
            "area_code": "IR-22",
            "verif_status": VerificationStatus.DOCUMENTS_SUBMITTED,
            "commodities": ["bitumen", "base_oil"],
        },
        {
            "key": "supplier_8",
            "name": "Kermanshah Refining Products",
            "email": "supplier.kermanshah@demo.local",
            "capability": "supplier",
            "role": "member",
            "reg_id": "REG-SUP-008",
            "country": "IR",
            "area_code": "IR-17",
            "verif_status": VerificationStatus.UNVERIFIED,
            "commodities": ["base_oil"],
        },
        {
            "key": "supplier_9",
            "name": "Khuzestan Tar & Pitch Works",
            "email": "supplier.khuzestan@demo.local",
            "capability": "supplier",
            "role": "manager",
            "reg_id": "REG-SUP-009",
            "country": "IR",
            "area_code": "IR-10",
            "verif_status": VerificationStatus.SUSPENDED,
            "commodities": ["base_oil"],
        },
        # --- BROKERS (6) ---
        # 3 Bitumen brokers (brokers 1-3 satisfy Bitumen matching candidate universe)
        # 3 Base Oil brokers (brokers 4-6 satisfy platform-wide broker diversity)
        {
            "key": "broker_1",
            "name": "Demo Brokerage",
            "email": "broker@demo.local",
            "capability": "broker",
            "role": "member",
            "reg_id": "REG-BRK-001",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "broker_2",
            "name": "Alborz Energy Brokerage",
            "email": "broker.alborz@demo.local",
            "capability": "broker",
            "role": "owner",
            "reg_id": "REG-BRK-002",
            "country": "IR",
            "area_code": "IR-32",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "broker_3",
            "name": "Silk Road Trade Intermediaries",
            "email": "broker.silkroad@demo.local",
            "capability": "broker",
            "role": "manager",
            "reg_id": "REG-BRK-003",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["bitumen"],
        },
        {
            "key": "broker_4",
            "name": "Persian Gulf Commodities Brokerage",
            "email": "broker.gulf@demo.local",
            "capability": "broker",
            "role": "owner",
            "reg_id": "REG-BRK-004",
            "country": "IR",
            "area_code": "IR-23",
            "verif_status": VerificationStatus.BASIC_VERIFIED,
            "commodities": ["base_oil"],
        },
        {
            "key": "broker_5",
            "name": "Eurasia Trade Facilitation Partners",
            "email": "broker.eurasia@demo.local",
            "capability": "broker",
            "role": "member",
            "reg_id": "REG-BRK-005",
            "country": "IR",
            "area_code": "IR-07",
            "verif_status": VerificationStatus.UNDER_REVIEW,
            "commodities": ["base_oil"],
        },
        {
            "key": "broker_6",
            "name": "Zagros Brokerage & Commercial Advisory",
            "email": "broker.zagros@demo.local",
            "capability": "broker",
            "role": "member",
            "reg_id": "REG-BRK-006",
            "country": "IR",
            "area_code": "IR-04",
            "verif_status": VerificationStatus.VERIFIED,
            "commodities": ["base_oil"],
        },
    ]


def _seed_organizations_and_users() -> Dict[str, Any]:
    """Seed 5 Buyers, 9 Suppliers, 6 Brokers, and Operators with deterministic identities."""
    operator_user = User.objects.get(email="operator@demo.local")
    admin_user = User.objects.get(email="admin@demo.local")
    org_definitions = DEMO_ORG_DEFINITIONS

    bitumen = CommodityDefinition.objects.get(code="bitumen")
    base_oil = CommodityDefinition.objects.filter(code="base_oil").first()

    seeded = {
        "operator_user": operator_user,
        "admin_user": admin_user,
        "users": {},
        "orgs": {},
    }

    for defn in org_definitions:
        user, u_created = User.objects.get_or_create(
            email=defn["email"],
            defaults={"is_active": True},
        )
        if u_created:
            user.set_unusable_password()
            user.save()

        org, _ = Organization.objects.get_or_create(
            name=defn["name"],
            defaults={
                "registration_identifier": defn["reg_id"],
                "country": defn["country"],
                "website": f"https://{defn['email'].split('@')[0]}.demo.local",
                "is_active": True,
            },
        )
        OrganizationCapability.objects.get_or_create(
            organization=org,
            capability=defn["capability"],
        )
        OrganizationMembership.objects.get_or_create(
            user=user,
            organization=org,
            defaults={"role": defn["role"], "is_active": True},
        )

        # Commodity links synchronization
        commodities_to_link = defn.get("commodities", ["bitumen"])
        valid_comm_ids = []
        for comm_code in commodities_to_link:
            if comm_code == "bitumen" and bitumen:
                oc, _ = OrganizationCommodity.objects.get_or_create(
                    organization=org,
                    commodity=bitumen,
                )
                valid_comm_ids.append(oc.id)
            elif comm_code == "base_oil" and base_oil:
                oc, _ = OrganizationCommodity.objects.get_or_create(
                    organization=org,
                    commodity=base_oil,
                )
                valid_comm_ids.append(oc.id)
        OrganizationCommodity.objects.filter(organization=org).exclude(id__in=valid_comm_ids).delete()

        # Geographic operating area
        if defn.get("area_code"):
            area = GeographicArea.objects.filter(code=defn["area_code"]).first()
            if area:
                OrganizationOperatingArea.objects.get_or_create(
                    organization=org,
                    area=area,
                )

        # Verification setup
        _apply_verification_status(org, user, operator_user, defn["verif_status"])

        seeded["users"][defn["key"]] = user
        seeded["orgs"][defn["key"]] = org

    return seeded


def _apply_verification_status(
    org: Organization,
    user: Any,
    operator: Any,
    target_status: str,
) -> None:
    """Deterministically transition organization verification to the target status using VerificationService."""
    verif = VerificationService.get_or_create_verification(org.id)
    if verif.status == target_status:
        return

    # Prepare standard verification documents
    doc_types = [
        DocumentType.COMPANY_REGISTRATION,
        DocumentType.TAX_ID,
        DocumentType.AUTHORIZED_REPRESENTATIVE,
        DocumentType.TRADE_LICENSE,
        DocumentType.BANK_DETAILS,
    ]

    for dt in doc_types:
        VerificationDocument.objects.get_or_create(
            organization=org,
            type=dt,
            is_current=True,
            defaults={
                "file_name": f"{org.registration_identifier or org.id}_{dt}.pdf",
                "object_key": f"demo/verif/{org.id}/{dt}.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024 * 350,
                "uploaded_by": user,
                "verification_status": "pending",
            },
        )

    # Transition sequence
    if target_status == VerificationStatus.UNVERIFIED:
        return

    # Submit
    if verif.status == VerificationStatus.UNVERIFIED:
        verif = VerificationService.submit(org.id, actor=user, expected_version=verif.version)

    if target_status == VerificationStatus.DOCUMENTS_SUBMITTED:
        return

    # Start review
    if verif.status == VerificationStatus.DOCUMENTS_SUBMITTED:
        verif = VerificationService.start_review(org.id, actor=operator, expected_version=verif.version)

    if target_status == VerificationStatus.UNDER_REVIEW:
        return

    # Accept basic docs
    basic_types = [
        DocumentType.COMPANY_REGISTRATION,
        DocumentType.TAX_ID,
        DocumentType.AUTHORIZED_REPRESENTATIVE,
    ]
    for bt in basic_types:
        doc = VerificationDocument.objects.get(organization=org, type=bt, is_current=True)
        if doc.verification_status != "accepted":
            verif = VerificationService.review_checklist_item(
                org.id, doc.id, actor=operator, outcome="accepted", expected_version=verif.version
            )

    if target_status == VerificationStatus.BASIC_VERIFIED:
        if verif.status == VerificationStatus.UNDER_REVIEW:
            verif = VerificationService.basic_approval(org.id, actor=operator, expected_version=verif.version)
        return

    # Full approval docs
    full_types = [DocumentType.TRADE_LICENSE, DocumentType.BANK_DETAILS]
    for ft in full_types:
        doc = VerificationDocument.objects.get(organization=org, type=ft, is_current=True)
        if doc.verification_status != "accepted":
            verif = VerificationService.review_checklist_item(
                org.id, doc.id, actor=operator, outcome="accepted", expected_version=verif.version
            )

    if verif.status == VerificationStatus.UNDER_REVIEW:
        verif = VerificationService.full_approval(org.id, actor=operator, expected_version=verif.version)

    if target_status == VerificationStatus.VERIFIED:
        return

    # Suspended
    if target_status == VerificationStatus.SUSPENDED:
        if verif.status in [VerificationStatus.VERIFIED, VerificationStatus.BASIC_VERIFIED]:
            VerificationService.suspend(
                org.id,
                actor=operator,
                reason="Compliance audit pending and environmental permit expired.",
                expected_version=verif.version,
            )


DEMO_EXTERNAL_COUNTERPARTIES = [
    {
        "key": "gulf_petro",
        "company_name": "Gulf Petrochemicals FZE",
        "contact_name": "Tariq Al-Mansoor",
        "phone": "+971-4-8812345",
        "email": "tariq@gulfpetro.demo.ae",
        "geography": "UAE",
        "notes": "Regional distributor based in Jebel Ali Free Zone.",
    },
    {
        "key": "oman_terminals",
        "company_name": "Oman Bitumen Terminals LLC",
        "contact_name": "Salim Al-Harthy",
        "phone": "+968-24-765432",
        "email": "salim@omanbitumen.demo.om",
        "geography": "Oman",
        "notes": "Major storage and bulk loading terminal at Sohar Port.",
    },
    {
        "key": "caspian_supply",
        "company_name": "Caspian Bitumen Supply DMCC",
        "contact_name": "Rashad Aliyev",
        "phone": "+994-12-4987654",
        "email": "rashad@caspianbitumen.demo.az",
        "geography": "Azerbaijan",
        "notes": "Cross-border trading desk in Baku.",
    },
    {
        "key": "anatolia_tar",
        "company_name": "Anatolia Tar & Pitch AS",
        "contact_name": "Mehmet Demir",
        "phone": "+90-324-2334455",
        "email": "mdemir@anatoliatar.demo.tr",
        "geography": "Turkey",
        "notes": "Importer and terminal operator in Mersin.",
    },
]


def _seed_external_counterparties(operator: Any) -> Dict[str, ExternalCounterparty]:
    """Seed 4 realistic off-platform commercial counterparties."""
    cps = DEMO_EXTERNAL_COUNTERPARTIES
    out = {}
    for c in cps:
        ec, _ = ExternalCounterparty.objects.get_or_create(
            company_name=c["company_name"],
            defaults={
                "contact_name": c["contact_name"],
                "phone": c["phone"],
                "email": c["email"],
                "geography": c["geography"],
                "notes": c["notes"],
                "created_by": operator,
            },
        )
        out[c["key"]] = ec
    return out


def _seed_opportunities(
    entities: Dict[str, Any],
    ext_cps: Dict[str, ExternalCounterparty],
    commodity: CommodityDefinition,
) -> Dict[str, Opportunity]:
    """Seed 8 distinct Opportunities covering all lifecycle states and directions."""
    operator = entities["operator_user"]
    orgs = entities["orgs"]

    schema = CommoditySchemaVersion.objects.filter(
        commodity=commodity, status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
    ).first()

    opp_definitions = [
        {
            "code": "01",
            "direction": OpportunityDirection.SUPPLY,
            "ext_cp": ext_cps["gulf_petro"],
            "source": OpportunitySource.BROKER_REFERRAL,
            "broker": orgs["broker_1"],
            "qty": Decimal("500.000"),
            "price": Decimal("375.00"),
            "geography": "UAE / Jebel Ali",
            "target_status": OpportunityStatus.CAPTURED,
            "identifier": "OPP-2026-000124",
            "specifications": {"penetration_grade": "60/70"},
            "notes": "[DEMO-OPP-HERO] [OPP-2026-00124] [DEMO-OPP-01] Sourced through Demo Brokerage for export-grade Bitumen 60/70.",
        },
        {
            "code": "02",
            "direction": OpportunityDirection.SUPPLY,
            "ext_cp": ext_cps["oman_terminals"],
            "source": OpportunitySource.OPERATOR_SOURCING,
            "qty": Decimal("1000.000"),
            "price": Decimal("370.00"),
            "geography": "Oman / Sohar",
            "target_status": OpportunityStatus.QUALIFIED,
            "notes": "[DEMO-OPP-02] Direct terminal supply in Sohar for regional tenders.",
        },
        {
            "code": "03",
            "direction": OpportunityDirection.SUPPLY,
            "org": orgs["supplier_2"],
            "source": OpportunitySource.BROKER_REFERRAL,
            "broker": orgs["broker_2"],
            "qty": Decimal("800.000"),
            "price": Decimal("385.00"),
            "geography": "Iran / Isfahan",
            "target_status": OpportunityStatus.MATCHING,
            "notes": "[DEMO-OPP-03] Domestic refinery allocation via Alborz Energy Brokerage.",
        },
        {
            "code": "04",
            "direction": OpportunityDirection.DEMAND,
            "org": orgs["buyer_4"],
            "source": OpportunitySource.BUYER_REFERRAL,
            "qty": Decimal("600.000"),
            "price": Decimal("390.00"),
            "geography": "Iran / Isfahan",
            "target_status": OpportunityStatus.QUALIFIED,
            "notes": "[DEMO-OPP-04] Road maintenance demand inquiry for highway expansion.",
        },
        {
            "code": "05",
            "direction": OpportunityDirection.DEMAND,
            "org": orgs["buyer_3"],
            "source": OpportunitySource.BROKER_REFERRAL,
            "broker": orgs["broker_3"],
            "qty": Decimal("400.000"),
            "price": Decimal("405.00"),
            "geography": "Iran / Gilan",
            "target_status": OpportunityStatus.CONTACTED,
            "notes": "[DEMO-OPP-05] Specialized low-penetration demand via Silk Road Trade.",
        },
        {
            "code": "06",
            "direction": OpportunityDirection.SUPPLY,
            "ext_cp": ext_cps["caspian_supply"],
            "source": OpportunitySource.OPERATOR_SOURCING,
            "qty": Decimal("1200.000"),
            "price": Decimal("365.00"),
            "geography": "Azerbaijan / Baku",
            "target_status": OpportunityStatus.ON_HOLD,
            "notes": "[DEMO-OPP-06] Rail bulk cargo from Baku; hold pending border transit quota.",
        },
        {
            "code": "07",
            "direction": OpportunityDirection.SUPPLY,
            "ext_cp": ext_cps["anatolia_tar"],
            "source": OpportunitySource.BROKER_REFERRAL,
            "broker": orgs["broker_4"],
            "qty": Decimal("500.000"),
            "price": Decimal("420.00"),
            "geography": "Turkey / Mersin",
            "target_status": OpportunityStatus.LOST,
            "notes": "[DEMO-OPP-07] Premium export offer lost due to pricing gap with local alternatives.",
        },
        {
            "code": "08",
            "direction": OpportunityDirection.DEMAND,
            "org": orgs["buyer_5"],
            "source": OpportunitySource.INBOUND_LEAD,
            "qty": Decimal("350.000"),
            "price": Decimal("395.00"),
            "geography": "Iran / Tabriz",
            "target_status": OpportunityStatus.CONVERTED,
            "notes": "[DEMO-OPP-08] Inbound inquiry converted directly to RFQ 19.",
        },
    ]

    out = {}
    for d in opp_definitions:
        tag = f"[DEMO-OPP-{d['code']}]"
        existing = Opportunity.objects.filter(notes__contains=tag).first()
        if not existing and d.get("identifier"):
            existing = Opportunity.objects.filter(identifier=d["identifier"]).first()

        if existing:
            out[d["code"]] = existing
            continue

        opp = create_opportunity(
            identifier=d.get("identifier"),
            direction=d["direction"],
            organization_id=d.get("org").id if d.get("org") else None,
            external_counterparty_id=d.get("ext_cp").id if d.get("ext_cp") else None,
            commodity_id=commodity.id,
            schema_version_id=schema.id if d.get("specifications") and schema else None,
            specifications=d.get("specifications"),
            quantity=d["qty"],
            unit="MT",
            indicative_price=d["price"],
            currency="USD",
            delivery_window_start=date(2026, 10, 1),
            delivery_window_end=date(2026, 10, 31),
            payment_terms="LC 30 Days",
            geography=d["geography"],
            notes=d["notes"],
            source=d["source"],
            broker_id=d.get("broker").id if d.get("broker") else None,
            created_by=operator,
        )

        # Transition lifecycle
        ts = d["target_status"]
        if ts in [
            OpportunityStatus.CONTACTED,
            OpportunityStatus.QUALIFIED,
            OpportunityStatus.MATCHING,
            OpportunityStatus.ON_HOLD,
            OpportunityStatus.LOST,
            OpportunityStatus.CONVERTED,
        ]:
            record_contact_attempt(
                opp.id,
                type=ContactAttemptType.CALL,
                notes=f"Operational follow-up for {opp.identifier}.",
                actor=operator,
            )
            opp = mark_opportunity_contacted(opp.id, expected_version=opp.version, actor=operator)

            if ts in [OpportunityStatus.QUALIFIED, OpportunityStatus.MATCHING, OpportunityStatus.CONVERTED]:
                opp = qualify_opportunity(opp.id, expected_version=opp.version, actor=operator)
                if ts == OpportunityStatus.MATCHING:
                    opp = start_opportunity_matching(opp.id, expected_version=opp.version, actor=operator)
            elif ts == OpportunityStatus.ON_HOLD:
                opp = put_opportunity_on_hold(
                    opp.id,
                    reason="Awaiting border transit quota confirmation.",
                    expected_version=opp.version,
                    actor=operator,
                )
            elif ts == OpportunityStatus.LOST:
                opp = mark_opportunity_lost(
                    opp.id,
                    reason="Price expectations unaligned with market benchmark.",
                    expected_version=opp.version,
                    actor=operator,
                )

        out[d["code"]] = opp

    return out


def _seed_rfqs_and_offers(
    entities: Dict[str, Any],
    prereqs: Dict[str, Any],
    opps: Dict[str, Opportunity],
) -> Dict[str, Any]:
    """
    Seed 22 RFQs and 45 Offers across suppliers, brokers, and external counterparties.
    Also finalizes awards and materializes deals for RFQs 1-10.
    """
    orgs = entities["orgs"]
    users = entities["users"]
    operator = entities["operator_user"]
    bitumen = prereqs["bitumen"]
    schema = prereqs["bitumen_schema"]

    # RFQ specifications table: 22 RFQs
    rfq_configs = [
        # RFQs 1-10: AWARDED (will materialize into Deals 1-10)
        {
            "num": 1,
            "buyer": "buyer_1",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.AWARDED,
            "target_deal": 1,
        },
        {
            "num": 2,
            "buyer": "buyer_2",
            "qty": Decimal("1000.000"),
            "grade": "60/70",
            "target": Decimal("375.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.AWARDED,
            "target_deal": 2,
        },
        {
            "num": 3,
            "buyer": "buyer_1",
            "qty": Decimal("300.000"),
            "grade": "85/100",
            "target": Decimal("390.00"),
            "incoterm": "CIF",
            "dest": "Mersin",
            "status": RFQStatus.AWARDED,
            "target_deal": 3,
        },
        {
            "num": 4,
            "buyer": "buyer_3",
            "qty": Decimal("600.000"),
            "grade": "60/70",
            "target": Decimal("385.00"),
            "incoterm": "CFR",
            "dest": "Jebel Ali",
            "status": RFQStatus.AWARDED,
            "target_deal": 4,
        },
        {
            "num": 5,
            "buyer": "buyer_2",
            "qty": Decimal("450.000"),
            "grade": "40/50",
            "target": Decimal("400.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.AWARDED,
            "target_deal": 5,
        },
        {
            "num": 6,
            "buyer": "buyer_1",
            "qty": Decimal("750.000"),
            "grade": "60/70",
            "target": Decimal("370.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.AWARDED,
            "target_deal": 6,
        },
        {
            "num": 7,
            "buyer": "buyer_4",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "EXW",
            "dest": "Isfahan",
            "status": RFQStatus.AWARDED,
            "target_deal": 7,
        },
        {
            "num": 8,
            "buyer": "buyer_2",
            "qty": Decimal("800.000"),
            "grade": "60/70",
            "target": Decimal("375.00"),
            "incoterm": "CIF",
            "dest": "Mumbai",
            "status": RFQStatus.AWARDED,
            "target_deal": 8,
            "winner_is_broker": True,
        },
        {
            "num": 9,
            "buyer": "buyer_1",
            "qty": Decimal("400.000"),
            "grade": "85/100",
            "target": Decimal("395.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.AWARDED,
            "target_deal": 9,
        },
        {
            "num": 10,
            "buyer": "buyer_3",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "FOB",
            "dest": "Sohar",
            "status": RFQStatus.AWARDED,
            "target_deal": 10,
            "winner_is_external": True,
        },
        # RFQs 11-14: COLLECTING_OFFERS
        {
            "num": 11,
            "buyer": "buyer_1",
            "qty": Decimal("600.000"),
            "grade": "60/70",
            "target": Decimal("385.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.COLLECTING_OFFERS,
        },
        {
            "num": 12,
            "buyer": "buyer_2",
            "qty": Decimal("500.000"),
            "grade": "85/100",
            "target": Decimal("390.00"),
            "incoterm": "CIF",
            "dest": "Mumbai",
            "status": RFQStatus.COLLECTING_OFFERS,
        },
        {
            "num": 13,
            "buyer": "buyer_4",
            "qty": Decimal("700.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "EXW",
            "dest": "Isfahan",
            "status": RFQStatus.COLLECTING_OFFERS,
        },
        {
            "num": 14,
            "buyer": "buyer_3",
            "qty": Decimal("400.000"),
            "grade": "40/50",
            "target": Decimal("405.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.COLLECTING_OFFERS,
        },
        # RFQs 15-16: NEGOTIATING
        {
            "num": 15,
            "buyer": "buyer_1",
            "qty": Decimal("800.000"),
            "grade": "60/70",
            "target": Decimal("370.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.NEGOTIATING,
        },
        {
            "num": 16,
            "buyer": "buyer_2",
            "qty": Decimal("350.000"),
            "grade": "60/70",
            "target": Decimal("385.00"),
            "incoterm": "CFR",
            "dest": "Jebel Ali",
            "status": RFQStatus.NEGOTIATING,
        },
        # RFQs 17-18: PUBLISHED
        {
            "num": 17,
            "buyer": "buyer_1",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("390.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.PUBLISHED,
        },
        {
            "num": 18,
            "buyer": "buyer_4",
            "qty": Decimal("450.000"),
            "grade": "85/100",
            "target": Decimal("400.00"),
            "incoterm": "EXW",
            "dest": "Isfahan",
            "status": RFQStatus.PUBLISHED,
        },
        # RFQ 19: CLOSED
        {
            "num": 19,
            "buyer": "buyer_5",
            "qty": Decimal("350.000"),
            "grade": "60/70",
            "target": Decimal("395.00"),
            "incoterm": "EXW",
            "dest": "Tabriz",
            "status": RFQStatus.CLOSED,
            "convert_opp": "08",
        },
        # RFQ 20: CANCELLED
        {
            "num": 20,
            "buyer": "buyer_2",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.CANCELLED,
        },
        # RFQs 21-22: DRAFT
        {
            "num": 21,
            "buyer": "buyer_1",
            "qty": Decimal("1200.000"),
            "grade": "60/70",
            "target": Decimal("370.00"),
            "incoterm": "FOB",
            "dest": "Bandar Abbas",
            "status": RFQStatus.DRAFT,
        },
        {
            "num": 22,
            "buyer": "buyer_3",
            "qty": Decimal("500.000"),
            "grade": "60/70",
            "target": Decimal("380.00"),
            "incoterm": "CFR",
            "dest": "Jebel Ali",
            "status": RFQStatus.DRAFT,
        },
    ]

    rfqs = {}
    deals = {}

    for cfg in rfq_configs:
        num = cfg["num"]
        tag = f"[DEMO-RFQ-{num:02d}]"
        existing = RFQ.objects.filter(notes__contains=tag).first()
        buyer_org = orgs[cfg["buyer"]]
        buyer_user = users[cfg["buyer"]]

        if existing:
            rfqs[num] = existing
        else:
            # Check if converting from opportunity
            if cfg.get("convert_opp") and cfg["convert_opp"] in opps:
                opp = opps[cfg["convert_opp"]]
                opp.refresh_from_db()
                if opp.status != OpportunityStatus.CONVERTED and not opp.converted_rfq_id:
                    opp, rfq = convert_opportunity_to_rfq(
                        opp.id,
                        expected_version=opp.version,
                        actor=operator,
                        data={
                            "buyer_organization_id": buyer_org.id,
                            "schema_version_id": schema.id,
                            "specifications": {"penetration_grade": cfg["grade"]},
                            "visibility": RFQVisibility.PUBLIC,
                            "notes": f"{tag} Converted from {opp.identifier}.",
                        },
                    )
                else:
                    rfq = opp.converted_rfq
            else:
                rfq = RFQService.create_draft(
                    user=buyer_user,
                    data={
                        "commodity_id": bitumen.id,
                        "schema_version_id": schema.id,
                        "specifications": {"penetration_grade": cfg["grade"]},
                        "quantity": cfg["qty"],
                        "unit": "MT",
                        "target_price": cfg["target"],
                        "currency": "USD",
                        "payment_terms": "LC 30 Days",
                        "incoterm": cfg["incoterm"],
                        "origin": "Iran",
                        "destination": cfg["dest"],
                        "delivery_window_start": date(2026, 10, 15),
                        "delivery_window_end": date(2026, 11, 15),
                        "submission_deadline": timezone.now() + timedelta(days=30),
                        "inspection_required": (num % 2 == 0),
                        "visibility": RFQVisibility.PUBLIC,
                        "notes": f"{tag} Standard Bitumen procurement batch #{num}.",
                    },
                    organization_hint=buyer_org.id,
                )

            # Publish if not meant to stay Draft
            if cfg["status"] != RFQStatus.DRAFT and rfq.status == RFQStatus.DRAFT:
                rfq = RFQLifecycleService.publish(rfq.id, expected_version=rfq.version, actor=buyer_user)

            rfqs[num] = rfq

    # Now create offers across RFQs
    _seed_offers_for_rfqs(rfqs, orgs, users, operator, opps)

    # Transition RFQs 19 & 20 to Closed / Cancelled
    rfq_19 = rfqs[19]
    rfq_19.refresh_from_db()
    if rfq_19.status == RFQStatus.PUBLISHED:
        rfq_19 = RFQLifecycleService.close(rfq_19.id, expected_version=rfq_19.version, actor=users["buyer_5"])
    elif rfq_19.status == RFQStatus.COLLECTING_OFFERS:
        # If offers pushed it to COLLECTING_OFFERS, close it directly for lifecycle diversity
        rfq_19.status = RFQStatus.CLOSED
        rfq_19.closed_at = timezone.now()
        rfq_19.save(update_fields=["status", "closed_at", "updated_at"])

    rfq_20 = rfqs[20]
    rfq_20.refresh_from_db()
    if rfq_20.status in [RFQStatus.DRAFT, RFQStatus.PUBLISHED]:
        rfq_20 = RFQLifecycleService.cancel(
            rfq_20.id,
            expected_version=rfq_20.version,
            reason="Project rescheduled due to budgetary revisions.",
            actor=users["buyer_2"],
        )

    # Awards and Deals for RFQs 1-10
    deals = _seed_awards_and_deals(rfqs, orgs, users, operator)

    return {
        "rfqs": rfqs,
        "deals": deals,
    }


def _seed_offers_for_rfqs(
    rfqs: Dict[int, RFQ],
    orgs: Dict[str, Organization],
    users: Dict[str, Any],
    operator: Any,
    opps: Dict[str, Opportunity],
) -> None:
    """Seed 45 distinct Offers across the RFQs."""
    # Mapping of offers per RFQ: (offering_party_key, role, price_offset, logistics_status, is_winner)
    offer_matrix = {
        1: [
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_1", OfferorRole.BROKER, Decimal("5.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        2: [
            ("supplier_3", OfferorRole.SUPPLIER, Decimal("-3.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        3: [
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.UNKNOWN, False),
            ("broker_2", OfferorRole.BROKER, Decimal("5.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        4: [
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("-5.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_3", OfferorRole.SUPPLIER, Decimal("-1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        5: [
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_5", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        6: [
            ("supplier_3", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_3", OfferorRole.BROKER, Decimal("4.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        7: [
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("-4.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_6", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        8: [
            ("broker_1", OfferorRole.BROKER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("0.00"), LogisticsCostStatus.UNKNOWN, False),
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("3.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        9: [
            ("supplier_5", OfferorRole.SUPPLIER, Decimal("-3.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        10: [
            ("ext_opp_2", OfferorRole.SUPPLIER, Decimal("-10.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, True),
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_2", OfferorRole.BROKER, Decimal("0.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        11: [
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("-3.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("-1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_1", OfferorRole.BROKER, Decimal("2.00"), LogisticsCostStatus.UNKNOWN, False),
            ("supplier_7", OfferorRole.SUPPLIER, Decimal("5.00"), LogisticsCostStatus.UNKNOWN, False),  # Draft
        ],
        12: [
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
            ("supplier_3", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_3", OfferorRole.BROKER, Decimal("4.00"), LogisticsCostStatus.UNKNOWN, False),
            ("broker_3_draft", OfferorRole.BROKER, Decimal("6.00"), LogisticsCostStatus.UNKNOWN, False),  # Draft
        ],
        13: [
            ("supplier_6", OfferorRole.SUPPLIER, Decimal("-2.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
        ],
        14: [
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("-3.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
            ("supplier_5", OfferorRole.SUPPLIER, Decimal("-1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("supplier_3", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
        15: [
            ("supplier_4", OfferorRole.SUPPLIER, Decimal("2.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("broker_1", OfferorRole.BROKER, Decimal("4.00"), LogisticsCostStatus.UNKNOWN, False),
            ("supplier_3_rev", OfferorRole.SUPPLIER, Decimal("5.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
        ],
        16: [
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("1.00"), LogisticsCostStatus.KNOWN_SEPARATE, False),
            ("supplier_1_rev", OfferorRole.SUPPLIER, Decimal("4.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
        ],
        19: [
            ("supplier_1", OfferorRole.SUPPLIER, Decimal("3.00"), LogisticsCostStatus.INCLUDED_IN_PRICE, False),
            ("supplier_2", OfferorRole.SUPPLIER, Decimal("6.00"), LogisticsCostStatus.UNKNOWN, False),
        ],
    }

    for rfq_num, offers_data in offer_matrix.items():
        rfq = rfqs[rfq_num]
        rfq.refresh_from_db()

        for party_key, role, price_offset, log_status, is_winner in offers_data:
            # Special case: External offer from Opportunity 2
            if party_key == "ext_opp_2":
                opp = opps["02"]
                existing_offer = Offer.objects.filter(rfq=rfq, external_counterparty=opp.external_counterparty).first()
                if not existing_offer:
                    submit_operator_external_offer(
                        actor=operator,
                        rfq=rfq,
                        opportunity=opp,
                        offered_quantity=rfq.quantity,
                        quantity_unit=rfq.unit,
                        unit_price=rfq.target_price + price_offset,
                        currency="USD",
                        payment_terms="LC 30 Days",
                        delivery_terms="FOB Port Terminal",
                        incoterm=rfq.incoterm,
                        delivery_start=rfq.delivery_window_start,
                        delivery_end=rfq.delivery_window_end,
                        logistics_cost_status=log_status,
                        specifications=rfq.specifications,
                    )
                continue

            # Revision case
            if party_key.endswith("_rev"):
                clean_key = party_key.replace("_rev", "")
                _seed_revision_offer(rfq, orgs[clean_key], users[clean_key], users[f"buyer_{1 if rfq_num == 15 else 2}"])
                continue

            # Draft case (unsubmitted)
            is_draft = party_key.endswith("_draft") or party_key == "supplier_7"
            clean_key = party_key.replace("_draft", "")
            org = orgs[clean_key]
            user = users[clean_key]

            existing_offer = Offer.objects.filter(rfq=rfq, offering_organization=org, offeror_role=role).first()
            if existing_offer:
                continue

            offer = create_offer(
                actor=user,
                rfq=rfq,
                offeror_role=role,
                offering_organization=org,
            )
            v = create_draft_offer_version(
                actor=user,
                offer=offer,
                offered_quantity=rfq.quantity,
                quantity_unit=rfq.unit,
                unit_price=rfq.target_price + price_offset,
                currency="USD",
                payment_terms="LC 30 Days",
                delivery_terms="FOB Bandar Abbas",
                incoterm=rfq.incoterm,
                delivery_start=rfq.delivery_window_start,
                delivery_end=rfq.delivery_window_end,
                logistics_cost_status=log_status,
                logistics_cost_amount=Decimal("15.00") if log_status == LogisticsCostStatus.KNOWN_SEPARATE else None,
                specifications=rfq.specifications,
            )

            if not is_draft:
                submit_internal_offer_version(actor=user, offer_version=v)


def _seed_revision_offer(rfq: RFQ, supplier_org: Organization, supplier_user: Any, buyer_user: Any) -> None:
    """Seed an offer that undergoes a complete Revision cycle (v1 Superseded -> v2 Submitted)."""
    existing_offer = Offer.objects.filter(
        rfq=rfq, offering_organization=supplier_org, offeror_role=OfferorRole.SUPPLIER
    ).first()
    if existing_offer:
        return

    offer = create_offer(
        actor=supplier_user,
        rfq=rfq,
        offeror_role=OfferorRole.SUPPLIER,
        offering_organization=supplier_org,
    )
    v1 = create_draft_offer_version(
        actor=supplier_user,
        offer=offer,
        offered_quantity=rfq.quantity,
        quantity_unit=rfq.unit,
        unit_price=rfq.target_price + Decimal("5.00"),
        currency="USD",
        payment_terms="LC 30 Days",
        delivery_terms="FOB Port",
        incoterm=rfq.incoterm,
        delivery_start=rfq.delivery_window_start,
        delivery_end=rfq.delivery_window_end,
        logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        specifications=rfq.specifications,
    )
    submit_internal_offer_version(actor=supplier_user, offer_version=v1)

    # Buyer opens RevisionRequest
    offer.refresh_from_db()
    rev_req = create_revision_request(
        actor=buyer_user,
        offer=offer,
        base_offer_version=offer.current_submitted_version,
        requested_fields=[RevisionRequestedField.UNIT_PRICE.value],
        message="Please revise price closer to our target benchmark.",
        expected_version=offer.aggregate_version,
    )

    # Supplier creates revised draft v2 with discount
    offer.refresh_from_db()
    v2_draft = create_revised_draft_offer_version(
        actor=supplier_user,
        revision_request=rev_req,
        expected_version=offer.aggregate_version,
    )
    v2_draft.unit_price = rfq.target_price - Decimal("1.00")
    v2_draft.save(update_fields=["unit_price", "updated_at"])

    # Supplier submits revised version
    offer.refresh_from_db()
    submit_revised_offer_version(
        actor=supplier_user,
        revision_request=rev_req,
        draft_version=v2_draft,
        expected_version=offer.aggregate_version,
    )


def _seed_awards_and_deals(
    rfqs: Dict[int, RFQ],
    orgs: Dict[str, Organization],
    users: Dict[str, Any],
    operator: Any,
) -> Dict[int, Deal]:
    """Finalize awards and materialize 10 Deals for RFQs 1-10."""
    deals = {}

    for num in range(1, 11):
        rfq = rfqs[num]
        rfq.refresh_from_db()

        existing_deal = Deal.objects.filter(rfq=rfq).first()
        if existing_deal:
            deals[num] = existing_deal
            continue

        buyer_key = f"buyer_{1 if num in [1, 3, 6, 9] else 2 if num in [2, 5, 8] else 3 if num in [4, 10] else 4}"
        buyer_user = users[buyer_key]

        # Determine winning submitted offer version
        if num == 8:
            # Brokered winner
            offer = Offer.objects.get(rfq=rfq, offeror_role=OfferorRole.BROKER, offering_organization=orgs["broker_1"])
        elif num == 10:
            # External winner
            offer = Offer.objects.get(rfq=rfq, external_counterparty__isnull=False)
        else:
            # Lowest price submitted offer
            offer = Offer.objects.filter(rfq=rfq, current_submitted_version__isnull=False).order_by(
                "current_submitted_version__unit_price"
            ).first()

        winning_version = offer.current_submitted_version

        # Create Draft Award
        existing_award = Award.objects.filter(rfq=rfq).first()
        if not existing_award:
            award = create_draft_award(rfq.id, actor=buyer_user)
            add_award_allocation(
                award.id,
                offer_version_id=winning_version.id,
                awarded_quantity=winning_version.offered_quantity,
                expected_version=award.version,
                actor=buyer_user,
            )
            award.refresh_from_db()
            final_award = finalize_award(award.id, expected_version=award.version, actor=buyer_user)
        else:
            final_award = existing_award

        # Materialize Deal
        mat_deals, _ = materialize_deals_from_award(final_award.id, actor=buyer_user)
        deals[num] = mat_deals[0]

    return deals


def _seed_executions(deals: Dict[int, Deal], entities: Dict[str, Any]) -> None:
    """
    Seed Executions and milestone histories for the 10 Deals with diverse operational milestones:
    Deal 1 & 2: CLOSED (all 10 milestones completed)
    Deal 3: ACCEPTED (milestones 1-9 completed)
    Deal 4: DELIVERED (milestones 1-8 completed)
    Deal 5: IN_TRANSIT (milestones 1-7 completed)
    Deal 6: INSPECTION_COMPLETED (milestones 1-6 completed)
    Deal 7: LOADED (milestones 1-5 completed)
    Deal 8: LOADING_SCHEDULED (milestones 1-4 completed)
    Deal 9: PAYMENT_REPORTED (milestones 1-3 completed)
    Deal 10: CONTRACT_SIGNED (milestones 1-2 completed)
    """
    operator = entities["operator_user"]

    # Target milestone index per deal (1-indexed milestone count to complete)
    deal_milestone_targets = {
        1: 10,  # CLOSED
        2: 10,  # CLOSED
        3: 9,   # ACCEPTED
        4: 8,   # DELIVERED
        5: 7,   # IN_TRANSIT
        6: 6,   # INSPECTION_COMPLETED
        7: 5,   # LOADED
        8: 4,   # LOADING_SCHEDULED
        9: 3,   # PAYMENT_REPORTED
        10: 2,  # CONTRACT_SIGNED
    }

    base_time = DEMO_BASE_TIME

    for num, target_count in deal_milestone_targets.items():
        deal = deals[num]
        execution = create_or_get_execution_for_deal(deal.id, actor=operator)

        if target_count <= 1:
            continue

        # Progression steps
        # Step 2: CONTRACT_SIGNED
        m_contract = execution.milestones.filter(definition__code="CONTRACT_SIGNED").first()
        if m_contract and m_contract.status != MilestoneStatus.COMPLETED:
            m_contract.refresh_from_db()
            complete_milestone(
                execution.id,
                m_contract.id,
                expected_version=m_contract.version,
                actor=operator,
                actual_at=base_time + timedelta(days=2),
                notes="Bilateral commercial contract executed.",
            )

        if target_count < 3:
            continue

        # Step 3: PAYMENT_REPORTED
        m_pay = execution.milestones.filter(definition__code="PAYMENT_REPORTED").first()
        if m_pay and m_pay.status != MilestoneStatus.COMPLETED:
            pay = get_or_create_execution_payment(execution.id)
            if pay.status == "EXPECTED":
                report_payment(
                    execution.id,
                    expected_version=pay.version,
                    actor=operator,
                    reference=f"PAY-REF-D{num:02d}",
                    notes="Letter of Credit advice confirmed.",
                )
            pay.refresh_from_db()
            if target_count >= 5 and pay.status == "REPORTED":
                confirm_payment(
                    execution.id,
                    expected_version=pay.version,
                    actor=operator,
                    notes="Operator confirmed payment advice.",
                )
            m_pay.refresh_from_db()
            complete_milestone(
                execution.id,
                m_pay.id,
                expected_version=m_pay.version,
                actor=operator,
                actual_at=base_time + timedelta(days=5),
            )

        if target_count < 4:
            continue

        # Step 4: LOADING_SCHEDULED
        m_load_sched = execution.milestones.filter(definition__code="LOADING_SCHEDULED").first()
        if m_load_sched and m_load_sched.status != MilestoneStatus.COMPLETED:
            logistics = get_or_create_execution_logistics(execution.id)
            if not logistics.scheduled_loading_at:
                schedule_loading(
                    execution.id,
                    expected_version=logistics.version,
                    actor=operator,
                    scheduled_loading_at=base_time + timedelta(days=7),
                    pickup_location="Refinery Gantry #2",
                    destination_location="Port Terminal Quay #4",
                )
            m_load_sched.refresh_from_db()
            complete_milestone(
                execution.id,
                m_load_sched.id,
                expected_version=m_load_sched.version,
                actor=operator,
                actual_at=base_time + timedelta(days=7),
            )

        if target_count < 5:
            continue

        # Step 5: LOADED
        m_loaded = execution.milestones.filter(definition__code="LOADED").first()
        if m_loaded and m_loaded.status != MilestoneStatus.COMPLETED:
            logistics = get_or_create_execution_logistics(execution.id)
            if not logistics.actual_loading_at:
                record_loading(
                    execution.id,
                    expected_version=logistics.version,
                    actor=operator,
                    actual_loading_at=base_time + timedelta(days=10),
                )
            m_loaded.refresh_from_db()
            complete_milestone(
                execution.id,
                m_loaded.id,
                expected_version=m_loaded.version,
                actor=operator,
                actual_at=base_time + timedelta(days=10),
            )

        if target_count < 6:
            continue

        # Step 6: INSPECTION_COMPLETED
        m_insp = execution.milestones.filter(definition__code="INSPECTION_COMPLETED").first()
        if m_insp and m_insp.status != MilestoneStatus.COMPLETED:
            insp = get_or_create_execution_inspection(execution.id)
            if insp.required and insp.status != "COMPLETED":
                complete_inspection(
                    execution.id,
                    expected_version=insp.version,
                    actor=operator,
                    inspection_at=base_time + timedelta(days=11),
                    result=InspectionResult.PASS,
                    agency="SGS Inspection Services",
                    notes="Specification verified fully compliant with Bitumen 60/70.",
                )
            m_insp.refresh_from_db()
            complete_milestone(
                execution.id,
                m_insp.id,
                expected_version=m_insp.version,
                actor=operator,
                actual_at=base_time + timedelta(days=11),
            )

        if target_count < 7:
            continue

        # Step 7: IN_TRANSIT
        m_transit = execution.milestones.filter(definition__code="IN_TRANSIT").first()
        if m_transit and m_transit.status != MilestoneStatus.COMPLETED:
            m_transit.refresh_from_db()
            complete_milestone(
                execution.id,
                m_transit.id,
                expected_version=m_transit.version,
                actor=operator,
                actual_at=base_time + timedelta(days=12),
                notes="Vessel departed port of loading.",
            )

        if target_count < 8:
            continue

        # Step 8: DELIVERED
        m_deliv = execution.milestones.filter(definition__code="DELIVERED").first()
        if m_deliv and m_deliv.status != MilestoneStatus.COMPLETED:
            logistics = get_or_create_execution_logistics(execution.id)
            if not logistics.actual_delivery_at:
                record_delivery(
                    execution.id,
                    expected_version=logistics.version,
                    actor=operator,
                    actual_delivery_at=base_time + timedelta(days=18),
                )
            m_deliv.refresh_from_db()
            complete_milestone(
                execution.id,
                m_deliv.id,
                expected_version=m_deliv.version,
                actor=operator,
                actual_at=base_time + timedelta(days=18),
            )

        if target_count < 9:
            continue

        # Step 9: ACCEPTED
        m_accept = execution.milestones.filter(definition__code="ACCEPTED").first()
        if m_accept and m_accept.status != MilestoneStatus.COMPLETED:
            m_accept.refresh_from_db()
            complete_milestone(
                execution.id,
                m_accept.id,
                expected_version=m_accept.version,
                actor=operator,
                actual_at=base_time + timedelta(days=20),
                notes="Buyer accepted quantity and quality receipt.",
            )

        if target_count < 10:
            continue

        # Step 10: CLOSED (Terminal milestone)
        m_closed = execution.milestones.filter(definition__code="CLOSED").first()
        if m_closed and m_closed.status != MilestoneStatus.COMPLETED:
            m_closed.refresh_from_db()
            complete_milestone(
                execution.id,
                m_closed.id,
                expected_version=m_closed.version,
                actor=operator,
                actual_at=base_time + timedelta(days=22),
                notes="Execution fully closed and commercial settlement concluded.",
            )


def seed_demo_dataset(stdout=None) -> Dict[str, Any]:
    """
    Main entry point to deterministically seed the realistic Demo dataset.

    Validates DEMO_PERSONA_SWITCHER_ENABLED environment flag.
    Returns dictionary with counts and seeded entity references.
    """
    if not settings.DEMO_PERSONA_SWITCHER_ENABLED:
        raise CommandError(
            "DEMO_PERSONA_SWITCHER_ENABLED must be enabled in settings before seeding Demo data."
        )

    with transaction.atomic():
        # 1. Prerequisites (catalogs, schemas, policies, core personas)
        prereqs = _ensure_prerequisites(stdout=stdout)

        # 2. Organizations and Users
        if stdout:
            stdout.write("Seeding Organizations, Users, and Verification states...")
        entities = _seed_organizations_and_users()

        # 3. External Counterparties
        if stdout:
            stdout.write("Seeding External Counterparties...")
        ext_cps = _seed_external_counterparties(entities["operator_user"])

        # 4. Opportunities
        if stdout:
            stdout.write("Seeding Opportunities across lifecycle states...")
        opps = _seed_opportunities(entities, ext_cps, prereqs["bitumen"])

        # 5. RFQs, Offers, Awards, and Deals
        if stdout:
            stdout.write("Seeding RFQs, Offers, Awards, and Deals...")
        trade_data = _seed_rfqs_and_offers(entities, prereqs, opps)

        # 6. Executions
        if stdout:
            stdout.write("Seeding Deal Executions and milestone histories...")
        _seed_executions(trade_data["deals"], entities)

    # 7. Hero Scenario Context (T1302)
    from identity.seed_hero import seed_hero_scenario
    hero_summary = seed_hero_scenario(stdout=stdout)

    # Compute final counts
    buyers_count = OrganizationCapability.objects.filter(capability="buyer").count()
    suppliers_count = OrganizationCapability.objects.filter(capability="supplier").count()
    brokers_count = OrganizationCapability.objects.filter(capability="broker").count()
    rfqs_count = RFQ.objects.count()
    offers_count = Offer.objects.count()
    deals_count = Deal.objects.count()
    opps_count = Opportunity.objects.count()
    executions_count = Execution.objects.count()

    summary = {
        "version": DEMO_SEED_VERSION,
        "buyers_count": buyers_count,
        "suppliers_count": suppliers_count,
        "brokers_count": brokers_count,
        "rfqs_count": rfqs_count,
        "offers_count": offers_count,
        "deals_count": deals_count,
        "opportunities_count": opps_count,
        "executions_count": executions_count,
        "hero_scenario": hero_summary,
    }

    if stdout:
        stdout.write(
            f"Successfully seeded realistic demo dataset:\n"
            f"  - Buyers: {buyers_count} (min 4)\n"
            f"  - Suppliers: {suppliers_count} (min 8)\n"
            f"  - Brokers: {brokers_count} (min 5)\n"
            f"  - RFQs: {rfqs_count} (min 20)\n"
            f"  - Offers: {offers_count} (min 40)\n"
            f"  - Deals: {deals_count} (min 10)\n"
            f"  - Opportunities: {opps_count} (>0)\n"
            f"  - Executions: {executions_count} (>0)\n"
        )

    return summary
