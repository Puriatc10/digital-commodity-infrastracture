from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    PolicyLifecycleStatus,
    SignalDimension,
    SignalOutcome,
)
from matching.models import (
    MatchingCandidate,
    MatchingPolicy,
    MatchingPolicyVersion,
    MatchingRun,
    MatchingSignal,
)
from opportunities.models import ExternalCounterparty, Opportunity, OpportunityDirection
from organizations.models import Organization
from trade_hub.models import RFQ, RFQStatus, SupplyListing, SupplyListingStatus


class HistoricalIntegrityTests(TestCase):
    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Historical Buyer")
        self.supplier_org = Organization.objects.create(name="Historical Supplier")
        self.broker_org = Organization.objects.create(name="Historical Broker")

        self.commodity = CommodityDefinition.objects.create(code="bitumen-hist-test", name_en="Bitumen", name_fa="قیر")
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

        self.policy = MatchingPolicy.objects.create(code="hist-test-policy", name="Historical Policy")
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

        self.listing = SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            status=SupplyListingStatus.ACTIVE,
        )

        self.ext_cp = ExternalCounterparty.objects.create(company_name="Hist CP Ltd")
        self.opportunity = Opportunity.objects.create(
            identifier="OPP-2026-000201",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.ext_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("150.000"),
        )

        self.cand_listing = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            supply_listing=self.listing,
        )

        self.cand_opp = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.DIRECT_SUPPLY,
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            supply_opportunity=self.opportunity,
        )

        self.cand_supplier = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            supplier_organization=self.supplier_org,
        )

        self.cand_broker = MatchingCandidate.objects.create(
            run=self.run,
            lane=CandidateLane.BROKER_PATH,
            candidate_kind=CandidateKind.BROKER_ORGANIZATION,
            broker_organization=self.broker_org,
        )

        self.signal = MatchingSignal.objects.create(
            candidate=self.cand_listing,
            dimension=SignalDimension.SPECIFICATION,
            code="spec.penetration_grade",
            outcome=SignalOutcome.PASS,
            weight=Decimal("45.00"),
            raw_score=Decimal("1.0000"),
            contribution=Decimal("45.00"),
        )

    def test_rfq_deletion_protected(self):
        """Prove that deleting an RFQ referenced by a MatchingRun is protected."""
        with self.assertRaises(ProtectedError):
            self.rfq.delete()

    def test_supply_listing_deletion_protected(self):
        """Prove that deleting a SupplyListing referenced by a MatchingCandidate is protected."""
        with self.assertRaises(ProtectedError):
            self.listing.delete()

    def test_opportunity_deletion_protected(self):
        """Prove that deleting an Opportunity referenced by a MatchingCandidate is protected."""
        with self.assertRaises(ProtectedError):
            self.opportunity.delete()

    def test_organization_deletion_protected(self):
        """Prove that deleting Organizations referenced by run or candidate is protected."""
        # Referenced as requesting_organization on run
        with self.assertRaises(ProtectedError):
            self.buyer_org.delete()

        # Referenced as broker_organization on candidate
        with self.assertRaises(ProtectedError):
            self.broker_org.delete()

        # Referenced as supplier_organization on candidate
        with self.assertRaises(ProtectedError):
            self.supplier_org.delete()

    def test_policy_version_deletion_protected(self):
        """Prove that deleting a MatchingPolicyVersion referenced by a MatchingRun is protected."""
        # Direct model deletion raises ValidationError (published/retired immutable)
        with self.assertRaises(ValidationError):
            self.policy_version.delete()

        # ORM QuerySet deletion raises ProtectedError due to on_delete=models.PROTECT on MatchingRun
        with self.assertRaises(ProtectedError):
            MatchingPolicyVersion.objects.filter(pk=self.policy_version.pk).delete()

    def test_historical_records_immutability(self):
        """Prove that historical matching records cannot be modified after creation."""
        # MatchingRun cannot be updated
        self.run.engine_version = "modified-engine"
        with self.assertRaises(ValidationError):
            self.run.save()

        # MatchingCandidate cannot be updated
        self.cand_listing.eligible = False
        with self.assertRaises(ValidationError):
            self.cand_listing.save()

        # MatchingSignal cannot be updated
        self.signal.raw_score = Decimal("0.5000")
        with self.assertRaises(ValidationError):
            self.signal.save()

    def test_historical_records_direct_delete_prevented(self):
        """Prove that historical matching records cannot be deleted directly."""
        with self.assertRaises(ValidationError):
            self.run.delete()

        with self.assertRaises(ValidationError):
            self.cand_listing.delete()

        with self.assertRaises(ValidationError):
            self.signal.delete()
