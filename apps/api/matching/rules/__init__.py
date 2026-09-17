from matching.rules.availability import evaluate_availability
from matching.rules.capability import evaluate_capability
from matching.rules.commodity import evaluate_commodity
from matching.rules.geography import (
    CandidateGeographySnapshot,
    GeographicEvidenceRole,
    GeographyConstraintMode,
    GeographyConstraintSnapshot,
    TargetGeographySnapshot,
    evaluate_geography,
)
from matching.rules.history import (
    HistoricalEvaluationContext,
    HistoricalProviderError,
    HistoricalProviderRegistry,
    HistoricalSignalProvider,
    HistoryReasonCode,
    default_historical_registry,
    evaluate_historical_signals,
    evaluate_history,
    get_historical_providers,
)
from matching.rules.lifecycle import evaluate_lifecycle
from matching.rules.quantity import evaluate_quantity
from matching.rules.result import RuleResult
from matching.rules.self_match import evaluate_self_match
from matching.rules.specification import (
    AttributeDefinitionSnapshot,
    SpecificationEvaluationResult,
    SpecificationReasonCode,
    SpecificationRuleSnapshot,
    check_attribute_snapshot_compatibility,
    evaluate_candidate_specifications,
    evaluate_specifications,
    materialize_attribute_snapshots,
    materialize_specification_rules,
)
from matching.rules.trust import (
    DEFAULT_VERIFICATION_RULES,
    TrustReasonCode,
    VerificationRuleSnapshot,
    evaluate_trust,
    materialize_verification_rules,
)

__all__ = [
    "AttributeDefinitionSnapshot",
    "CandidateGeographySnapshot",
    "DEFAULT_VERIFICATION_RULES",
    "GeographicEvidenceRole",
    "GeographyConstraintMode",
    "GeographyConstraintSnapshot",
    "HistoricalEvaluationContext",
    "HistoricalProviderError",
    "HistoricalProviderRegistry",
    "HistoricalSignalProvider",
    "HistoryReasonCode",
    "RuleResult",
    "SpecificationEvaluationResult",
    "SpecificationReasonCode",
    "SpecificationRuleSnapshot",
    "TargetGeographySnapshot",
    "TrustReasonCode",
    "VerificationRuleSnapshot",
    "check_attribute_snapshot_compatibility",
    "default_historical_registry",
    "evaluate_availability",
    "evaluate_candidate_specifications",
    "evaluate_capability",
    "evaluate_commodity",
    "evaluate_geography",
    "evaluate_historical_signals",
    "evaluate_history",
    "evaluate_lifecycle",
    "evaluate_quantity",
    "evaluate_self_match",
    "evaluate_specifications",
    "evaluate_trust",
    "get_historical_providers",
    "materialize_attribute_snapshots",
    "materialize_specification_rules",
    "materialize_verification_rules",
]
