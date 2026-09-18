from django.test import TestCase

from matching.enums import CandidateLane, PolicyLifecycleStatus, SignalDimension
from matching.exceptions import InvalidPolicyConfigurationError, PolicySeedConflictError
from matching.models.policy import MatchingPolicy, MatchingPolicyVersion
from matching.models.verification_rule import VerificationMatchingRule
from matching.seed import (
    DEFAULT_POLICY_CODE,
    DEFAULT_POLICY_V1_CONFIGURATION,
    seed_matching_policy_v1,
    validate_policy_configuration,
)


class SeedMatchingPolicyTests(TestCase):
    """
    Tests for seeding default matching policy v1, idempotent re-runs,
    lane weight sum validation (must total 100), and conflict detection.
    """

    def test_seed_matching_policy_v1_creates_published_policy_and_rules(self):
        """Initial seed creates policy aggregate, published v1, and verification rules."""
        v1 = seed_matching_policy_v1()
        self.assertEqual(v1.version, 1)
        self.assertEqual(v1.status, PolicyLifecycleStatus.PUBLISHED)
        self.assertEqual(v1.policy.code, DEFAULT_POLICY_CODE)

        # Verify lane weights configuration
        weights = v1.configuration["dimension_weights"]
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.SPECIFICATION.value], 45)
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.QUANTITY.value], 10)
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.AVAILABILITY.value], 15)
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.GEOGRAPHY.value], 10)
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.TRUST.value], 15)
        self.assertEqual(weights[CandidateLane.DIRECT_SUPPLY.value][SignalDimension.HISTORY.value], 5)

        self.assertEqual(weights[CandidateLane.POTENTIAL_SUPPLIER.value][SignalDimension.GEOGRAPHY.value], 40)
        self.assertEqual(weights[CandidateLane.POTENTIAL_SUPPLIER.value][SignalDimension.TRUST.value], 60)

        self.assertEqual(weights[CandidateLane.BROKER_PATH.value][SignalDimension.GEOGRAPHY.value], 40)
        self.assertEqual(weights[CandidateLane.BROKER_PATH.value][SignalDimension.TRUST.value], 60)

        # Verify verification rules were seeded
        rules = VerificationMatchingRule.objects.filter(policy_version=v1)
        self.assertGreaterEqual(rules.count(), 4)

    def test_seed_matching_policy_v1_is_idempotent(self):
        """Subsequent runs return the existing v1 instance without creating duplicates."""
        v1_first = seed_matching_policy_v1()
        initial_policies = MatchingPolicy.objects.count()
        initial_versions = MatchingPolicyVersion.objects.count()
        initial_rules = VerificationMatchingRule.objects.count()

        v1_second = seed_matching_policy_v1()

        self.assertEqual(v1_first.pk, v1_second.pk)
        self.assertEqual(MatchingPolicy.objects.count(), initial_policies)
        self.assertEqual(MatchingPolicyVersion.objects.count(), initial_versions)
        self.assertEqual(VerificationMatchingRule.objects.count(), initial_rules)

    def test_seed_matching_policy_v1_raises_conflict_on_modified_weights(self):
        """If v1 exists with conflicting weights, seed must raise PolicySeedConflictError."""
        policy, _ = MatchingPolicy.objects.get_or_create(code=DEFAULT_POLICY_CODE)
        conflicting_config = {
            "dimension_weights": {
                CandidateLane.DIRECT_SUPPLY.value: {
                    SignalDimension.SPECIFICATION.value: 50,  # Conflict: 50 instead of 45
                    SignalDimension.QUANTITY.value: 10,
                    SignalDimension.AVAILABILITY.value: 15,
                    SignalDimension.GEOGRAPHY.value: 10,
                    SignalDimension.TRUST.value: 10,
                    SignalDimension.HISTORY.value: 5,
                },
                CandidateLane.POTENTIAL_SUPPLIER.value: {
                    SignalDimension.GEOGRAPHY.value: 40,
                    SignalDimension.TRUST.value: 60,
                },
                CandidateLane.BROKER_PATH.value: {
                    SignalDimension.GEOGRAPHY.value: 40,
                    SignalDimension.TRUST.value: 60,
                },
            }
        }
        MatchingPolicyVersion.objects.create(
            policy=policy,
            version=1,
            status=PolicyLifecycleStatus.PUBLISHED,
            configuration=conflicting_config,
        )

        with self.assertRaises(PolicySeedConflictError) as ctx:
            seed_matching_policy_v1()

        self.assertIn("conflicting configuration", str(ctx.exception))

    def test_validate_policy_configuration_enforces_sum_100(self):
        """Each candidate lane must sum to exactly 100."""
        # Valid config passes
        validate_policy_configuration(DEFAULT_POLICY_V1_CONFIGURATION)

        # Direct Supply sums to 90 -> error
        invalid_config = {
            "dimension_weights": {
                CandidateLane.DIRECT_SUPPLY.value: {
                    SignalDimension.SPECIFICATION.value: 35,  # Sum is 90
                    SignalDimension.QUANTITY.value: 10,
                    SignalDimension.AVAILABILITY.value: 15,
                    SignalDimension.GEOGRAPHY.value: 10,
                    SignalDimension.TRUST.value: 15,
                    SignalDimension.HISTORY.value: 5,
                }
            }
        }
        with self.assertRaises(InvalidPolicyConfigurationError):
            validate_policy_configuration(invalid_config)
