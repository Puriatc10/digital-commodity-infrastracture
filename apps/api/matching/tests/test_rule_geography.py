from decimal import Decimal
from django.test import TestCase

from geography.models import GeographicArea
from geography.seed import seed_iran_geography
from matching.enums import SignalOutcome
from matching.rules.geography import (
    CandidateGeographySnapshot,
    GeographicEvidenceRole,
    GeographyConstraintMode,
    GeographyConstraintSnapshot,
    TargetGeographySnapshot,
    evaluate_geography,
)


class GeographyRuleEvaluatorTests(TestCase):
    """
    Mandatory geography rule evaluation tests covering point-like vs coverage semantics,
    constraint modes (REQUIRED, ALLOWED, PREFERRED, EXCLUDED), ANY-OF multi-area semantics,
    and missing/free-text evidence behavior.
    """

    @classmethod
    def setUpTestData(cls):
        cls.areas = seed_iran_geography()
        cls.tehran_prov = cls.areas["IR-07"]
        cls.shahriar = cls.areas["IR-07-SHH"]
        cls.tehran_city = cls.areas["IR-07-THR"]
        cls.isfahan_city = cls.areas["IR-04-ISF"]
        cls.hormozgan_prov = cls.areas["IR-23"]
        cls.bandar_abbas = cls.areas["IR-23-BND"]
        cls.alborz_prov = cls.areas["IR-32"]
        cls.karaj = cls.areas["IR-32-KRJ"]
        cls.qom_prov = cls.areas["IR-26"]

    def test_required_tehran_province_supply_shahriar_passes(self):
        """1. Required Tehran Province, Supply Shahriar -> PASS (point-like city inside required province)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.shahriar,
            area_code=self.shahriar.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)

    def test_required_tehran_province_supply_isfahan_city_hard_fails(self):
        """2. Required Tehran Province, Supply Isfahan City -> HARD FAIL (point-like city outside required province)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.isfahan_city,
            area_code=self.isfahan_city.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.0000"))
        self.assertFalse(res.is_eligible)

    def test_required_tehran_city_pointlike_tehran_province_unknown(self):
        """3. Required Tehran City, Point-like Tehran Province -> UNKNOWN (broad point-like evidence does not prove city)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_city,
                    area_code=self.tehran_city.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.tehran_prov,
            area_code=self.tehran_prov.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_hard)
        self.assertTrue(res.is_eligible)  # Unknown does not hard-fail eligibility by default

    def test_target_tehran_city_operating_area_tehran_province_passes(self):
        """4. Target Tehran City, Operating Area Tehran Province -> PASS (province coverage covers target city)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_city,
                    area_code=self.tehran_city.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.OPERATING_AREA,
            operating_areas=(self.tehran_prov,),
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)

    def test_excluded_hormozgan_province_supply_bandar_abbas_hard_fails(self):
        """5. Excluded Hormozgan Province, Supply Bandar Abbas -> HARD FAIL (inside excluded subtree)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.EXCLUDED,
                    area=self.hormozgan_prov,
                    area_code=self.hormozgan_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.bandar_abbas,
            area_code=self.bandar_abbas.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertTrue(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("0.0000"))
        self.assertFalse(res.is_eligible)

    def test_preferred_tehran_province_supply_isfahan_city_soft_zero(self):
        """6. Preferred Tehran Province, Supply Isfahan City -> soft raw 0 (candidate remains eligible)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.PREFERRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.isfahan_city,
            area_code=self.isfahan_city.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.FAIL)
        self.assertFalse(res.is_hard)  # Soft failure!
        self.assertEqual(res.raw_score, Decimal("0.0000"))
        self.assertTrue(res.is_eligible)  # Remains eligible!

    def test_preferred_tehran_province_supply_shahriar_passes(self):
        """Preferred Tehran Province, Supply Shahriar -> PASS, soft raw 1.0."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.PREFERRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.shahriar,
            area_code=self.shahriar.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertTrue(res.is_eligible)

    def test_no_geography_constraints_not_applicable(self):
        """7. No geography constraints -> NOT_APPLICABLE (does not hurt coverage)."""
        target = TargetGeographySnapshot(constraints=())
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.shahriar,
            area_code=self.shahriar.code,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertFalse(res.is_hard)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_eligible)

    def test_free_text_tehran_only_unknown(self):
        """8. Free-text Tehran only -> UNKNOWN (never fuzzy string guess)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            has_only_free_text=True,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_eligible)

    def test_organization_hq_tehran_no_operating_area_unknown(self):
        """9. Organization HQ Tehran, No explicit operating area -> UNKNOWN (HQ != operating area)."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_city,
                    area_code=self.tehran_city.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.OPERATING_AREA,
            organization_hq_only=True,
        )

        res = evaluate_geography(target, candidate)
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertTrue(res.is_eligible)

    def test_multi_area_any_of_allowed(self):
        """10. Multi-area ANY-OF constraint evaluation."""
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.ALLOWED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.ALLOWED,
                    area=self.alborz_prov,
                    area_code=self.alborz_prov.code,
                ),
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.ALLOWED,
                    area=self.qom_prov,
                    area_code=self.qom_prov.code,
                ),
            )
        )
        # Karaj is in Alborz -> allowed -> PASS
        cand_karaj = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.karaj,
            area_code=self.karaj.code,
        )
        res_karaj = evaluate_geography(target, cand_karaj)
        self.assertEqual(res_karaj.outcome, SignalOutcome.PASS)
        self.assertTrue(res_karaj.is_eligible)

        # Bandar Abbas is in Hormozgan -> outside all allowed -> HARD FAIL
        cand_bnd = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.bandar_abbas,
            area_code=self.bandar_abbas.code,
        )
        res_bnd = evaluate_geography(target, cand_bnd)
        self.assertEqual(res_bnd.outcome, SignalOutcome.FAIL)
        self.assertTrue(res_bnd.is_hard)
        self.assertFalse(res_bnd.is_eligible)

    def test_evaluator_is_side_effect_free(self):
        """Verify evaluator does not modify any source database records."""
        count_before = GeographicArea.objects.count()
        target = TargetGeographySnapshot(
            constraints=(
                GeographyConstraintSnapshot(
                    mode=GeographyConstraintMode.REQUIRED,
                    area=self.tehran_prov,
                    area_code=self.tehran_prov.code,
                ),
            )
        )
        candidate = CandidateGeographySnapshot(
            evidence_role=GeographicEvidenceRole.SUPPLY_LOCATION,
            area=self.shahriar,
            area_code=self.shahriar.code,
        )
        evaluate_geography(target, candidate)
        count_after = GeographicArea.objects.count()
        self.assertEqual(count_before, count_after)
