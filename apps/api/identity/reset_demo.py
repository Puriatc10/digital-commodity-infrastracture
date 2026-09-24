"""
Deterministic and Safe Demo Reset Mechanism (Epic 13, T1308).

Restores the Demo environment from any mutated or partially played state
back to the canonical, approved seed baseline established by T1301 and T1302.

Boundary & Invariant Guarantees:
- Destructive reset is restricted strictly to Demo-managed data.
- Non-Demo data (independent organizations, real users, non-demo RFQs,
  unrelated opportunities, independent deals) is strictly protected and preserved.
- Refuses to execute if DEMO_PERSONA_SWITCHER_ENABLED is False or if
  a production settings module is detected.
- Wrapped in an atomic transaction; any failure rolls back completely, leaving
  no partial or corrupted demo state.
- Disables execution model pre_delete signals strictly within the reset transaction
  to clean up demo execution history, then safely restores them.
- Deterministic and idempotent: repeated consecutive runs converge to the identical
  logical baseline with zero accumulation or progressive counter drift.
- Prepares the database for Hero Flow E2E execution (T1307): Hero RFQ in Published
  status with zero offers, zero deals, and Hero Opportunity in Captured status.
"""

from contextlib import contextmanager
import logging
import os
from typing import Any, Dict, Set

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import pre_delete

from deals.models import (
    Deal,
    DealAttribution,
    DealBrokerAttribution,
    DealCostSnapshot,
    DealOpportunityAttribution,
    DealPartySnapshot,
    DealTermsSnapshot,
)
from documents.models import VerificationDocument
from execution.models import (
    Execution,
    ExecutionDocument,
    ExecutionInspection,
    ExecutionIssue,
    ExecutionLogistics,
    ExecutionMilestone,
    ExecutionPayment,
    protect_execution_deletion,
    protect_execution_document_deletion,
    protect_execution_inspection_deletion,
    protect_execution_issue_deletion,
    protect_execution_logistics_deletion,
    protect_execution_milestone_deletion,
    protect_execution_payment_deletion,
)
from identity.models import SystemRoleAssignment
from identity.seed_dataset import (
    DEMO_EXTERNAL_COUNTERPARTIES,
    DEMO_ORG_DEFINITIONS,
    seed_demo_dataset,
)
from identity.seed_hero import (
    HERO_OPP_IDENTIFIER,
    HERO_OPP_TAG,
    HERO_RFQ_TAG,
)
from matching.models import MatchingRun
from offers.models import Award, AwardAllocation, Offer, OfferVersion, RevisionRequest
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityContactAttempt,
    OpportunityIdentifierSequence,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
    OrganizationOperatingArea,
)
from organizations.verification.models import (
    OrganizationVerification,
    VerificationChecklistReview,
    VerificationDecision,
)
from trade_hub.models import RFQ, RFQInvitation, SupplyListing

logger = logging.getLogger(__name__)
User = get_user_model()

# Canonical Demo Identifiers
CANONICAL_DEMO_ORG_REG_IDS: Set[str] = {
    defn["reg_id"] for defn in DEMO_ORG_DEFINITIONS if "reg_id" in defn
}
CANONICAL_DEMO_ORG_NAMES: Set[str] = {defn["name"] for defn in DEMO_ORG_DEFINITIONS}
CANONICAL_DEMO_EMAILS: Set[str] = {defn["email"] for defn in DEMO_ORG_DEFINITIONS} | {
    "operator@demo.local",
    "admin@demo.local",
}
CANONICAL_DEMO_COUNTERPARTIES: Set[str] = {
    c["company_name"] for c in DEMO_EXTERNAL_COUNTERPARTIES
}


def validate_demo_reset_environment() -> None:
    """
    Validate that the current environment explicitly and safely permits a Demo reset.

    Rejection criteria:
    1. DEMO_PERSONA_SWITCHER_ENABLED is False or missing.
    2. Active settings module is 'config.settings.production' or contains 'production'.
    3. DJANGO_SETTINGS_MODULE environment variable indicates production.
    """
    if not getattr(settings, "DEMO_PERSONA_SWITCHER_ENABLED", False):
        raise CommandError(
            "Demo reset is only permitted when DEMO_PERSONA_SWITCHER_ENABLED is True. "
            "Ensure you are in a local development or demo environment."
        )

    settings_module = (
        getattr(settings, "SETTINGS_MODULE", "")
        or os.environ.get("DJANGO_SETTINGS_MODULE", "")
    ).lower()

    if "production" in settings_module:
        raise CommandError(
            "Demo reset is strictly forbidden in production configuration. "
            f"Active settings module: '{settings_module}'."
        )


@contextmanager
def temporary_disconnect_execution_signals():
    """
    Temporarily disconnect execution model pre_delete signals during demo reset.

    Execution models enforce historical preservation via pre_delete signals
    that reject ordinary business deletion. During an authorized demo reset,
    these signals are disconnected within this context manager and guaranteed
    to be reconnected upon exit.
    """
    receivers = [
        (protect_execution_deletion, Execution),
        (protect_execution_milestone_deletion, ExecutionMilestone),
        (protect_execution_logistics_deletion, ExecutionLogistics),
        (protect_execution_inspection_deletion, ExecutionInspection),
        (protect_execution_payment_deletion, ExecutionPayment),
        (protect_execution_document_deletion, ExecutionDocument),
        (protect_execution_issue_deletion, ExecutionIssue),
    ]
    for receiver, sender in receivers:
        pre_delete.disconnect(receiver, sender=sender)
    try:
        yield
    finally:
        for receiver, sender in receivers:
            pre_delete.connect(receiver, sender=sender)


def _clear_demo_transactional_data(stdout=None) -> Dict[str, int]:
    """
    Identify and cleanly remove all Demo-owned transactional state.

    Strictly preserves non-demo organizations, non-demo users, non-demo RFQs,
    non-demo opportunities, and non-demo deals.
    """
    # 1. Identify Demo Organizations
    non_demo_users = User.objects.exclude(email__endswith="@demo.local")
    demo_orgs = Organization.objects.filter(
        (
            Q(registration_identifier__in=CANONICAL_DEMO_ORG_REG_IDS)
            | Q(name__in=CANONICAL_DEMO_ORG_NAMES)
            | Q(registration_identifier__startswith="REG-BYR-")
            | Q(registration_identifier__startswith="REG-SUP-")
            | Q(registration_identifier__startswith="REG-BRK-")
            | Q(website__endswith=".demo.local")
            | Q(memberships__user__email__endswith="@demo.local")
        )
        & ~Q(memberships__user__in=non_demo_users)
    ).distinct()

    # 2. Identify Demo Users
    demo_users = User.objects.filter(email__endswith="@demo.local")

    # 3. Identify Demo External Counterparties
    demo_counterparties = ExternalCounterparty.objects.filter(
        Q(company_name__in=CANONICAL_DEMO_COUNTERPARTIES)
        | Q(email__endswith=".demo.ae")
        | Q(email__endswith=".demo.om")
        | Q(email__endswith=".demo.az")
        | Q(email__endswith=".demo.tr")
        | Q(created_by__in=demo_users)
    ).distinct()

    # 4. Identify Demo RFQs
    demo_rfqs = RFQ.objects.filter(
        Q(notes__contains="[DEMO-RFQ-")
        | Q(notes__contains=HERO_RFQ_TAG)
        | Q(organization__in=demo_orgs)
        | Q(created_by__in=demo_users)
    ).distinct()

    # 5. Identify Demo Opportunities
    demo_opps = Opportunity.objects.filter(
        Q(notes__contains="[DEMO-OPP-")
        | Q(notes__contains=HERO_OPP_TAG)
        | Q(identifier=HERO_OPP_IDENTIFIER)
        | Q(identifier="OPP-2026-00124")
        | Q(organization__in=demo_orgs)
        | Q(external_counterparty__in=demo_counterparties)
        | Q(created_by__in=demo_users)
    ).distinct()

    # 6. Identify Demo Deals
    demo_deals = Deal.objects.filter(
        Q(rfq__in=demo_rfqs)
        | Q(buyer_organization__in=demo_orgs)
        | Q(seller_organization__in=demo_orgs)
        | Q(seller_external_counterparty__in=demo_counterparties)
    ).distinct()

    # 7. Identify Demo Executions
    demo_executions = Execution.objects.filter(deal__in=demo_deals).distinct()

    # 8. Identify Demo Awards & Offers
    demo_awards = Award.objects.filter(rfq__in=demo_rfqs).distinct()
    demo_offers = Offer.objects.filter(
        Q(rfq__in=demo_rfqs)
        | Q(offering_organization__in=demo_orgs)
        | Q(external_counterparty__in=demo_counterparties)
        | Q(created_by__in=demo_users)
    ).distinct()

    exec_count = demo_executions.count()
    deals_count = demo_deals.count()
    offers_count = demo_offers.count()
    rfqs_count = demo_rfqs.count()
    opps_count = demo_opps.count()

    if stdout:
        stdout.write(
            f"Clearing Demo state: {exec_count} executions, "
            f"{deals_count} deals, {offers_count} offers, "
            f"{rfqs_count} RFQs, {opps_count} opportunities..."
        )

    # --- EXECUTE DELETION IN CAREFUL DEPENDENCY ORDER ---

    # A. Delete Executions (disconnect pre_delete signals safely)
    with temporary_disconnect_execution_signals():
        ExecutionIssue.objects.filter(execution__in=demo_executions).delete()
        ExecutionDocument.objects.filter(execution__in=demo_executions).delete()
        ExecutionPayment.objects.filter(execution__in=demo_executions).delete()
        ExecutionInspection.objects.filter(execution__in=demo_executions).delete()
        ExecutionLogistics.objects.filter(execution__in=demo_executions).delete()
        ExecutionMilestone.objects.filter(execution__in=demo_executions).delete()
        Execution.objects.filter(id__in=demo_executions).delete()

    # B. Delete Deal Sub-models and Deals (models.PROTECT)
    DealCostSnapshot.objects.filter(deal_terms_snapshot__deal__in=demo_deals).delete()
    DealTermsSnapshot.objects.filter(deal__in=demo_deals).delete()
    DealPartySnapshot.objects.filter(deal__in=demo_deals).delete()
    DealBrokerAttribution.objects.filter(deal__in=demo_deals).delete()
    DealOpportunityAttribution.objects.filter(deal__in=demo_deals).delete()
    DealAttribution.objects.filter(deal__in=demo_deals).delete()
    Deal.objects.filter(id__in=demo_deals).delete()

    # C. Delete AwardAllocations and Awards
    AwardAllocation.objects.filter(award__in=demo_awards).delete()
    Award.objects.filter(id__in=demo_awards).delete()

    # D. Delete Offer RevisionRequests, Version Pointers, Versions, and Offers
    RevisionRequest.objects.filter(offer__in=demo_offers).delete()
    Offer.objects.filter(id__in=demo_offers).update(
        current_submitted_version=None
    )
    OfferVersion.objects.filter(offer__in=demo_offers).delete()
    Offer.objects.filter(id__in=demo_offers).delete()

    # E. Delete Matching Runs & Candidates
    MatchingRun.objects.filter(rfq__in=demo_rfqs).delete()

    # F. Delete Opportunities & Contact Attempts (before deleting RFQs to safely clear converted_rfq references)
    OpportunityContactAttempt.objects.filter(opportunity__in=demo_opps).delete()
    Opportunity.objects.filter(id__in=demo_opps).delete()

    # G. Reset OpportunityIdentifierSequence for year 2026 deterministically
    _reset_opportunity_sequence(year=2026)

    # H. Delete RFQ Invitations, Supply Listings, and Demo RFQs
    RFQInvitation.objects.filter(rfq__in=demo_rfqs).delete()
    SupplyListing.objects.filter(organization__in=demo_orgs).delete()
    RFQ.objects.filter(id__in=demo_rfqs).delete()

    # I. Delete Demo External Counterparties
    ExternalCounterparty.objects.filter(id__in=demo_counterparties).delete()

    # J. Delete Verification Records for Demo Organizations
    VerificationChecklistReview.objects.filter(
        verification__organization__in=demo_orgs
    ).delete()
    VerificationDecision.objects.filter(
        verification__organization__in=demo_orgs
    ).delete()
    OrganizationVerification.objects.filter(organization__in=demo_orgs).delete()
    VerificationDocument.objects.filter(organization__in=demo_orgs).delete()

    # K. Clean up Extra Demo Organizations and reset Canonical Organizations
    Organization.objects.filter(id__in=demo_orgs).exclude(
        registration_identifier__in=CANONICAL_DEMO_ORG_REG_IDS,
        name__in=CANONICAL_DEMO_ORG_NAMES,
    ).delete()

    # Reset capabilities, areas, and memberships on remaining canonical demo orgs
    OrganizationCapability.objects.filter(organization__in=demo_orgs).delete()
    OrganizationOperatingArea.objects.filter(organization__in=demo_orgs).delete()
    OrganizationMembership.objects.filter(organization__in=demo_orgs).delete()

    # Restore canonical profile fields on the 20 Demo Organizations
    for defn in DEMO_ORG_DEFINITIONS:
        org = Organization.objects.filter(
            Q(registration_identifier=defn["reg_id"]) | Q(name=defn["name"])
        ).first()
        if org:
            org.name = defn["name"]
            org.registration_identifier = defn["reg_id"]
            org.country = defn["country"]
            org.website = f"https://{defn['email'].split('@')[0]}.demo.local"
            org.is_active = True
            org.save(
                update_fields=[
                    "name",
                    "registration_identifier",
                    "country",
                    "website",
                    "is_active",
                    "updated_at",
                ]
            )

    # L. Clean up Users: delete non-canonical demo users, reset canonical demo users
    User.objects.filter(email__endswith="@demo.local").exclude(
        email__in=CANONICAL_DEMO_EMAILS
    ).delete()

    for email in CANONICAL_DEMO_EMAILS:
        user = User.objects.filter(email=email).first()
        if user:
            user.is_active = True
            user.set_unusable_password()
            user.save(update_fields=["is_active", "password"])

    # Clean up non-canonical system roles on demo users
    SystemRoleAssignment.objects.filter(user__in=demo_users).exclude(
        user__email__in=["operator@demo.local", "admin@demo.local"]
    ).delete()

    return {
        "executions_cleared": exec_count,
        "deals_cleared": deals_count,
        "offers_cleared": offers_count,
        "rfqs_cleared": rfqs_count,
        "opportunities_cleared": opps_count,
    }


def _reset_opportunity_sequence(year: int = 2026) -> None:
    """
    Deterministically reset OpportunityIdentifierSequence for the specified year.

    If any non-demo opportunities remain for the year, sets next_value to
    max(existing sequences) + 1. Otherwise, resets next_value to 1.
    """
    remaining = Opportunity.objects.filter(
        identifier__startswith=f"OPP-{year:04d}-"
    ).values_list("identifier", flat=True)

    max_seq = 0
    for ident in remaining:
        parts = ident.split("-")
        if len(parts) >= 3 and parts[2].isdigit():
            max_seq = max(max_seq, int(parts[2]))

    target_next_value = max_seq + 1

    seq_rec, _ = OpportunityIdentifierSequence.objects.get_or_create(
        year=year, defaults={"next_value": target_next_value}
    )
    if seq_rec.next_value != target_next_value:
        seq_rec.next_value = target_next_value
        seq_rec.save(update_fields=["next_value", "updated_at"])


def reset_demo_environment(stdout=None) -> Dict[str, Any]:
    """
    Canonical entry point to reset and restore the Demo environment (T1308).

    Validates environment safety guards, clears Demo-managed transactional state,
    and runs the canonical seed flow (T1301 + T1302) inside an atomic transaction.
    """
    validate_demo_reset_environment()

    if stdout:
        stdout.write("Environment verified: Demo persona switcher active and safe.")

    with transaction.atomic():
        # Step 1: Clean Demo-owned transactional state
        cleared_info = _clear_demo_transactional_data(stdout=stdout)

        # Step 2: Invoke the canonical existing seed flow
        if stdout:
            stdout.write("Invoking canonical seed flow (T1301 + T1302)...")
        seed_summary = seed_demo_dataset(stdout=stdout)

    result = {
        "status": "success",
        "cleared": cleared_info,
        "seed_summary": seed_summary,
    }

    if stdout:
        stdout.write(
            "Demo environment successfully reset:\n"
            f"  - Buyers: {seed_summary['buyers_count']}\n"
            f"  - Suppliers: {seed_summary['suppliers_count']}\n"
            f"  - Brokers: {seed_summary['brokers_count']}\n"
            f"  - RFQs: {seed_summary['rfqs_count']}\n"
            f"  - Offers: {seed_summary['offers_count']}\n"
            f"  - Deals: {seed_summary['deals_count']}\n"
            f"  - Opportunities: {seed_summary['opportunities_count']}\n"
            f"  - Executions: {seed_summary['executions_count']}\n"
            f"  - Hero RFQ Status: {seed_summary['hero_scenario']['hero_rfq_status']}\n"
            f"  - Hero Opportunity Status: {seed_summary['hero_scenario']['hero_opportunity_status']}\n"
        )

    return result
