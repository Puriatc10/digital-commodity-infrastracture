from typing import List, Sequence

from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot
from matching.enums import CandidateKind, CandidateLane
from matching.rules.geography import GeographicEvidenceRole
from trade_hub.models.supply import SupplyListingStatus
from trade_hub.services.visibility_service import SupplyListingVisibilityService


class SupplyListingCandidateProvider:
    """
    Candidate provider for the Direct Supply lane backed by formal Supply Listings.

    Enforces authoritative Epic 5 listing lifecycle and visibility rules,
    retains historical commodity schema and specifications immutably,
    and captures structured origin area geography without free-text inference.
    """

    def find_candidates(
        self,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Discover usable, authorized Supply Listing candidates for the target context.
        """
        # 1. Authoritative server-side visibility scoping
        visible_qs = SupplyListingVisibilityService.get_visible_supply_listings(
            user=actor_scope.user,
            organization=actor_scope.organization,
        )

        # 2. Relational pre-filters: active lifecycle, target commodity, non-self
        listings = (
            visible_qs.filter(
                status=SupplyListingStatus.ACTIVE,
                commodity_id=context.commodity_id,
            )
            .exclude(organization_id=context.rfq_owner_organization_id)
            .select_related(
                "organization",
                "organization__verification",
                "commodity",
                "schema_version",
                "origin_area",
            )
            .order_by("id")
        )

        candidates: List[CandidateSnapshot] = []
        for listing in listings:
            # Deterministic sorting of specification keys
            specs = (
                dict(sorted(listing.specifications.items()))
                if listing.specifications
                else {}
            )

            # Structured geography from T0702; legacy free-text is never treated as authoritative
            has_structured_area = listing.origin_area_id is not None
            geo_evidence = {
                "evidence_role": GeographicEvidenceRole.SUPPLY_LOCATION,
                "area_id": str(listing.origin_area_id) if has_structured_area else None,
                "area_code": listing.origin_area.code if has_structured_area else "",
                "has_only_free_text": bool(listing.origin and not has_structured_area),
                "operating_areas": (),
                "organization_hq_only": False,
            }

            # Verification status from owning organization (absent record maps to unverified)
            org_ver = getattr(listing.organization, "verification", None)
            org_verification_status = org_ver.status if org_ver else "unverified"

            # Matching-relevant evidence only (no phone/email, internal notes, credentials, or docs)
            evidence = {
                "organization_id": str(listing.organization_id),
                "organization_name": listing.organization.name,
                "verification_status": org_verification_status,
                "commodity_id": str(listing.commodity_id),
                "schema_version_id": str(listing.schema_version_id),
                "schema_version_number": listing.schema_version.version,
                "specifications": specs,
                "quantity": str(listing.quantity),
                "unit": listing.unit,
                "indicative_price": (
                    str(listing.indicative_price)
                    if listing.indicative_price is not None
                    else None
                ),
                "currency": listing.currency,
                "incoterm": listing.incoterm,
                "payment_terms": listing.payment_terms,
                "availability_window_start": (
                    listing.availability_window_start.isoformat()
                    if listing.availability_window_start
                    else None
                ),
                "availability_window_end": (
                    listing.availability_window_end.isoformat()
                    if listing.availability_window_end
                    else None
                ),
                "geography": geo_evidence,
                "status": listing.status,
                "visibility": listing.visibility,
            }

            snapshot = CandidateSnapshot.create(
                candidate_kind=CandidateKind.SUPPLY_LISTING,
                source_id=listing.id,
                lane=CandidateLane.DIRECT_SUPPLY,
                evidence=evidence,
            )
            candidates.append(snapshot)

        return candidates
