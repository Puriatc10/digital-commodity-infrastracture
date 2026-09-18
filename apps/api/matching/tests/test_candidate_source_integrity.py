from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
)
from matching.models import (
    MatchingCandidate,
    MatchingPolicy,
    MatchingPolicyVersion,
    MatchingRun,
)
from opportunities.models import ExternalCounterparty, Opportunity, OpportunityDirection
from organizations.models import Organization
from trade_hub.models import RFQ, RFQStatus, SupplyListing, SupplyListingStatus


class CandidateSourceIntegrityTests(TestCase):
    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org")
        self.supplier_org = Organization.objects.create(name="Supplier Org")
        self.broker_org = Organization.objects.create(name="Broker Org")

        self.commodity = CommodityDefinition.objects.create(code="bitumen-cand-src", name_en="Bitumen", name_fa="قیر")
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )

        self.policy = MatchingPolicy.objects.create(code="candidate-test-policy", name="Candidate Policy")
        self.policy_version = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.PUBLISHED,
        )

        self.run = MatchingRun.objects.create(
            rfq=self.rfq,
            rfq_version=self.rfq.version,
            audience=MatchingAudience.BUYER,
            policy_version=self.policy_version,
            requesting_organization=self.buyer_org,
        )

        self.listing_1 = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("200.000"),
            status=SupplyListingStatus.ACTIVE,
        )
        self.listing_2 = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            status=SupplyListingStatus.ACTIVE,
        )

        self.ext_cp = ExternalCounterparty.objects.create(company_name="Global Bitumen Ltd")
        self.opportunity = Opportunity.objects.create(
            identifier="OPP-2026-000101",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.ext_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("150.000"),
        )

    def test_rejection_of_zero_sources(self):
        """Prove that a candidate with zero source FKs is rejected by DB constraint and clean."""
        cand = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
        )
        with self.assertRaises(ValidationError):
            cand.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand])

    def test_rejection_of_two_sources(self):
        """Prove that a candidate with more than one source FK is rejected by DB constraint and clean."""
        cand = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_1,
            supplier_organization=self.supplier_org,
        )
        with self.assertRaises(ValidationError):
            cand.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand])

    def test_rejection_of_kind_source_mismatch(self):
        """Prove kind and source consistency is enforced by DB constraint and clean."""
        # SUPPLY_LISTING kind with supplier_organization source
        cand1 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supplier_organization=self.supplier_org,
        )
        with self.assertRaises(ValidationError):
            cand1.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand1])

        # SUPPLY_OPPORTUNITY kind with supply_listing source
        cand2 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            supply_listing=self.listing_1,
        )
        with self.assertRaises(ValidationError):
            cand2.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand2])

        # SUPPLIER_ORGANIZATION kind with broker_organization source
        cand3 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.BROKER_PATH,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            broker_organization=self.broker_org,
        )
        with self.assertRaises(ValidationError):
            cand3.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand3])

        # BROKER_ORGANIZATION kind with supply_opportunity source
        cand4 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.BROKER_ORGANIZATION,
            supply_opportunity=self.opportunity,
        )
        with self.assertRaises(ValidationError):
            cand4.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand4])

    def test_rejection_of_lane_source_mismatch(self):
        """Prove lane and source consistency is enforced by DB constraint and clean."""
        # BROKER_PATH lane with supply_listing source
        cand1 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.BROKER_PATH,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_1,
        )
        with self.assertRaises(ValidationError):
            cand1.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand1])

        # POTENTIAL_SUPPLIER lane with supply_listing source
        cand2 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_1,
        )
        with self.assertRaises(ValidationError):
            cand2.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand2])

        # DIRECT_SUPPLY lane with supplier_organization source
        cand3 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            supplier_organization=self.supplier_org,
        )
        with self.assertRaises(ValidationError):
            cand3.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand3])

        # DIRECT_SUPPLY lane with broker_organization source
        cand4 = MatchingCandidate(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.BROKER_ORGANIZATION,
            broker_organization=self.broker_org,
        )
        with self.assertRaises(ValidationError):
            cand4.clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.bulk_create([cand4])

    def test_duplicate_exact_source_in_same_run_rejected(self):
        """Prove DB rejects duplicate occurrences of the same source artifact inside one run."""
        # 1. Supply Listing duplicate
        MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.create(
                    run=self.run,
                    lane=CandidateLane.DIRECT_SUPPLY,
                    candidate_kind=CandidateKind.SUPPLY_LISTING,
                    supply_listing=self.listing_1,
                )

        # 2. Supplier Organization duplicate
        MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            supplier_organization=self.supplier_org,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.create(
                    run=self.run,
                    lane=CandidateLane.POTENTIAL_SUPPLIER,
                    candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
                    supplier_organization=self.supplier_org,
                )

        # 3. Supply Opportunity duplicate
        MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            supply_opportunity=self.opportunity,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.create(
                    run=self.run,
                    lane=CandidateLane.DIRECT_SUPPLY,
                    candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
                    supply_opportunity=self.opportunity,
                )

        # 4. Broker Organization duplicate
        MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.BROKER_PATH,
            candidate_kind=CandidateKind.BROKER_ORGANIZATION,
            broker_organization=self.broker_org,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchingCandidate.objects.create(
                    run=self.run,
                    lane=CandidateLane.BROKER_PATH,
                    candidate_kind=CandidateKind.BROKER_ORGANIZATION,
                    broker_organization=self.broker_org,
                )

    def test_different_artifacts_from_same_organization_allowed(self):
        """
        Prove that different evidence artifacts owned by one Organization can coexist in one run:
        - Supplier Organization X
        - Supply Listing X-1
        - Supply Listing X-2
        """
        cand_org = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            supplier_organization=self.supplier_org,
        )
        cand_listing_1 = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_1,
        )
        cand_listing_2 = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing_2,
        )

        self.assertEqual(
            MatchingCandidate.objects.filter(run=self.run).count(),
            3,
        )
        self.assertNotEqual(cand_org.id, cand_listing_1.id)
        self.assertNotEqual(cand_listing_1.id, cand_listing_2.id)
