from typing import List, Sequence

from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot
from matching.enums import CandidateKind, CandidateLane
from matching.rules.geography import GeographicEvidenceRole
from organizations.models import Organization, OrganizationCapability


class SupplierOrganizationCandidateProvider:
    """
    Candidate provider for the Potential Supplier lane backed by registered Organizations.

    Filters for active organizations with explicit Supplier capability and declared
    commodity association.

    CRITICAL INVARIANTS:
    - Never invents current inventory: quantity, availability, specifications remain empty/null.
    - Operating geography is derived strictly from explicit OrganizationOperatingArea records.
    - Registered country, address, or headquarters MUST NEVER be inferred as operating area.
    """

    def find_candidates(
        self,
        context: CandidateContext,
        actor_scope: ActorScope,
    ) -> Sequence[CandidateSnapshot]:
        """
        Discover active Supplier organizations associated with the requested commodity.
        """
        organizations = (
            Organization.objects.filter(
                is_active=True,
                capabilities__capability=OrganizationCapability.CapabilityType.SUPPLIER,
                commodities__commodity=context.commodity_id,
            )
            .exclude(id=context.rfq_owner_organization_id)
            .prefetch_related("capabilities", "commodities", "operating_areas__area")
            .distinct()
            .order_by("id")
        )

        candidates: List[CandidateSnapshot] = []
        for org in organizations:
            # Deterministic capability and commodity sorting
            caps = sorted({c.capability for c in org.capabilities.all()})
            comm_ids = sorted({str(c.commodity_id) for c in org.commodities.all()})

            # Explicit operating areas only; registered HQ/country is never treated as operating area
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

            # Potential Supplier lane contains ZERO inventory claims
            evidence = {
                "organization_id": str(org.id),
                "organization_name": org.name,
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
                candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
                source_id=org.id,
                lane=CandidateLane.POTENTIAL_SUPPLIER,
                evidence=evidence,
            )
            candidates.append(snapshot)

        return candidates
