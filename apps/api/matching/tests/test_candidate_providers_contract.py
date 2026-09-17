from dataclasses import FrozenInstanceError
import uuid

from django.test import TestCase

from matching.candidates.broker_organization import BrokerCandidateProvider
from matching.candidates.protocol import CandidateProvider
from matching.candidates.snapshot import CandidateSnapshot
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.candidates.supply_listing import SupplyListingCandidateProvider
from matching.candidates.supply_opportunity import SupplyOpportunityCandidateProvider
from matching.enums import CandidateKind, CandidateLane
from matching.rules.geography import GeographicEvidenceRole


class CandidateProvidersContractTests(TestCase):
    """
    Contract and value object invariants for Candidate Providers and Snapshots.
    """

    def test_all_providers_satisfy_candidate_provider_protocol(self):
        """Verify all four independent candidate providers conform to CandidateProvider protocol."""
        providers = [
            SupplyListingCandidateProvider(),
            SupplyOpportunityCandidateProvider(),
            SupplierOrganizationCandidateProvider(),
            BrokerCandidateProvider(),
        ]
        for provider in providers:
            self.assertIsInstance(
                provider,
                CandidateProvider,
                f"{provider.__class__.__name__} must conform to CandidateProvider protocol.",
            )
            self.assertTrue(callable(getattr(provider, "find_candidates", None)))

    def test_candidate_snapshot_immutability(self):
        """CandidateSnapshot is a frozen value object and rejects in-place mutation."""
        snapshot = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uuid.uuid4(),
            evidence={"quantity": "500", "unit": "MT"},
        )
        with self.assertRaises(FrozenInstanceError):
            snapshot.lane = CandidateLane.BROKER_PATH

        with self.assertRaises(FrozenInstanceError):
            snapshot.source_id = "modified"

    def test_candidate_snapshot_lane_kind_matrix_integrity(self):
        """CandidateSnapshot enforces strict kind-to-lane matrix mapping."""
        valid_pairs = [
            (CandidateKind.SUPPLY_LISTING, CandidateLane.DIRECT_SUPPLY),
            (CandidateKind.SUPPLY_OPPORTUNITY, CandidateLane.DIRECT_SUPPLY),
            (CandidateKind.SUPPLIER_ORGANIZATION, CandidateLane.POTENTIAL_SUPPLIER),
            (CandidateKind.BROKER_ORGANIZATION, CandidateLane.BROKER_PATH),
        ]
        uid = str(uuid.uuid4())
        for kind, lane in valid_pairs:
            snapshot = CandidateSnapshot(
                lane=lane,
                candidate_kind=kind,
                source_id=uid,
                stable_candidate_key=f"{kind}:{uid}",
                evidence={},
            )
            self.assertEqual(snapshot.lane, lane)
            self.assertEqual(snapshot.candidate_kind, kind)

        # Invalid combinations must raise ValueError
        invalid_pairs = [
            (CandidateKind.SUPPLY_LISTING, CandidateLane.POTENTIAL_SUPPLIER),
            (CandidateKind.SUPPLY_LISTING, CandidateLane.BROKER_PATH),
            (CandidateKind.SUPPLY_OPPORTUNITY, CandidateLane.POTENTIAL_SUPPLIER),
            (CandidateKind.SUPPLIER_ORGANIZATION, CandidateLane.DIRECT_SUPPLY),
            (CandidateKind.BROKER_ORGANIZATION, CandidateLane.DIRECT_SUPPLY),
        ]
        for kind, lane in invalid_pairs:
            with self.assertRaises(ValueError):
                CandidateSnapshot(
                    lane=lane,
                    candidate_kind=kind,
                    source_id=uid,
                    stable_candidate_key=f"{kind}:{uid}",
                    evidence={},
                )

    def test_stable_candidate_key_validation(self):
        """stable_candidate_key must follow KIND:UUID format."""
        uid = str(uuid.uuid4())
        # Valid key
        snapshot = CandidateSnapshot(
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uid,
            stable_candidate_key=f"SUPPLY_LISTING:{uid}",
            evidence={},
        )
        self.assertEqual(snapshot.stable_candidate_key, f"SUPPLY_LISTING:{uid}")

        # Mismatched key must be rejected
        with self.assertRaises(ValueError):
            CandidateSnapshot(
                lane=CandidateLane.DIRECT_SUPPLY,
                candidate_kind=CandidateKind.SUPPLY_LISTING,
                source_id=uid,
                stable_candidate_key="ARBITRARY_NAME",
                evidence={},
            )

    def test_to_candidate_geography_snapshot_conversion(self):
        """Verify seamless adaptation to T0702 CandidateGeographySnapshot."""
        area_id = str(uuid.uuid4())
        snapshot = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uuid.uuid4(),
            evidence={
                "geography": {
                    "evidence_role": GeographicEvidenceRole.SUPPLY_LOCATION,
                    "area_id": area_id,
                    "area_code": "IR-TEH",
                    "has_only_free_text": False,
                    "organization_hq_only": False,
                }
            },
        )
        geo_snap = snapshot.to_candidate_geography_snapshot()
        self.assertEqual(geo_snap.evidence_role, GeographicEvidenceRole.SUPPLY_LOCATION)
        self.assertEqual(geo_snap.area, area_id)
        self.assertEqual(geo_snap.area_code, "IR-TEH")
        self.assertFalse(geo_snap.has_only_free_text)
        self.assertFalse(geo_snap.organization_hq_only)
