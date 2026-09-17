from typing import List, Sequence

from matching.candidates.authorization import (
    MatchingAuthorizationError,
    MatchingPrivacyViolationError,
)
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot
from matching.enums import CandidateKind, CandidateLane, MatchingAudience
from matching.rules.geography import GeographicEvidenceRole
from opportunities.models import Opportunity, OpportunityDirection, OpportunityStatus


class SupplyOpportunityCandidateProvider:
    """
    Candidate provider for the Direct Supply lane backed by Qualified Supply Opportunities.

    CRITICAL PRIVACY INVARIANT:
    Must execute strictly for OPERATOR audience. Buyer candidate discovery must never
    query, materialize, or project Opportunity candidates.

    Counterparty privacy:
    External counterparties are sanitized to company name and identifier only.
    Phone numbers, emails, contact names, contact attempts, and internal operational
    notes are strictly excluded from the snapshot.
    """

    def find_candidates(
        self,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Discover Qualified Supply Opportunities for Operator discovery.
        """
        # 1. Privacy barrier: hard rejection if invoked under BUYER audience
        if context.audience != MatchingAudience.OPERATOR:
            raise MatchingPrivacyViolationError(
                "SupplyOpportunityCandidateProvider must never execute under BUYER audience."
            )

        # 2. Authorization barrier: Operator or Admin system authority required
        if not actor_scope.is_operator_or_admin:
            raise MatchingAuthorizationError(
                "Operator privileges required to discover Supply Opportunity candidates."
            )

        # 3. Filter strictly for Qualified Supply opportunities for this commodity, excluding self
        opportunities = (
            Opportunity.objects.filter(
                direction=OpportunityDirection.SUPPLY,
                status=OpportunityStatus.QUALIFIED,
                commodity_id=context.commodity_id,
            )
            .exclude(organization_id=context.rfq_owner_organization_id)
            .select_related(
                "organization",
                "external_counterparty",
                "commodity",
                "schema_version",
                "origin_area",
                "broker",
            )
            .order_by("id")
        )

        candidates: List[CandidateSnapshot] = []
        for opp in opportunities:
            # Deterministic specs sorting
            specs = (
                dict(sorted(opp.specifications.items()))
                if opp.specifications
                else {}
            )

            # Structured geography from T0702
            has_structured_area = opp.origin_area_id is not None
            geo_evidence = {
                "evidence_role": GeographicEvidenceRole.SUPPLY_LOCATION,
                "area_id": str(opp.origin_area_id) if has_structured_area else None,
                "area_code": opp.origin_area.code if has_structured_area else "",
                "has_only_free_text": bool(opp.geography and not has_structured_area),
                "operating_areas": (),
                "organization_hq_only": False,
            }

            # Safe counterparty projection: NO phone, email, contact person, or private notes
            is_external = bool(opp.external_counterparty_id)
            if is_external:
                counterparty_data = {
                    "is_external": True,
                    "external_counterparty_id": str(opp.external_counterparty_id),
                    "counterparty_name": opp.external_counterparty.company_name,
                    "organization_id": None,
                }
            else:
                counterparty_data = {
                    "is_external": False,
                    "external_counterparty_id": None,
                    "organization_id": str(opp.organization_id),
                    "counterparty_name": opp.organization.name if opp.organization else "",
                }

            # Optional broker attribution (Operator visibility only, no trust scoring in T0706)
            broker_attribution = None
            if opp.broker_id and opp.broker:
                broker_attribution = {
                    "broker_id": str(opp.broker_id),
                    "broker_name": opp.broker.name,
                }

            evidence = {
                "counterparty": counterparty_data,
                "broker_attribution": broker_attribution,
                "commodity_id": str(opp.commodity_id),
                "schema_version_id": (
                    str(opp.schema_version_id) if opp.schema_version_id else None
                ),
                "schema_version_number": (
                    opp.schema_version.version if opp.schema_version else None
                ),
                "specifications": specs,
                "quantity": str(opp.quantity) if opp.quantity is not None else None,
                "unit": opp.unit,
                "indicative_price": (
                    str(opp.indicative_price) if opp.indicative_price is not None else None
                ),
                "currency": opp.currency,
                "payment_terms": opp.payment_terms,
                "delivery_window_start": (
                    opp.delivery_window_start.isoformat()
                    if opp.delivery_window_start
                    else None
                ),
                "delivery_window_end": (
                    opp.delivery_window_end.isoformat()
                    if opp.delivery_window_end
                    else None
                ),
                "geography": geo_evidence,
                "status": opp.status,
                "direction": opp.direction,
                "identifier": opp.identifier,
            }

            snapshot = CandidateSnapshot.create(
                candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
                source_id=opp.id,
                lane=CandidateLane.DIRECT_SUPPLY,
                evidence=evidence,
            )
            candidates.append(snapshot)

        return candidates
