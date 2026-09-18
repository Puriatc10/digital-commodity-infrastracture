from typing import List, Sequence

from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot
from matching.enums import CandidateKind, CandidateLane
from matching.rules.geography import GeographicEvidenceRole
from organizations.models import Organization, OrganizationCapability


class BrokerCandidateProvider:
    """
    Candidate provider for the Broker Path lane backed by registered Organizations.

    Filters for active organizations with explicit Broker capability and declared
    commodity association.

    CRITICAL INVARIANTS:
    - Brokers are facilitators, not suppliers: never describe as inventory or supply listing.
    - Operating geography is derived strictly from explicit OrganizationOperatingArea records.
    - Registered country, address, or headquarters MUST NEVER be inferred as operating area.
    """

    def find_candidates(
        self,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Discover active Broker organizations associated with the requested commodity.
        """
        organizations = (
            Organization.objects.filter(
                is_active=True,
                capabilities__capability=OrganizationCapability.CapabilityType.BROKER,
                commodities__commodity=context.commodity_id,
            )
            .exclude(id=context.rfq_owner_organization_id)
            .select_related("verification")
            .prefetch_related("capabilities", "commodities", "operating_areas__area")
            .distinct()
            .order_by("id")
        )

        candidates: List[CandidateSnapshot] = []
        for org in organizations:
            # Deterministic capability and commodity sorting
            caps = sorted({c.capability for c in org.capabilities.all()})
            comm_ids = sorted({str(c.commodity_id) for c in org.commodities.all()})

            # Broker organization verification status (absent record maps to unverified)
            org_ver = getattr(org, "verification", None)
            org_verification_status = org_ver.status if org_ver else "unverified"

            # Explicit operating areas only; no HQ or registered country inference
            sorted_operating_areas = sorted(
                org.operating_areas.all(),
                key=lambda oa: (oa.area.code, str(oa.area_id)),
            )
            has_operating_areas = len(sorted_operating_areas) > 0
            operating_area_records = [
                {"area_id": str(oa.area_id), "area_code": oa.area.code}
                for oa in sorted_operating_areas
            ]
            organization_hq_only = bool(org.country and not has_operating_areas)

            geo_evidence = {
                "evidence_role": GeographicEvidenceRole.OPERATING_AREA,
                "area_id": None,
                "area_code": "",
                "operating_areas": operating_area_records,
                "has_only_free_text": False,
                "organization_hq_only": organization_hq_only,
            }

            # Broker Path lane contains ZERO inventory or supply claims
            evidence = {
                "organization_id": str(org.id),
                "organization_name": org.name,
                "verification_status": org_verification_status,
                "capabilities": caps,
                "supported_commodity_ids": comm_ids,
                "quantity": None,
                "unit": None,
                "availability_window_start": None,
                "availability_window_end": None,
                "specifications": {},
                "indicative_price": None,
                "currency": None,
                "geography": geo_evidence,
                "is_active": org.is_active,
            }

            snapshot = CandidateSnapshot.create(
                candidate_kind=CandidateKind.BROKER_ORGANIZATION,
                source_id=org.id,
                lane=CandidateLane.BROKER_PATH,
                evidence=evidence,
            )
            candidates.append(snapshot)

        return candidates
