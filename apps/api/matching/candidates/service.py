from typing import List, Sequence

from matching.candidates.authorization import validate_actor_audience_authorization
from matching.candidates.broker_organization import BrokerCandidateProvider
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.protocol import CandidateProvider
from matching.candidates.snapshot import CandidateSnapshot
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.candidates.supply_listing import SupplyListingCandidateProvider
from matching.candidates.supply_opportunity import SupplyOpportunityCandidateProvider
from matching.enums import MatchingAudience


def get_candidate_providers(audience: str) -> Sequence[CandidateProvider]:
    """
    Return the authoritative suite of CandidateProviders for the requested audience.

    CRITICAL PRIVACY BOUNDARY:
    - Buyer universe: SupplyListing, SupplierOrganization, BrokerCandidateProvider.
      SupplyOpportunityCandidateProvider is STRICTLY excluded.
    - Operator universe: SupplyListing, SupplyOpportunity, SupplierOrganization, BrokerCandidateProvider.
    """
    if audience == MatchingAudience.BUYER:
        return (
            SupplyListingCandidateProvider(),
            SupplierOrganizationCandidateProvider(),
            BrokerCandidateProvider(),
        )
    elif audience == MatchingAudience.OPERATOR:
        return (
            SupplyListingCandidateProvider(),
            SupplyOpportunityCandidateProvider(),
            SupplierOrganizationCandidateProvider(),
            BrokerCandidateProvider(),
        )
    else:
        raise ValueError(
            f"Invalid audience '{audience}'. Must be one of: {', '.join(MatchingAudience.values)}."
        )


class CandidateDiscoveryService:
    """
    Domain service for discovering and snapshotting matching candidates for an RFQ target.

    Orchestrates audience-scoped provider execution, enforces entry-point actor authorization,
    and returns a deterministic collection of candidate snapshots without deduplicating
    distinct evidence artifacts across the same organization.
    """

    @classmethod
    def discover_candidates(
        cls,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Execute authorized candidate discovery for a validated target context.

        1. Server-side authorization check: validates actor authority for target RFQ and audience.
        2. Resolves authorized provider suite for the audience.
        3. Executes each provider to snapshot matching evidence.
        4. Orders candidates deterministically by lane and stable_candidate_key.
        """
        # 1. Enforce authorization before discovery/snapshotting
        validate_actor_audience_authorization(actor_scope, context)

        # 2. Resolve authorized providers
        providers = get_candidate_providers(context.audience)

        # 3. Collect candidates
        candidates: List[CandidateSnapshot] = []
        for provider in providers:
            provider_candidates = provider.find_candidates(context, actor_scope)
            candidates.extend(provider_candidates)

        # 4. Deterministic sorting (lane, stable_candidate_key)
        candidates.sort(key=lambda c: (c.lane, c.stable_candidate_key))

        return tuple(candidates)


# Convenience module-level entry point
discover_candidates = CandidateDiscoveryService.discover_candidates
