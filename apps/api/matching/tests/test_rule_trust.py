from decimal import Decimal
import uuid

from django.test import TestCase

from commodities.models import CommodityDefinition, CommoditySchemaVersion
from matching.candidates.context import ActorScope, CandidateContext
from matching.candidates.snapshot import CandidateSnapshot, CandidateTrustSnapshot
from matching.candidates.supply_listing import SupplyListingCandidateProvider
from matching.candidates.supply_opportunity import SupplyOpportunityCandidateProvider
from matching.candidates.supplier_organization import SupplierOrganizationCandidateProvider
from matching.candidates.broker_organization import BrokerCandidateProvider
from matching.enums import (
    CandidateKind,
    CandidateLane,
    MatchingAudience,
    SignalDimension,
    SignalOutcome,
)
from matching.rules.trust import (
    TrustReasonCode,
    evaluate_trust,
)
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
)
from organizations.verification.models import (
    OrganizationVerification,
    VerificationStatus,
)
from trade_hub.models import RFQ, RFQStatus, SupplyListing, SupplyListingStatus


class TrustEvaluatorMappingTests(TestCase):
    """
    Unit tests for pure evaluate_trust mapping across all approved verification states.
    """

    def test_verified_maps_to_pass_score_one(self):
        """Verified -> PASS, Decimal('1.00'), is_hard=False."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="verified",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.PASS)
        self.assertEqual(result.raw_score, Decimal("1.00"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_VERIFIED.value)

    def test_basic_verified_maps_to_partial_point_seven(self):
        """Basic Verified -> PARTIAL, Decimal('0.70'), is_hard=False."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="basic_verified",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(result.raw_score, Decimal("0.70"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_BASIC_VERIFIED.value)

    def test_under_review_maps_to_partial_point_three(self):
        """Under Review -> PARTIAL, Decimal('0.30'), is_hard=False."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="under_review",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(result.raw_score, Decimal("0.30"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_UNDER_REVIEW.value)

    def test_documents_submitted_maps_to_partial_point_fifteen(self):
        """Documents Submitted -> PARTIAL, Decimal('0.15'), is_hard=False."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="documents_submitted",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(result.raw_score, Decimal("0.15"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_DOCUMENTS_SUBMITTED.value)

    def test_unverified_maps_to_fail_score_zero_soft(self):
        """Unverified -> FAIL, Decimal('0.00'), is_hard=False (candidate remains eligible)."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="unverified",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.FAIL)
        self.assertEqual(result.raw_score, Decimal("0.00"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_UNVERIFIED.value)

    def test_suspended_maps_to_hard_fail_score_none(self):
        """Suspended -> FAIL, raw_score=None, is_hard=True (candidate is ineligible)."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status="suspended",
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.FAIL)
        self.assertIsNone(result.raw_score)
        self.assertTrue(result.is_hard)
        self.assertFalse(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_SUSPENDED.value)

    def test_external_counterparty_mandatory_unknown(self):
        """ExternalCounterparty strictly produces UNKNOWN, raw_score=None, is_hard=False."""
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            is_external=True,
            verification_status=None,
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(result.raw_score)
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.code, "trust")
        self.assertEqual(result.dimension, SignalDimension.TRUST.value)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_EXTERNAL_COUNTERPARTY.value)
        self.assertTrue(result.actual["is_external"])
        self.assertEqual(result.actual["counterparty_kind"], "ExternalCounterparty")

    def test_exact_decimal_types_enforced(self):
        """Verify scores are exact Decimals and not Python floats."""
        for state, expected_score, expected_outcome, expected_hard in [
            ("verified", Decimal("1.00"), SignalOutcome.PASS, False),
            ("basic_verified", Decimal("0.70"), SignalOutcome.PARTIAL, False),
            ("under_review", Decimal("0.30"), SignalOutcome.PARTIAL, False),
            ("documents_submitted", Decimal("0.15"), SignalOutcome.PARTIAL, False),
            ("unverified", Decimal("0.00"), SignalOutcome.FAIL, False),
        ]:
            cand = CandidateTrustSnapshot(
                candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
                is_external=False,
                verification_status=state,
            )
            res = evaluate_trust(cand)
            self.assertIsInstance(res.raw_score, Decimal)
            self.assertEqual(res.raw_score, expected_score)
            self.assertEqual(res.outcome, expected_outcome)
            self.assertEqual(res.is_hard, expected_hard)


class TrustCandidateKindResolutionTests(TestCase):
    """
    Integration tests verifying trust evidence resolution for all 4 candidate kinds.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Buyer Org", is_active=True)
        self.supplier_org = Organization.objects.create(name="Supplier Org", is_active=True)
        self.broker_org = Organization.objects.create(name="Broker Org", is_active=True)

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-trust-test", name_en="Bitumen", name_fa="قیر"
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=RFQStatus.PUBLISHED,
        )
        self.context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.BUYER,
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.buyer_user = User.objects.create(email="buyer@trust-test.com")
        from organizations.models import OrganizationMembership
        OrganizationMembership.objects.create(
            user=self.buyer_user,
            organization=self.buyer_org,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        self.actor_scope = ActorScope(
            user=self.buyer_user,
            organization=self.buyer_org,
            is_operator_or_admin=False,
        )

    def test_supply_listing_trust_derived_from_owner(self):
        """Supply Listing candidate trust is derived from owning Supplier Organization verification."""
        OrganizationVerification.objects.create(
            organization=self.supplier_org,
            status=VerificationStatus.BASIC_VERIFIED,
        )
        SupplyListing.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            status=SupplyListingStatus.ACTIVE,
        )

        provider = SupplyListingCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        result = evaluate_trust(candidates[0])
        self.assertEqual(result.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(result.raw_score, Decimal("0.70"))
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_BASIC_VERIFIED.value)
        self.assertEqual(result.actual["verification_status"], "basic_verified")

    def test_supply_opportunity_internal_organization_trust(self):
        """Supply Opportunity with internal counterparty uses that Organization's verification."""
        internal_supplier = Organization.objects.create(name="Internal Opp Supplier")
        OrganizationVerification.objects.create(
            organization=internal_supplier,
            status=VerificationStatus.VERIFIED,
        )
        Opportunity.objects.create(
            identifier="OPP-INT-001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            organization=internal_supplier,
        )

        op_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.OPERATOR,
        )
        op_scope = ActorScope(user=None, organization=None, is_operator_or_admin=True)

        provider = SupplyOpportunityCandidateProvider()
        candidates = provider.find_candidates(op_context, op_scope)
        self.assertEqual(len(candidates), 1)

        result = evaluate_trust(candidates[0])
        self.assertEqual(result.outcome, SignalOutcome.PASS)
        self.assertEqual(result.raw_score, Decimal("1.00"))
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_VERIFIED.value)

    def test_supply_opportunity_external_counterparty_trust(self):
        """Supply Opportunity with ExternalCounterparty strictly produces UNKNOWN."""
        ext_cp = ExternalCounterparty.objects.create(company_name="Overseas Refinery Corp")
        Opportunity.objects.create(
            identifier="OPP-EXT-001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("500.000"),
            external_counterparty=ext_cp,
        )

        op_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.OPERATOR,
        )
        op_scope = ActorScope(user=None, organization=None, is_operator_or_admin=True)

        provider = SupplyOpportunityCandidateProvider()
        candidates = provider.find_candidates(op_context, op_scope)
        self.assertEqual(len(candidates), 1)

        result = evaluate_trust(candidates[0])
        self.assertEqual(result.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(result.raw_score)
        self.assertFalse(result.is_hard)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_EXTERNAL_COUNTERPARTY.value)

    def test_supplier_organization_candidate_trust(self):
        """Supplier Organization candidate uses its own verification status."""
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCommodity.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
        )
        OrganizationVerification.objects.create(
            organization=self.supplier_org,
            status=VerificationStatus.DOCUMENTS_SUBMITTED,
        )

        provider = SupplierOrganizationCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        result = evaluate_trust(candidates[0])
        self.assertEqual(result.outcome, SignalOutcome.PARTIAL)
        self.assertEqual(result.raw_score, Decimal("0.15"))
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_DOCUMENTS_SUBMITTED.value)

    def test_broker_organization_candidate_trust(self):
        """Broker Organization candidate in BROKER_PATH lane uses its own verification."""
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationCommodity.objects.create(
            organization=self.broker_org,
            commodity=self.commodity,
        )
        OrganizationVerification.objects.create(
            organization=self.broker_org,
            status=VerificationStatus.VERIFIED,
        )

        provider = BrokerCandidateProvider()
        candidates = provider.find_candidates(self.context, self.actor_scope)
        self.assertEqual(len(candidates), 1)

        result = evaluate_trust(candidates[0])
        self.assertEqual(result.outcome, SignalOutcome.PASS)
        self.assertEqual(result.raw_score, Decimal("1.00"))
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_VERIFIED.value)


class TrustBrokerReferralIsolationTests(TestCase):
    """
    Mandatory Broker Referral isolation tests:
    Supply Opportunity from Broker Referral with ExternalCounterparty produces UNKNOWN,
    even if the referring Broker is Verified.
    Broker's own BROKER_PATH candidate separately produces 1.00.
    """

    def setUp(self):
        self.buyer_org = Organization.objects.create(name="Isolation Buyer Org")
        self.broker_org = Organization.objects.create(name="Verified Broker Org")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        # Broker is fully VERIFIED
        OrganizationVerification.objects.create(
            organization=self.broker_org,
            status=VerificationStatus.VERIFIED,
        )

        self.commodity = CommodityDefinition.objects.create(
            code="bitumen-isolation-test", name_en="Bitumen", name_fa="قیر"
        )
        OrganizationCommodity.objects.create(
            organization=self.broker_org,
            commodity=self.commodity,
        )
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED,
        )

        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("1000.000"),
            status=RFQStatus.PUBLISHED,
        )
        self.op_context = CandidateContext(
            rfq_id=self.rfq.id,
            rfq_owner_organization_id=self.buyer_org.id,
            commodity_id=self.commodity.id,
            audience=MatchingAudience.OPERATOR,
        )
        self.op_scope = ActorScope(user=None, organization=None, is_operator_or_admin=True)

        # External counterparty referred by Broker
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="External Refinery Referred By Broker",
            geography="TR",
        )
        self.opp = Opportunity.objects.create(
            identifier="OPP-BRK-REF-001",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            commodity=self.commodity,
            schema_version=self.schema,
            quantity=Decimal("1000.000"),
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            external_counterparty=self.external_cp,
        )

    def test_broker_referral_external_counterparty_isolation(self):
        """
        Evaluating Supply Opportunity candidate from Broker Referral:
        Counterparty = ExternalCounterparty
        Broker = Verified Organization
        Trust result MUST be UNKNOWN (never 1.00 from the broker).
        """
        opp_provider = SupplyOpportunityCandidateProvider()
        opp_candidates = opp_provider.find_candidates(self.op_context, self.op_scope)
        self.assertEqual(len(opp_candidates), 1)

        opp_candidate = opp_candidates[0]
        opp_trust_result = evaluate_trust(opp_candidate)

        self.assertEqual(opp_trust_result.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(opp_trust_result.raw_score)
        self.assertFalse(opp_trust_result.is_hard)
        self.assertEqual(opp_trust_result.reason_code, TrustReasonCode.TRUST_EXTERNAL_COUNTERPARTY.value)

    def test_broker_own_candidate_evaluates_independently(self):
        """
        The Broker's own candidate in the BROKER_PATH lane independently produces 1.00 (PASS).
        """
        broker_provider = BrokerCandidateProvider()
        broker_candidates = broker_provider.find_candidates(self.op_context, self.op_scope)
        self.assertEqual(len(broker_candidates), 1)

        broker_candidate = broker_candidates[0]
        broker_trust_result = evaluate_trust(broker_candidate)

        self.assertEqual(broker_trust_result.outcome, SignalOutcome.PASS)
        self.assertEqual(broker_trust_result.raw_score, Decimal("1.00"))
        self.assertFalse(broker_trust_result.is_hard)
        self.assertEqual(broker_trust_result.reason_code, TrustReasonCode.TRUST_VERIFIED.value)


class TrustMissingVerificationSemanticsTests(TestCase):
    """
    Tests proving repository source-of-truth semantics for missing verification records.
    """

    def setUp(self):
        self.org_no_row = Organization.objects.create(name="Unverified Org Without Row")

    def test_absent_verification_row_maps_to_unverified(self):
        """
        Organization without an OrganizationVerification row evaluates to Unverified:
        FAIL, Decimal('0.00'), is_hard=False, is_eligible=True.
        """
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            is_external=False,
            verification_status=None,
            organization_id=str(self.org_no_row.id),
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.FAIL)
        self.assertEqual(result.raw_score, Decimal("0.00"))
        self.assertFalse(result.is_hard)
        self.assertTrue(result.is_eligible)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_UNVERIFIED.value)

    def test_external_counterparty_never_maps_to_unverified(self):
        """
        ExternalCounterparty has no verification row, but MUST NOT map to Unverified (0.00).
        It strictly maps to UNKNOWN.
        """
        cand = CandidateTrustSnapshot(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            is_external=True,
            verification_status=None,
            organization_id=None,
        )
        result = evaluate_trust(cand)
        self.assertEqual(result.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(result.raw_score)
        self.assertNotEqual(result.outcome, SignalOutcome.FAIL)
        self.assertNotEqual(result.raw_score, Decimal("0.00"))


class TrustSuspensionHardExclusionRegressionTests(TestCase):
    """
    Regression test ensuring Suspended candidates produce hard failure regardless of other evidence.
    """

    def test_suspended_candidate_hard_failure_no_compensation(self):
        """
        Even with perfect other dimensions, a candidate with Suspended verification
        produces an uncompromising hard failure in the trust rule.
        """
        suspended_cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            lane=CandidateLane.POTENTIAL_SUPPLIER,
            evidence={
                "organization_id": str(uuid.uuid4()),
                "organization_name": "Suspended Supplier Inc",
                "verification_status": "suspended",
                "quantity": "1000.000",
                "specifications": {"penetration": "65"},
            },
        )

        result = evaluate_trust(suspended_cand)
        self.assertEqual(result.outcome, SignalOutcome.FAIL)
        self.assertIsNone(result.raw_score)
        self.assertTrue(result.is_hard)
        self.assertFalse(result.is_eligible)
        self.assertEqual(result.reason_code, TrustReasonCode.TRUST_SUSPENDED.value)


class TrustSensitiveDataAbsenceTests(TestCase):
    """
    Verify that candidate snapshots and trust evaluations contain zero sensitive document metadata.
    """

    def test_snapshot_evidence_contains_no_verification_documents(self):
        supplier = Organization.objects.create(name="KYC Supplier")
        OrganizationCapability.objects.create(
            organization=supplier, capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        comm = CommodityDefinition.objects.create(code="kyc-comm", name_en="KYC Comm")
        OrganizationCommodity.objects.create(organization=supplier, commodity=comm)
        OrganizationVerification.objects.create(organization=supplier, status=VerificationStatus.VERIFIED)

        provider = SupplierOrganizationCandidateProvider()
        context = CandidateContext(
            rfq_id=uuid.uuid4(),
            rfq_owner_organization_id=uuid.uuid4(),
            commodity_id=comm.id,
            audience=MatchingAudience.BUYER,
        )
        scope = ActorScope(user=None, organization=None, is_operator_or_admin=False)
        candidates = provider.find_candidates(context, scope)
        self.assertEqual(len(candidates), 1)

        ev = candidates[0].evidence
        self.assertNotIn("documents", ev)
        self.assertNotIn("document_object_keys", ev)
        self.assertNotIn("reviewer_notes", ev)
        self.assertNotIn("notes", ev)
        self.assertNotIn("kyc", ev)
        self.assertNotIn("comments", ev)
        self.assertIn("verification_status", ev)
        self.assertEqual(ev["verification_status"], "verified")
