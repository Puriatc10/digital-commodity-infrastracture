from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from offers.enums import DecisionDimension, DecisionProfileLifecycleStatus
from offers.exceptions import (
    DecisionPolicyError,
    DecisionProfileSeedConflictError,
)
from offers.models.decision import (
    DecisionDimensionWeight,
    DecisionProfile,
    DecisionProfileVersion,
)
from offers.services.policy_seed import (
    DEFAULT_DECISION_PROFILE_CODE,
    REQUIRED_V1_DIMENSIONS,
    seed_decision_profile_v1,
    validate_decision_profile_version,
)


class DecisionProfilePolicyTests(TestCase):
    """
    Tests for DecisionProfile, DecisionProfileVersion, and DecisionDimensionWeight (T0808).
    """

    def setUp(self):
        super().setUp()
        self.profile = DecisionProfile.objects.create(
            code=f"test-decision-{uuid.uuid4().hex[:6]}",
            name="Test Decision Profile",
            description="Profile for testing policy invariants.",
        )

    def test_seed_decision_profile_v1_exact_weights_and_coverage(self):
        """Seed creates exact v1 configuration: Cost 35, Quality 25, Delivery 15, Payment 10, Trust 10, Completeness 5, Min Coverage 70."""
        v1 = seed_decision_profile_v1()

        self.assertEqual(v1.profile.code, DEFAULT_DECISION_PROFILE_CODE)
        self.assertEqual(v1.version, 1)
        self.assertEqual(v1.status, DecisionProfileLifecycleStatus.PUBLISHED)
        self.assertEqual(v1.minimum_coverage, Decimal("70.00"))

        weights = {
            dw.dimension: dw.weight for dw in v1.dimension_weights.all()
        }
        self.assertEqual(weights[DecisionDimension.COST], Decimal("35.00"))
        self.assertEqual(weights[DecisionDimension.QUALITY], Decimal("25.00"))
        self.assertEqual(weights[DecisionDimension.DELIVERY], Decimal("15.00"))
        self.assertEqual(weights[DecisionDimension.PAYMENT], Decimal("10.00"))
        self.assertEqual(weights[DecisionDimension.TRUST], Decimal("10.00"))
        self.assertEqual(weights[DecisionDimension.COMPLETENESS], Decimal("5.00"))

        self.assertEqual(sum(weights.values()), Decimal("100.00"))

    def test_seed_decision_profile_v1_idempotent_seed_twice(self):
        """Seeding twice returns identical published version without mutation."""
        first = seed_decision_profile_v1()
        second = seed_decision_profile_v1()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.version, second.version)
        self.assertEqual(first.status, DecisionProfileLifecycleStatus.PUBLISHED)
        self.assertEqual(DecisionProfileVersion.objects.filter(profile=first.profile, version=1).count(), 1)

    def test_seed_decision_profile_conflicting_seed_fails_clearly(self):
        """Conflicting existing v1 semantics raises DecisionProfileSeedConflictError without mutating history."""
        v1 = seed_decision_profile_v1()

        # Artificially alter minimum coverage in DB bypassing clean() to simulate conflicting persisted state
        DecisionProfileVersion.objects.filter(pk=v1.pk).update(minimum_coverage=Decimal("80.00"))

        with self.assertRaises(DecisionProfileSeedConflictError) as ctx:
            seed_decision_profile_v1()

        self.assertIn("differs from target seed", str(ctx.exception))
        # Verify DB was NOT mutated back or corrupted
        v1.refresh_from_db()
        self.assertEqual(v1.minimum_coverage, Decimal("80.00"))

    def test_published_profile_immutability(self):
        """Published profile versions cannot be mutated or deleted."""
        v1 = seed_decision_profile_v1()

        # Cannot revert to draft
        v1.status = DecisionProfileLifecycleStatus.DRAFT
        with self.assertRaises(ValidationError):
            v1.save()

        v1.refresh_from_db()

        # Cannot alter minimum coverage
        v1.minimum_coverage = Decimal("50.00")
        with self.assertRaises(ValidationError):
            v1.save()

        v1.refresh_from_db()

        # Cannot mutate existing dimension weight
        weight = v1.dimension_weights.first()
        weight.weight = Decimal("50.00")
        with self.assertRaises(ValidationError):
            weight.save()

        # Cannot add new dimension weight to published version
        with self.assertRaises(ValidationError):
            DecisionDimensionWeight.objects.create(
                profile_version=v1,
                dimension=DecisionDimension.COST,
                weight=Decimal("10.00"),
            )

        # Cannot delete dimension weight from published version
        with self.assertRaises(ValidationError):
            weight.delete()

        # Cannot delete published profile version
        with self.assertRaises(ValidationError):
            v1.delete()

    def test_draft_v2_mutation_allowed(self):
        """Draft v2 allows modification and deletion before publication."""
        v1 = seed_decision_profile_v1()

        # Create v2 in DRAFT
        v2 = DecisionProfileVersion.objects.create(
            profile=v1.profile,
            version=2,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("75.00"),
            description="Draft candidate for policy v2",
        )

        dw = DecisionDimensionWeight.objects.create(
            profile_version=v2,
            dimension=DecisionDimension.COST,
            weight=Decimal("40.00"),
        )
        # Weight mutation allowed in draft
        dw.weight = Decimal("45.00")
        dw.save()
        dw.refresh_from_db()
        self.assertEqual(dw.weight, Decimal("45.00"))

        # Minimum coverage mutation allowed in draft
        v2.minimum_coverage = Decimal("80.00")
        v2.save()
        v2.refresh_from_db()
        self.assertEqual(v2.minimum_coverage, Decimal("80.00"))

        # Deletion of weight allowed in draft
        dw.delete()
        self.assertEqual(v2.dimension_weights.count(), 0)

        # Deletion of draft version allowed
        v2.delete()
        self.assertFalse(DecisionProfileVersion.objects.filter(pk=v2.pk).exists())

    def test_validation_sum_must_equal_100(self):
        """Dimension weights must sum to exactly 100."""
        v = DecisionProfileVersion.objects.create(
            profile=self.profile,
            version=1,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("70.00"),
        )
        for dim in REQUIRED_V1_DIMENSIONS.keys():
            DecisionDimensionWeight.objects.create(
                profile_version=v,
                dimension=dim.value,
                weight=Decimal("10.00"),  # Total = 60, not 100
            )

        with self.assertRaises(DecisionPolicyError) as ctx:
            validate_decision_profile_version(v)
        self.assertIn("must equal exactly 100.00%", str(ctx.exception))

    def test_validation_missing_dimensions(self):
        """Missing any required v1 dimension fails validation."""
        v = DecisionProfileVersion.objects.create(
            profile=self.profile,
            version=1,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("70.00"),
        )
        # Add only Cost and Quality summing to 100
        DecisionDimensionWeight.objects.create(
            profile_version=v,
            dimension=DecisionDimension.COST,
            weight=Decimal("60.00"),
        )
        DecisionDimensionWeight.objects.create(
            profile_version=v,
            dimension=DecisionDimension.QUALITY,
            weight=Decimal("40.00"),
        )

        with self.assertRaises(DecisionPolicyError) as ctx:
            validate_decision_profile_version(v)
        self.assertIn("missing required dimensions", str(ctx.exception))

    def test_database_constraints_prevent_invalid_values(self):
        """DB check constraints enforce positive version, valid status, weight range 0..100, min coverage 0..100."""
        # Version <= 0 rejected
        bad_v = DecisionProfileVersion(
            profile=self.profile,
            version=0,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("70.00"),
        )
        with self.assertRaises(ValidationError):
            bad_v.full_clean()

        # Minimum coverage > 100 rejected
        bad_cov = DecisionProfileVersion(
            profile=self.profile,
            version=1,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("110.00"),
        )
        with self.assertRaises(ValidationError):
            bad_cov.full_clean()

        # Dimension weight > 100 rejected
        v_ok = DecisionProfileVersion.objects.create(
            profile=self.profile,
            version=1,
            status=DecisionProfileLifecycleStatus.DRAFT,
            minimum_coverage=Decimal("70.00"),
        )
        bad_dw = DecisionDimensionWeight(
            profile_version=v_ok,
            dimension=DecisionDimension.COST,
            weight=Decimal("150.00"),
        )
        with self.assertRaises(ValidationError):
            bad_dw.full_clean()
