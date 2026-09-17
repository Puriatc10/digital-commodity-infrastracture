from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from matching.enums import MatchingAudience, PolicyLifecycleStatus
from matching.models import MatchingPolicy, MatchingPolicyVersion, MatchingRun
from matching.services import create_matching_run, publish_policy_version, retire_policy_version
from organizations.models import Organization
from trade_hub.models import RFQ, RFQStatus


class MatchingPolicyVersioningTests(TestCase):
    def setUp(self):
        self.policy = MatchingPolicy.objects.create(
            code="test-policy",
            name="Test Policy",
            description="A test matching policy.",
        )
        self.org = Organization.objects.create(name="Buyer Corp")
        self.commodity = CommodityDefinition.objects.create(code="bitumen-test-pol", name_en="Bitumen", name_fa="قیر")
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )
        self.rfq = RFQ.objects.create(
            organization=self.org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

    def test_positive_policy_version_enforced(self):
        """Prove policy version > 0 is enforced by clean and DB check constraint."""
        ver0 = MatchingPolicyVersion(policy=self.policy, version=0)
        with self.assertRaises(ValidationError):
            ver0.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingPolicyVersion.objects.bulk_create([ver0])

    def test_policy_version_uniqueness(self):
        """Prove (policy, version) uniqueness is enforced by DB constraint."""
        MatchingPolicyVersion.objects.create(policy=self.policy, version=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingPolicyVersion.objects.create(policy=self.policy, version=1)

    def test_cannot_start_in_retired_status(self):
        """Prove that new policy versions cannot start in RETIRED status."""
        v = MatchingPolicyVersion(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.RETIRED,
        )
        with self.assertRaises(ValidationError):
            v.save()

    def test_draft_cannot_skip_to_retired(self):
        """Prove that a draft policy version must be published before retirement."""
        v = MatchingPolicyVersion.objects.create(policy=self.policy, version=1)
        v.status = PolicyLifecycleStatus.RETIRED
        with self.assertRaises(ValidationError):
            v.save()

    def test_published_cannot_revert_to_draft(self):
        """Prove that a published policy version cannot revert to draft."""
        v = MatchingPolicyVersion.objects.create(policy=self.policy, version=1)
        publish_policy_version(v)
        v.status = PolicyLifecycleStatus.DRAFT
        with self.assertRaises(ValidationError):
            v.save()

    def test_published_configuration_immutability(self):
        """Prove that once published, configuration cannot be modified."""
        v = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            configuration={"weights": {"spec": 45, "qty": 10}},
        )
        publish_policy_version(v)

        # Attempt to modify configuration
        v.configuration = {"weights": {"spec": 50, "qty": 10}}
        with self.assertRaises(ValidationError):
            v.save()

    def test_published_policy_can_transition_to_retired(self):
        """Prove that legitimate retirement of published policy is permitted."""
        v = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            configuration={"weights": {"spec": 45}},
        )
        publish_policy_version(v)
        retired_v = retire_policy_version(v)

        self.assertEqual(retired_v.status, PolicyLifecycleStatus.RETIRED)

        # Retired version cannot modify configuration
        retired_v.configuration = {"weights": {"spec": 99}}
        with self.assertRaises(ValidationError):
            retired_v.save()

        # Retired version cannot change status
        retired_v.status = PolicyLifecycleStatus.PUBLISHED
        with self.assertRaises(ValidationError):
            retired_v.save()

    def test_matching_run_requires_published_policy(self):
        """Prove that runs can only be created against Published policy versions."""
        draft_v = MatchingPolicyVersion.objects.create(policy=self.policy, version=1)

        # Service path rejects DRAFT
        with self.assertRaises(ValidationError):
            create_matching_run(
                rfq=self.rfq,
                rfq_version=self.rfq.version,
                audience=MatchingAudience.BUYER,
                policy_version=draft_v,
            )

        # Model validation rejects DRAFT
        run_draft = MatchingRun(
            rfq=self.rfq,
            rfq_version=self.rfq.version,
            audience=MatchingAudience.BUYER,
            policy_version=draft_v,
        )
        with self.assertRaises(ValidationError):
            run_draft.save()

        # Publish policy and verify success
        publish_policy_version(draft_v)
        run = create_matching_run(
            rfq=self.rfq,
            rfq_version=self.rfq.version,
            audience=MatchingAudience.BUYER,
            policy_version=draft_v,
            requesting_organization=self.org,
            target_snapshot={"rfq_id": str(self.rfq.id)},
        )
        self.assertIsNotNone(run.id)
        self.assertTrue(len(run.input_fingerprint) > 0)

        # Retiring policy prevents new runs against it
        retire_policy_version(draft_v)
        with self.assertRaises(ValidationError):
            create_matching_run(
                rfq=self.rfq,
                rfq_version=self.rfq.version,
                audience=MatchingAudience.BUYER,
                policy_version=draft_v,
            )
