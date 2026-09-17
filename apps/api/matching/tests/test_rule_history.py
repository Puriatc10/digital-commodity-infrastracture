from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence
import uuid

from django.test import TestCase

from matching.candidates.snapshot import CandidateSnapshot
from matching.enums import CandidateKind, CandidateLane, MatchingAudience, SignalDimension, SignalOutcome
from matching.rules.history import (
    HistoricalEvaluationContext,
    HistoricalProviderError,
    HistoricalProviderRegistry,
    HistoricalSignalProvider,
    HistoryReasonCode,
    evaluate_historical_signals,
    evaluate_history,
)
from matching.rules.result import RuleResult


class SampleMockProvider:
    """Mock provider conforming to HistoricalSignalProvider protocol for testing."""

    def __init__(
        self,
        code: str = "history.sample",
        supported_kinds: Optional[Sequence[str]] = None,
        return_results: Optional[Sequence[RuleResult]] = None,
        raise_error: Optional[Exception] = None,
    ):
        self.code = code
        self.supported_kinds = supported_kinds or [CandidateKind.SUPPLIER_ORGANIZATION]
        self.return_results = return_results
        self.raise_error = raise_error

    def supports_candidate_kind(self, candidate_kind: str) -> bool:
        return candidate_kind in self.supported_kinds

    def evaluate(
        self,
        candidate: Any,
        context: HistoricalEvaluationContext,
        policy_version: Optional[Any] = None,
    ) -> Sequence[RuleResult]:
        if self.raise_error:
            raise self.raise_error

        if self.return_results is not None:
            return self.return_results

        evidence = getattr(candidate, "evidence", {}) if hasattr(candidate, "evidence") else {}
        history_evidence = evidence.get("historical_deals")

        if history_evidence is None:
            return (
                RuleResult(
                    code=self.code,
                    dimension=SignalDimension.HISTORY.value,
                    outcome=SignalOutcome.UNKNOWN,
                    is_hard=False,
                    raw_score=None,
                    reason_code=HistoryReasonCode.HISTORICAL_EVIDENCE_UNAVAILABLE.value,
                    expected={"min_completed_deals": 1},
                    actual={"completed_deals": None},
                ),
            )

        # Has evidence
        completed = history_evidence.get("completed_count", 0)
        score = Decimal("1.0000") if completed >= 5 else Decimal("0.7500")
        return (
            RuleResult(
                code=self.code,
                dimension=SignalDimension.HISTORY.value,
                outcome=SignalOutcome.PASS if score >= Decimal("1.0000") else SignalOutcome.PARTIAL,
                is_hard=False,
                raw_score=score,
                reason_code=HistoryReasonCode.HISTORICAL_EVALUATION_SUCCESS.value,
                expected={"min_completed_deals": 5},
                actual={"completed_deals": completed},
            ),
        )


class HistoricalProviderContractTests(TestCase):
    """
    Unit tests for the HistoricalSignalProvider protocol, registry, and deterministic ordering.
    """

    def test_protocol_conformance(self):
        """Verify mock provider satisfies runtime checkable HistoricalSignalProvider protocol."""
        provider = SampleMockProvider()
        self.assertIsInstance(provider, HistoricalSignalProvider)

    def test_evaluate_history_alias(self):
        """Verify evaluate_history is an exact alias for evaluate_historical_signals."""
        self.assertIs(evaluate_history, evaluate_historical_signals)

    def test_registry_registration_and_clearing(self):
        """Verify registry correctly manages providers and clears cleanly."""
        reg = HistoricalProviderRegistry()
        self.assertEqual(len(reg.get_providers()), 0)

        p1 = SampleMockProvider(code="history.alpha")
        p2 = SampleMockProvider(code="history.beta")
        reg.register(p1)
        reg.register(p2)

        self.assertEqual(len(reg.get_providers()), 2)
        reg.unregister("history.alpha")
        self.assertEqual(len(reg.get_providers()), 1)
        self.assertEqual(reg.get_providers()[0].code, "history.beta")

        reg.clear()
        self.assertEqual(len(reg.get_providers()), 0)

    def test_registry_deterministic_ordering(self):
        """Verify registry returns providers in strictly alphabetical order by provider.code."""
        reg = HistoricalProviderRegistry()
        # Register in reverse or random order
        reg.register(SampleMockProvider(code="history.zeta"))
        reg.register(SampleMockProvider(code="history.alpha"))
        reg.register(SampleMockProvider(code="history.mu"))

        providers = reg.get_providers()
        codes = [p.code for p in providers]
        self.assertEqual(codes, ["history.alpha", "history.mu", "history.zeta"])

    def test_register_invalid_provider_fails(self):
        """Verify registering provider without code raises ValueError."""
        reg = HistoricalProviderRegistry()

        class BadProvider:
            code = ""

        with self.assertRaises(ValueError):
            reg.register(BadProvider())  # type: ignore


class NoProviderHonestDefaultTests(TestCase):
    """
    Mandatory tests for default honest behavior:
    When no historical provider exists today in production,
    evaluate_historical_signals returns NOT_APPLICABLE with raw_score=None.
    """

    def _create_snapshot(self, kind: str) -> CandidateSnapshot:
        return CandidateSnapshot.create(
            candidate_kind=kind,
            source_id=uuid.uuid4(),
            evidence={},
        )

    def test_no_provider_supply_listing(self):
        cand = self._create_snapshot(CandidateKind.SUPPLY_LISTING)
        results = evaluate_historical_signals(cand)

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.code, "history")
        self.assertEqual(res.dimension, SignalDimension.HISTORY.value)
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertFalse(res.is_hard)
        self.assertTrue(res.is_eligible)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_DATA_NOT_APPLICABLE.value)
        self.assertFalse(res.expected["requires_history"])
        self.assertEqual(res.actual["provider_count"], 0)

    def test_no_provider_supply_opportunity(self):
        cand = self._create_snapshot(CandidateKind.SUPPLY_OPPORTUNITY)
        results = evaluate_historical_signals(cand)

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_DATA_NOT_APPLICABLE.value)

    def test_no_provider_supplier_organization(self):
        cand = self._create_snapshot(CandidateKind.SUPPLIER_ORGANIZATION)
        results = evaluate_historical_signals(cand)

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_DATA_NOT_APPLICABLE.value)

    def test_no_provider_broker_organization(self):
        cand = self._create_snapshot(CandidateKind.BROKER_ORGANIZATION)
        results = evaluate_historical_signals(cand)

        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_DATA_NOT_APPLICABLE.value)


class CandidateKindApplicabilityTests(TestCase):
    """
    Tests that unsupported candidate kinds produce NOT_APPLICABLE, not failure.
    """

    def test_unsupported_candidate_kind_is_not_applicable(self):
        """A provider supporting only SUPPLIER_ORGANIZATION returns NOT_APPLICABLE for SUPPLY_LISTING."""
        provider = SampleMockProvider(
            code="history.supplier_only",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uuid.uuid4(),
            evidence={},
        )

        results = evaluate_historical_signals(cand, providers=[provider])
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_KIND_NOT_SUPPORTED.value)
        self.assertFalse(res.is_hard)


class ApplicableButMissingEvidenceTests(TestCase):
    """
    Tests for applicable provider with missing candidate evidence.
    Must produce UNKNOWN, raw_score=None, never 0.00.
    """

    def test_applicable_provider_missing_evidence_yields_unknown(self):
        provider = SampleMockProvider(
            code="history.deals",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={"organization_id": str(uuid.uuid4())},  # no historical_deals
        )

        results = evaluate_historical_signals(cand, providers=[provider])
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.code, "history.deals")
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertFalse(res.is_hard)
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_EVIDENCE_UNAVAILABLE.value)

    def test_applicable_provider_with_evidence_yields_pass_score(self):
        provider = SampleMockProvider(
            code="history.deals",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={
                "historical_deals": {"completed_count": 10},
            },
        )

        results = evaluate_historical_signals(cand, providers=[provider])
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.PASS)
        self.assertEqual(res.raw_score, Decimal("1.0000"))
        self.assertEqual(res.reason_code, HistoryReasonCode.HISTORICAL_EVALUATION_SUCCESS.value)


class DifferenceNAPerVsUnknownTests(TestCase):
    """
    Explicitly proves that NOT_APPLICABLE != UNKNOWN.
    """

    def test_explicit_distinction_na_vs_unknown(self):
        # 1. No provider applies -> NOT_APPLICABLE
        cand_na = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uuid.uuid4(),
            evidence={},
        )
        results_na = evaluate_historical_signals(cand_na, providers=[])
        res_na = results_na[0]

        # 2. Provider applies, but evidence missing -> UNKNOWN
        provider = SampleMockProvider(
            code="history.track_record",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )
        cand_unknown = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={},
        )
        results_unknown = evaluate_historical_signals(cand_unknown, providers=[provider])
        res_unknown = results_unknown[0]

        # Proof of distinction
        self.assertNotEqual(res_na.outcome, res_unknown.outcome)
        self.assertEqual(res_na.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertEqual(res_unknown.outcome, SignalOutcome.UNKNOWN)
        self.assertNotEqual(res_na.reason_code, res_unknown.reason_code)

        # Both agree on null numeric score (never 0.00)
        self.assertIsNone(res_na.raw_score)
        self.assertIsNone(res_unknown.raw_score)


class ExternalCounterpartyHistoricalTests(TestCase):
    """
    Mandatory tests for ExternalCounterparty:
    No platform history is not a negative signal.
    Never automatically 0.00.
    """

    def test_external_counterparty_no_provider_is_not_applicable(self):
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            source_id=uuid.uuid4(),
            evidence={
                "counterparty": {
                    "is_external": True,
                    "external_counterparty_id": str(uuid.uuid4()),
                    "company_name": "External Refinery FZCO",
                }
            },
        )

        results = evaluate_historical_signals(cand)
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res.raw_score)
        self.assertNotEqual(res.raw_score, Decimal("0.00"))

    def test_external_counterparty_with_applicable_provider_no_data_is_unknown(self):
        provider = SampleMockProvider(
            code="history.counterparty_history",
            supported_kinds=[CandidateKind.SUPPLY_OPPORTUNITY],
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_OPPORTUNITY,
            source_id=uuid.uuid4(),
            evidence={
                "counterparty": {
                    "is_external": True,
                    "external_counterparty_id": str(uuid.uuid4()),
                }
            },
        )

        results = evaluate_historical_signals(cand, providers=[provider])
        res = results[0]
        self.assertEqual(res.outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res.raw_score)
        self.assertNotEqual(res.raw_score, Decimal("0.00"))


class BrokerSupplierIsolationTests(TestCase):
    """
    Mandatory tests for Broker / Supplier isolation:
    No trust/history transfer between actors.
    """

    def test_broker_history_does_not_transfer_to_supplier(self):
        """Broker history cannot be attributed to SupplierOrganization."""
        broker_provider = SampleMockProvider(
            code="history.broker_deals",
            supported_kinds=[CandidateKind.BROKER_ORGANIZATION],
        )
        supplier_provider = SampleMockProvider(
            code="history.supplier_deals",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )

        supplier_cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={
                "organization_id": str(uuid.uuid4()),
                # Even if candidate evidence maliciously had broker data
                "broker_attribution": {"broker_deals": 20},
            },
        )

        # Evaluate against both providers
        results = evaluate_historical_signals(
            supplier_cand,
            providers=[broker_provider, supplier_provider],
        )

        # Only supplier provider should have evaluated
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].code, "history.supplier_deals")
        self.assertEqual(results[0].outcome, SignalOutcome.UNKNOWN)

    def test_supplier_history_does_not_transfer_to_broker(self):
        """Supplier history cannot be attributed to BrokerOrganization."""
        broker_provider = SampleMockProvider(
            code="history.broker_deals",
            supported_kinds=[CandidateKind.BROKER_ORGANIZATION],
        )
        supplier_provider = SampleMockProvider(
            code="history.supplier_deals",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )

        broker_cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.BROKER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={"organization_id": str(uuid.uuid4())},
        )

        results = evaluate_historical_signals(
            broker_cand,
            providers=[broker_provider, supplier_provider],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].code, "history.broker_deals")
        self.assertEqual(results[0].outcome, SignalOutcome.UNKNOWN)


class PrivacyBoundaryTests(TestCase):
    """
    Mandatory tests for privacy boundaries:
    Buyer runs must not gain evidence from hidden internal Opportunity Desk records.
    """

    def test_buyer_context_privacy(self):
        """Ensure Buyer context is explicitly carried and does not leak internal operational data."""
        ctx_buyer = HistoricalEvaluationContext(
            evaluation_time=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc),
            audience=MatchingAudience.BUYER,
            target_rfq_id=str(uuid.uuid4()),
        )

        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLY_LISTING,
            source_id=uuid.uuid4(),
            evidence={
                "organization_id": str(uuid.uuid4()),
            },
        )

        results = evaluate_historical_signals(cand, context=ctx_buyer)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, SignalOutcome.NOT_APPLICABLE)
        # Ensure actual values leak no internal operational fields
        self.assertNotIn("internal_notes", results[0].actual)
        self.assertNotIn("contact_attempts", results[0].actual)


class ProviderErrorBehaviorTests(TestCase):
    """
    Mandatory tests for provider failure handling:
    Provider execution failure must be surfaced as HistoricalProviderError,
    never silently converted to UNKNOWN or 0.00.
    """

    def test_provider_runtime_exception_is_surfaced(self):
        provider = SampleMockProvider(
            code="history.failing_provider",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
            raise_error=RuntimeError("Database connection dropped during historical query"),
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={},
        )

        with self.assertRaises(HistoricalProviderError) as ctx:
            evaluate_historical_signals(cand, providers=[provider])

        self.assertIn("history.failing_provider", str(ctx.exception))
        self.assertIn("Database connection dropped", str(ctx.exception))

    def test_provider_returning_hard_rule_fails(self):
        provider = SampleMockProvider(
            code="history.invalid_hard",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
            return_results=(
                RuleResult(
                    code="history.invalid_hard",
                    dimension=SignalDimension.HISTORY.value,
                    outcome=SignalOutcome.FAIL,
                    is_hard=True,  # Hard failure forbidden in history v1
                    raw_score=None,
                ),
            ),
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={},
        )

        with self.assertRaises(ValueError) as ctx:
            evaluate_historical_signals(cand, providers=[provider])
        self.assertIn("must be soft", str(ctx.exception))

    def test_provider_returning_unknown_with_score_fails(self):
        provider = SampleMockProvider(
            code="history.invalid_score",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
            return_results=(
                RuleResult(
                    code="history.invalid_score",
                    dimension=SignalDimension.HISTORY.value,
                    outcome=SignalOutcome.UNKNOWN,
                    is_hard=False,
                    raw_score=Decimal("0.5000"),  # Score forbidden for UNKNOWN
                ),
            ),
        )
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={},
        )

        with self.assertRaises(ValueError) as ctx:
            evaluate_historical_signals(cand, providers=[provider])
        self.assertIn("raw_score must be None for UNKNOWN", str(ctx.exception))

    def test_provider_returning_float_score_fails(self):
        # We construct a provider returning a mock with float raw_score
        class FloatScoreProvider:
            code = "history.float_score"

            def supports_candidate_kind(self, candidate_kind: str) -> bool:
                return True

            def evaluate(self, candidate, context, policy_version=None):
                class FakeResult:
                    code = "history.float_score"
                    dimension = "HISTORY"
                    outcome = "PASS"
                    is_hard = False
                    raw_score = 0.85  # Float forbidden
                    reason_code = "FLOAT_SCORE"
                    expected = None
                    actual = None

                return (FakeResult(),)

        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={},
        )

        with self.assertRaises(TypeError) as ctx:
            evaluate_historical_signals(cand, providers=[FloatScoreProvider()])  # type: ignore
        self.assertIn("Must be Decimal", str(ctx.exception))


class DeterminismAndImmutabilityTests(TestCase):
    """
    Mandatory tests for determinism, immutability, and explicit evaluation time.
    """

    def test_determinism_with_explicit_context(self):
        eval_time = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
        ctx = HistoricalEvaluationContext(
            evaluation_time=eval_time,
            audience=MatchingAudience.BUYER,
            target_rfq_id=str(uuid.uuid4()),
        )

        provider = SampleMockProvider(
            code="history.reproducible",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )

        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence={"historical_deals": {"completed_count": 8}},
        )

        # Run multiple times consecutively
        res1 = evaluate_historical_signals(cand, context=ctx, providers=[provider])
        res2 = evaluate_historical_signals(cand, context=ctx, providers=[provider])

        self.assertEqual(len(res1), len(res2))
        self.assertEqual(res1[0].to_dict(), res2[0].to_dict())

    def test_candidate_snapshot_is_not_mutated(self):
        evidence_copy = {
            "organization_id": str(uuid.uuid4()),
            "historical_deals": {"completed_count": 3},
        }
        cand = CandidateSnapshot.create(
            candidate_kind=CandidateKind.SUPPLIER_ORGANIZATION,
            source_id=uuid.uuid4(),
            evidence=dict(evidence_copy),
        )

        provider = SampleMockProvider(
            code="history.immutable_check",
            supported_kinds=[CandidateKind.SUPPLIER_ORGANIZATION],
        )

        evaluate_historical_signals(cand, providers=[provider])

        # Candidate snapshot remains identical
        self.assertEqual(cand.evidence, evidence_copy)
        self.assertEqual(cand.candidate_kind, CandidateKind.SUPPLIER_ORGANIZATION)
        self.assertEqual(cand.lane, CandidateLane.POTENTIAL_SUPPLIER)
