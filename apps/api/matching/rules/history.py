from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from matching.enums import CandidateKind, SignalDimension, SignalOutcome
from matching.exceptions import HistoricalProviderError
from matching.rules.result import RuleResult

logger = logging.getLogger(__name__)


class HistoryReasonCode(str, Enum):
    """Machine-readable outcome explanation codes for historical evaluation."""

    HISTORICAL_DATA_NOT_APPLICABLE = "HISTORICAL_DATA_NOT_APPLICABLE"
    HISTORICAL_KIND_NOT_SUPPORTED = "HISTORICAL_KIND_NOT_SUPPORTED"
    HISTORICAL_EVIDENCE_UNAVAILABLE = "HISTORICAL_EVIDENCE_UNAVAILABLE"
    HISTORICAL_EVALUATION_SUCCESS = "HISTORICAL_EVALUATION_SUCCESS"
    HISTORICAL_PROVIDER_ERROR = "HISTORICAL_PROVIDER_ERROR"



@dataclass(frozen=True)
class HistoricalEvaluationContext:
    """
    Explicit evaluation context for historical signal calculations.

    Guarantees pure, reproducible evaluation by accepting an explicit reference
    evaluation time (preventing implicit wall-clock calls like now() deep in
    calculations), audience scope, and target RFQ identity.
    """

    evaluation_time: Optional[datetime] = None
    audience: Optional[str] = None
    target_rfq_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@runtime_checkable
class HistoricalSignalProvider(Protocol):
    """
    Narrow, composable protocol for historical signal providers.

    Each provider searches an authorized domain source and produces deterministic,
    structured RuleResult instances with dimension=SignalDimension.HISTORY.
    """

    code: str

    def supports_candidate_kind(self, candidate_kind: str) -> bool:
        """
        Return True if this provider can evaluate the specified candidate kind.

        Compatible with:
        - SUPPLY_LISTING
        - SUPPLY_OPPORTUNITY
        - SUPPLIER_ORGANIZATION
        - BROKER_ORGANIZATION
        """
        ...

    def evaluate(
        self,
        candidate: Any,
        context: HistoricalEvaluationContext,
        policy_version: Optional[Any] = None,
    ) -> Sequence[RuleResult]:
        """
        Evaluate historical evidence for a candidate snapshot under an explicit context.

        Returns a sequence of RuleResult value objects.
        """
        ...


class HistoricalProviderRegistry:
    """
    Thread-safe registry of HistoricalSignalProviders with deterministic ordering.

    Ensures provider execution order is always sorted by provider.code, eliminating
    any sensitivity to import or registration sequence.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, HistoricalSignalProvider] = {}

    def register(self, provider: HistoricalSignalProvider) -> None:
        """Register a provider. Stable key is provider.code."""
        if not hasattr(provider, "code") or not provider.code:
            raise ValueError("Provider must define a non-empty 'code' attribute.")
        self._providers[provider.code] = provider

    def unregister(self, provider_code: str) -> Optional[HistoricalSignalProvider]:
        """Unregister a provider by code."""
        return self._providers.pop(provider_code, None)

    def clear(self) -> None:
        """Clear all registered providers."""
        self._providers.clear()

    def get_providers(
        self,
        policy_version: Optional[Any] = None,
        audience: Optional[str] = None,
    ) -> Sequence[HistoricalSignalProvider]:
        """
        Return registered providers sorted deterministically by code.

        In production, the registry is empty by default until authoritative
        historical sources are introduced in later epics.
        """
        sorted_codes = sorted(self._providers.keys())
        return tuple(self._providers[code] for code in sorted_codes)


# Default global registry. In production v1, no authoritative historical providers
# exist, so this registry remains empty by default.
default_historical_registry = HistoricalProviderRegistry()


def get_historical_providers(
    policy_version: Optional[Any] = None,
    audience: Optional[str] = None,
) -> Sequence[HistoricalSignalProvider]:
    """Retrieve active historical providers in deterministic order."""
    return default_historical_registry.get_providers(
        policy_version=policy_version,
        audience=audience,
    )


def _resolve_candidate_kind(candidate: Any) -> str:
    """Extract candidate_kind safely from CandidateSnapshot or duck-typed object."""
    if hasattr(candidate, "candidate_kind"):
        return candidate.candidate_kind
    if isinstance(candidate, dict):
        return candidate.get("candidate_kind", "")
    return getattr(candidate, "candidate_kind", "")


def evaluate_historical_signals(
    candidate: Any,
    context: Optional[HistoricalEvaluationContext] = None,
    policy_version: Optional[Any] = None,
    providers: Optional[Sequence[HistoricalSignalProvider]] = None,
) -> Sequence[RuleResult]:
    """
    Pure, deterministic evaluator for candidate historical signals.

    Invariants:
    1. Honest Default Behavior: If no historical provider applies, returns a single
       RuleResult with outcome=NOT_APPLICABLE, raw_score=None, is_hard=False.
    2. UNKNOWN vs NOT_APPLICABLE:
       - No provider exists / candidate kind unsupported -> NOT_APPLICABLE (raw_score=None).
       - Provider applies but candidate evidence is unavailable -> UNKNOWN (raw_score=None, never 0.00).
    3. Error Transparency: Provider execution failures are surfaced as HistoricalProviderError,
       never silently swallowed or masked as UNKNOWN / favorable evidence.
    4. Determinism & Stability: Providers are executed in strict alphabetical order by code.
    5. Privacy Boundary: Never accesses internal opportunity notes or unverified operational data
       when audience is BUYER.
    6. Non-mutation: Never mutates the CandidateSnapshot.
    7. Decimal Precision: All numeric scores must be Decimal within [0.0000, 1.0000].
    """
    ctx = context or HistoricalEvaluationContext()
    candidate_kind = _resolve_candidate_kind(candidate)

    if providers is not None:
        candidate_providers = sorted(providers, key=lambda p: p.code)
    else:
        candidate_providers = list(
            get_historical_providers(
                policy_version=policy_version,
                audience=ctx.audience,
            )
        )

    # 1. Honest default when no providers are configured in the platform
    if not candidate_providers:
        logger.debug(
            "No historical providers registered. Returning NOT_APPLICABLE for candidate_kind=%s",
            candidate_kind,
        )
        return (
            RuleResult(
                code="history",
                dimension=SignalDimension.HISTORY.value,
                outcome=SignalOutcome.NOT_APPLICABLE,
                is_hard=False,
                raw_score=None,
                reason_code=HistoryReasonCode.HISTORICAL_DATA_NOT_APPLICABLE.value,
                expected={"requires_history": False},
                actual={
                    "candidate_kind": candidate_kind,
                    "provider_count": 0,
                },
            ),
        )

    # Filter providers supporting this candidate kind
    applicable_providers = [
        p for p in candidate_providers if p.supports_candidate_kind(candidate_kind)
    ]

    # If candidate kind is unsupported by all registered providers -> NOT_APPLICABLE
    if not applicable_providers:
        logger.debug(
            "No applicable historical provider supports candidate_kind=%s",
            candidate_kind,
        )
        return (
            RuleResult(
                code="history",
                dimension=SignalDimension.HISTORY.value,
                outcome=SignalOutcome.NOT_APPLICABLE,
                is_hard=False,
                raw_score=None,
                reason_code=HistoryReasonCode.HISTORICAL_KIND_NOT_SUPPORTED.value,
                expected={"supported_kinds": [ck.value for ck in CandidateKind]},
                actual={
                    "candidate_kind": candidate_kind,
                    "applicable_provider_count": 0,
                },
            ),
        )

    results: List[RuleResult] = []

    # Deterministic evaluation loop
    for provider in applicable_providers:
        try:
            provider_results = provider.evaluate(candidate, ctx, policy_version)
        except Exception as exc:
            provider_code = getattr(provider, "code", "unknown")
            logger.error(
                "Operational failure in historical provider '%s' for candidate_kind '%s'",
                provider_code,
                candidate_kind,
                exc_info=True,
            )
            raise HistoricalProviderError(
                f"Historical provider '{provider_code}' execution failed: {exc}",
                code="historical_provider_failure",
                provider_code=provider_code,
                original_exception=exc,
            ) from exc

        for res in provider_results:
            # Validate output contract conformance
            if res.dimension != SignalDimension.HISTORY.value:
                res = RuleResult(
                    code=res.code,
                    outcome=res.outcome,
                    is_hard=False,
                    raw_score=res.raw_score,
                    reason_code=res.reason_code,
                    expected=res.expected,
                    actual=res.actual,
                    dimension=SignalDimension.HISTORY.value,
                )

            # Enforce null score on non-evaluable outcomes
            if res.outcome in (SignalOutcome.UNKNOWN, SignalOutcome.NOT_APPLICABLE):
                if res.raw_score is not None:
                    raise ValueError(
                        f"Historical provider '{provider.code}' produced outcome '{res.outcome}' "
                        f"with non-null raw_score '{res.raw_score}'. raw_score must be None for UNKNOWN or NOT_APPLICABLE."
                    )

            # Enforce Decimal type for numeric scores
            if res.raw_score is not None and not isinstance(res.raw_score, Decimal):
                raise TypeError(
                    f"Historical provider '{provider.code}' produced raw_score of type "
                    f"{type(res.raw_score)}. Must be Decimal in [0.0000, 1.0000]."
                )

            # Enforce soft constraints
            if res.is_hard:
                raise ValueError(
                    f"Historical provider '{provider.code}' produced a hard rule result. "
                    "Historical signals must be soft (is_hard=False)."
                )

            logger.debug(
                "Historical signal evaluated: provider=%s, outcome=%s, score=%s, reason=%s",
                provider.code,
                res.outcome,
                res.raw_score,
                res.reason_code,
            )
            results.append(res)

    return tuple(results)


# Backward-compatible convenience alias
evaluate_history = evaluate_historical_signals
