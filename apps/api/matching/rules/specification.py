from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from matching.enums import SignalOutcome
from matching.models.specification_rule import SpecificationRuleOperator
from matching.rules.result import RuleResult


class SpecificationReasonCode(str, Enum):
    SPEC_EXACT_MATCH = "spec_exact_match"
    SPEC_VALUE_MISMATCH = "spec_value_mismatch"
    CANDIDATE_SPEC_MISSING = "candidate_spec_missing"
    MATCHING_RULE_NOT_CONFIGURED = "matching_rule_not_configured"
    SEMANTIC_IDENTITY_NOT_FOUND = "semantic_identity_not_found"
    SEMANTIC_COMPATIBILITY_FAILED = "semantic_compatibility_failed"
    UNIT_NOT_COMPARABLE = "unit_not_comparable"
    WITHIN_TOLERANCE = "within_tolerance"
    OUTSIDE_TOLERANCE = "outside_tolerance"
    MIN_REQUIREMENT_MET = "min_requirement_met"
    MIN_REQUIREMENT_NOT_MET = "min_requirement_not_met"
    MAX_ALLOWANCE_MET = "max_allowance_met"
    MAX_ALLOWANCE_EXCEEDED = "max_allowance_exceeded"
    RULE_OPERATOR_IGNORE = "rule_operator_ignore"
    RFQ_VALUE_NOT_SPECIFIED = "rfq_value_not_specified"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"


@dataclass(frozen=True)
class AttributeDefinitionSnapshot:
    """
    Normalized immutable snapshot of a CommodityAttributeDefinition.
    Decoupled from live Django model instances for pure analytical execution.
    """

    key: str
    label: str = ""
    data_type: str = "string"
    unit: str = ""
    enum_choices: Tuple[str, ...] = ()
    semantic_identity_id: Optional[UUID] = None
    commodity_id: Optional[UUID] = None
    schema_version_id: Optional[UUID] = None


@dataclass(frozen=True)
class SpecificationRuleSnapshot:
    """
    Normalized immutable snapshot of a SpecificationMatchingRule for an attribute semantic identity.
    """

    semantic_identity_id: UUID
    operator: str
    tolerance: Optional[Decimal] = None
    hard_constraint: bool = False
    relative_weight: Decimal = Decimal("1.0000")
    missing_data_policy: str = SignalOutcome.UNKNOWN

    def __post_init__(self):
        if self.operator not in SpecificationRuleOperator.values:
            raise ValueError(
                f"Invalid operator '{self.operator}'. Must be one of: {', '.join(SpecificationRuleOperator.values)}."
            )
        if self.missing_data_policy not in SignalOutcome.values:
            raise ValueError(
                f"Invalid missing_data_policy '{self.missing_data_policy}'. Must be one of: {', '.join(SignalOutcome.values)}."
            )


@dataclass(frozen=True)
class SpecificationEvaluationResult:
    """
    Evaluation result for a single specification attribute in the specification dimension.
    """

    dimension: str = "specifications"
    code: str = ""
    semantic_identity_id: Optional[UUID] = None
    outcome: str = SignalOutcome.UNKNOWN
    is_hard: bool = False
    raw_score: Optional[Decimal] = None
    relative_weight: Decimal = Decimal("1.0000")
    expected: Optional[Dict[str, Any]] = None
    actual: Optional[Dict[str, Any]] = None
    reason_code: str = ""

    def __post_init__(self):
        if self.outcome not in SignalOutcome.values:
            raise ValueError(
                f"Invalid outcome '{self.outcome}'. Must be one of: {', '.join(SignalOutcome.values)}."
            )
        if self.raw_score is not None:
            if not (Decimal("0.0000") <= self.raw_score <= Decimal("1.0000")):
                raise ValueError(f"raw_score must be between 0 and 1, got {self.raw_score}.")

    @property
    def is_eligible(self) -> bool:
        """A candidate remains eligible unless an applicable hard constraint produces FAIL."""
        if self.is_hard and self.outcome == SignalOutcome.FAIL:
            return False
        return True

    def to_rule_result(self) -> RuleResult:
        """Convert to standard RuleResult vocabulary."""
        return RuleResult(
            code=self.code,
            outcome=self.outcome,
            is_hard=self.is_hard,
            raw_score=self.raw_score,
            reason_code=self.reason_code,
            expected=self.expected,
            actual=self.actual,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Clean dictionary representation for serialization."""
        data = asdict(self)
        if self.raw_score is not None:
            data["raw_score"] = str(self.raw_score)
        if self.relative_weight is not None:
            data["relative_weight"] = str(self.relative_weight)
        if self.semantic_identity_id is not None:
            data["semantic_identity_id"] = str(self.semantic_identity_id)
        return data


def to_attribute_snapshot(attr: Any) -> AttributeDefinitionSnapshot:
    """Helper to convert CommodityAttributeDefinition or dict to AttributeDefinitionSnapshot."""
    if isinstance(attr, AttributeDefinitionSnapshot):
        return attr
    if isinstance(attr, dict):
        sem_id = attr.get("semantic_identity_id")
        if sem_id and not isinstance(sem_id, UUID):
            sem_id = UUID(str(sem_id))
        comm_id = attr.get("commodity_id")
        if comm_id and not isinstance(comm_id, UUID):
            comm_id = UUID(str(comm_id))
        ver_id = attr.get("schema_version_id")
        if ver_id and not isinstance(ver_id, UUID):
            ver_id = UUID(str(ver_id))
        return AttributeDefinitionSnapshot(
            key=attr.get("key", ""),
            label=attr.get("label", ""),
            data_type=attr.get("data_type", "string"),
            unit=attr.get("unit", ""),
            enum_choices=tuple(attr.get("enum_choices", ())),
            semantic_identity_id=sem_id,
            commodity_id=comm_id,
            schema_version_id=ver_id,
        )
    # Model instance
    unit_meta = getattr(attr, "unit_metadata", {}) or {}
    unit = unit_meta.get("canonical_unit", "") if isinstance(unit_meta, dict) else ""
    enum_meta = getattr(attr, "enum_metadata", {}) or {}
    enum_choices = []
    if isinstance(enum_meta, dict):
        for opt in enum_meta.get("options", []):
            if isinstance(opt, dict) and "value" in opt:
                enum_choices.append(str(opt["value"]))
            elif isinstance(opt, str):
                enum_choices.append(opt)

    return AttributeDefinitionSnapshot(
        key=attr.key,
        label=getattr(attr, "label_fa", "") or getattr(attr, "label_en", "") or attr.key,
        data_type=attr.data_type,
        unit=unit,
        enum_choices=tuple(enum_choices),
        semantic_identity_id=attr.semantic_identity_id,
        commodity_id=getattr(attr.schema_version, "commodity_id", None) if hasattr(attr, "schema_version") else None,
        schema_version_id=attr.schema_version_id if hasattr(attr, "schema_version_id") else None,
    )


def to_rule_snapshot(rule: Any) -> SpecificationRuleSnapshot:
    """Helper to convert SpecificationMatchingRule or dict to SpecificationRuleSnapshot."""
    if isinstance(rule, SpecificationRuleSnapshot):
        return rule
    if isinstance(rule, dict):
        sem_id = rule["semantic_identity_id"]
        if not isinstance(sem_id, UUID):
            sem_id = UUID(str(sem_id))
        tol = rule.get("tolerance")
        if tol is not None and not isinstance(tol, Decimal):
            tol = Decimal(str(tol))
        rw = rule.get("relative_weight", Decimal("1.0000"))
        if rw is not None and not isinstance(rw, Decimal):
            rw = Decimal(str(rw))
        return SpecificationRuleSnapshot(
            semantic_identity_id=sem_id,
            operator=rule["operator"],
            tolerance=tol,
            hard_constraint=bool(rule.get("hard_constraint", False)),
            relative_weight=rw,
            missing_data_policy=rule.get("missing_data_policy", SignalOutcome.UNKNOWN),
        )
    # Model instance
    return SpecificationRuleSnapshot(
        semantic_identity_id=rule.semantic_identity_id,
        operator=rule.operator,
        tolerance=rule.tolerance,
        hard_constraint=rule.hard_constraint,
        relative_weight=rule.relative_weight,
        missing_data_policy=rule.missing_data_policy,
    )


def check_attribute_snapshot_compatibility(
    attr_a: AttributeDefinitionSnapshot,
    attr_b: AttributeDefinitionSnapshot,
) -> Tuple[bool, str]:
    """
    Verify basic technical compatibility between two attribute snapshots
    sharing the same semantic identity.
    """
    if attr_a.data_type != attr_b.data_type:
        return False, "data_type_mismatch"
    unit_a = (attr_a.unit or "").strip().upper()
    unit_b = (attr_b.unit or "").strip().upper()
    if (unit_a or unit_b) and unit_a != unit_b:
        return False, "unit_not_comparable"
    if attr_a.data_type == "enum" and attr_a.enum_choices and attr_b.enum_choices:
        if not (set(attr_a.enum_choices) & set(attr_b.enum_choices)):
            return False, "enum_domain_incompatible"
    return True, ""


def _parse_decimal(val: Any) -> Optional[Decimal]:
    """Safely parse a value to Decimal without boolean or float precision issues."""
    if val is None or isinstance(val, bool):
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return None


def evaluate_specifications(
    rfq_specifications: Dict[str, Any],
    candidate_specifications: Dict[str, Any],
    rfq_attributes: Sequence[AttributeDefinitionSnapshot | Any],
    candidate_attributes: Sequence[AttributeDefinitionSnapshot | Any],
    rules_by_semantic_identity: Dict[UUID, SpecificationRuleSnapshot | Any],
) -> List[SpecificationEvaluationResult]:
    """
    Pure side-effect-free evaluator for commodity dynamic specifications.

    INVARIANTS:
    - Zero commodity-code or attribute-key branching.
    - Operates strictly on explicit Semantic Identity and exact stored schema definitions.
    - Evaluates using exact Decimal arithmetic (float-free).
    - Returns deterministic, fully-explained SpecificationEvaluationResult records.
    """
    rfq_snapshots = [to_attribute_snapshot(a) for a in rfq_attributes]
    cand_snapshots = [to_attribute_snapshot(a) for a in candidate_attributes]
    rules = {
        (k if isinstance(k, UUID) else UUID(str(k))): to_rule_snapshot(v)
        for k, v in rules_by_semantic_identity.items()
    }

    cand_by_semantic_id: Dict[UUID, List[AttributeDefinitionSnapshot]] = {}
    for ca in cand_snapshots:
        if ca.semantic_identity_id:
            cand_by_semantic_id.setdefault(ca.semantic_identity_id, []).append(ca)

    sorted_rfq = sorted(rfq_snapshots, key=lambda a: a.key)
    results: List[SpecificationEvaluationResult] = []

    for rfq_attr in sorted_rfq:
        sem_id = rfq_attr.semantic_identity_id
        rule = rules.get(sem_id) if sem_id else None
        rel_weight = rule.relative_weight if rule else Decimal("1.0000")

        # 1. Did RFQ specify a target value?
        if rfq_attr.key not in rfq_specifications or rfq_specifications[rfq_attr.key] is None:
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=SignalOutcome.NOT_APPLICABLE,
                    is_hard=False,
                    raw_score=None,
                    relative_weight=rel_weight,
                    expected={"key": rfq_attr.key, "target_value": None},
                    actual=None,
                    reason_code=SpecificationReasonCode.RFQ_VALUE_NOT_SPECIFIED.value,
                )
            )
            continue

        target_val = rfq_specifications[rfq_attr.key]

        # 2. Check semantic identity and rule configuration
        if not sem_id:
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=None,
                    outcome=SignalOutcome.UNKNOWN,
                    is_hard=False,
                    raw_score=None,
                    relative_weight=Decimal("1.0000"),
                    expected={"key": rfq_attr.key, "target_value": target_val},
                    actual=None,
                    reason_code=SpecificationReasonCode.SEMANTIC_IDENTITY_NOT_FOUND.value,
                )
            )
            continue

        if rule is None:
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=SignalOutcome.UNKNOWN,
                    is_hard=False,
                    raw_score=None,
                    relative_weight=Decimal("1.0000"),
                    expected={"key": rfq_attr.key, "target_value": target_val},
                    actual=None,
                    reason_code=SpecificationReasonCode.MATCHING_RULE_NOT_CONFIGURED.value,
                )
            )
            continue

        # 3. Rule operator IGNORE
        if rule.operator == SpecificationRuleOperator.IGNORE:
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=SignalOutcome.NOT_APPLICABLE,
                    is_hard=False,
                    raw_score=None,
                    relative_weight=rule.relative_weight,
                    expected={
                        "key": rfq_attr.key,
                        "target_value": target_val,
                        "operator": rule.operator,
                    },
                    actual=None,
                    reason_code=SpecificationReasonCode.RULE_OPERATOR_IGNORE.value,
                )
            )
            continue

        # 4. Find candidate attribute with same semantic identity
        cand_attr_list = cand_by_semantic_id.get(sem_id, [])
        if not cand_attr_list:
            outcome = rule.missing_data_policy
            raw_score = Decimal("0.0000") if outcome == SignalOutcome.FAIL else None
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=outcome,
                    is_hard=rule.hard_constraint,
                    raw_score=raw_score,
                    relative_weight=rule.relative_weight,
                    expected={
                        "key": rfq_attr.key,
                        "target_value": target_val,
                        "operator": rule.operator,
                    },
                    actual=None,
                    reason_code=SpecificationReasonCode.CANDIDATE_SPEC_MISSING.value,
                )
            )
            continue

        cand_attr = cand_attr_list[0]

        # 5. Semantic compatibility guard
        is_compat, compat_err = check_attribute_snapshot_compatibility(rfq_attr, cand_attr)
        if not is_compat:
            err_reason = (
                SpecificationReasonCode.UNIT_NOT_COMPARABLE.value
                if compat_err == "unit_not_comparable"
                else SpecificationReasonCode.SEMANTIC_COMPATIBILITY_FAILED.value
            )
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=SignalOutcome.UNKNOWN,
                    is_hard=rule.hard_constraint,
                    raw_score=None,
                    relative_weight=rule.relative_weight,
                    expected={
                        "key": rfq_attr.key,
                        "target_value": target_val,
                        "data_type": rfq_attr.data_type,
                        "unit": rfq_attr.unit,
                    },
                    actual={
                        "key": cand_attr.key,
                        "candidate_value": candidate_specifications.get(cand_attr.key),
                        "data_type": cand_attr.data_type,
                        "unit": cand_attr.unit,
                    },
                    reason_code=err_reason,
                )
            )
            continue

        # 6. Candidate specification value in JSONB
        if (
            cand_attr.key not in candidate_specifications
            or candidate_specifications[cand_attr.key] is None
        ):
            outcome = rule.missing_data_policy
            raw_score = Decimal("0.0000") if outcome == SignalOutcome.FAIL else None
            results.append(
                SpecificationEvaluationResult(
                    dimension="specifications",
                    code=rfq_attr.key,
                    semantic_identity_id=sem_id,
                    outcome=outcome,
                    is_hard=rule.hard_constraint,
                    raw_score=raw_score,
                    relative_weight=rule.relative_weight,
                    expected={
                        "key": rfq_attr.key,
                        "target_value": target_val,
                        "operator": rule.operator,
                    },
                    actual={"key": cand_attr.key, "candidate_value": None},
                    reason_code=SpecificationReasonCode.CANDIDATE_SPEC_MISSING.value,
                )
            )
            continue

        cand_val = candidate_specifications[cand_attr.key]

        expected_dict: Dict[str, Any] = {
            "key": rfq_attr.key,
            "target_value": target_val,
            "operator": rule.operator,
        }
        if rule.tolerance is not None:
            expected_dict["tolerance"] = str(rule.tolerance)
        actual_dict: Dict[str, Any] = {
            "key": cand_attr.key,
            "candidate_value": cand_val,
        }

        # 7. Evaluate operator
        if rule.operator == SpecificationRuleOperator.EXACT:
            if rfq_attr.data_type in ("number", "integer"):
                dec_t = _parse_decimal(target_val)
                dec_c = _parse_decimal(cand_val)
                if dec_t is not None and dec_c is not None:
                    is_match = dec_t == dec_c
                else:
                    is_match = str(target_val).strip() == str(cand_val).strip()
            elif rfq_attr.data_type == "boolean":
                is_match = bool(target_val) == bool(cand_val)
            else:
                is_match = str(target_val).strip() == str(cand_val).strip()

            if is_match:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.PASS,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("1.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.SPEC_EXACT_MATCH.value,
                    )
                )
            else:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.FAIL,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("0.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.SPEC_VALUE_MISMATCH.value,
                    )
                )

        elif rule.operator == SpecificationRuleOperator.MIN_REQUIRED:
            dec_t = _parse_decimal(target_val)
            dec_c = _parse_decimal(cand_val)
            if dec_t is None or dec_c is None:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.UNKNOWN,
                        is_hard=rule.hard_constraint,
                        raw_score=None,
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.INVALID_NUMERIC_VALUE.value,
                    )
                )
            elif dec_c >= dec_t:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.PASS,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("1.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.MIN_REQUIREMENT_MET.value,
                    )
                )
            else:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.FAIL,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("0.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.MIN_REQUIREMENT_NOT_MET.value,
                    )
                )

        elif rule.operator == SpecificationRuleOperator.MAX_ALLOWED:
            dec_t = _parse_decimal(target_val)
            dec_c = _parse_decimal(cand_val)
            if dec_t is None or dec_c is None:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.UNKNOWN,
                        is_hard=rule.hard_constraint,
                        raw_score=None,
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.INVALID_NUMERIC_VALUE.value,
                    )
                )
            elif dec_c <= dec_t:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.PASS,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("1.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.MAX_ALLOWANCE_MET.value,
                    )
                )
            else:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.FAIL,
                        is_hard=rule.hard_constraint,
                        raw_score=Decimal("0.0000"),
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.MAX_ALLOWANCE_EXCEEDED.value,
                    )
                )

        elif rule.operator == SpecificationRuleOperator.TARGET_WITH_TOLERANCE:
            dec_t = _parse_decimal(target_val)
            dec_c = _parse_decimal(cand_val)
            if dec_t is None or dec_c is None:
                results.append(
                    SpecificationEvaluationResult(
                        dimension="specifications",
                        code=rfq_attr.key,
                        semantic_identity_id=sem_id,
                        outcome=SignalOutcome.UNKNOWN,
                        is_hard=rule.hard_constraint,
                        raw_score=None,
                        relative_weight=rule.relative_weight,
                        expected=expected_dict,
                        actual=actual_dict,
                        reason_code=SpecificationReasonCode.INVALID_NUMERIC_VALUE.value,
                    )
                )
            else:
                diff = abs(dec_c - dec_t)
                tol = rule.tolerance if rule.tolerance is not None else Decimal("0.0000")
                if diff <= tol:
                    results.append(
                        SpecificationEvaluationResult(
                            dimension="specifications",
                            code=rfq_attr.key,
                            semantic_identity_id=sem_id,
                            outcome=SignalOutcome.PASS,
                            is_hard=rule.hard_constraint,
                            raw_score=Decimal("1.0000"),
                            relative_weight=rule.relative_weight,
                            expected=expected_dict,
                            actual=actual_dict,
                            reason_code=SpecificationReasonCode.WITHIN_TOLERANCE.value,
                        )
                    )
                else:
                    results.append(
                        SpecificationEvaluationResult(
                            dimension="specifications",
                            code=rfq_attr.key,
                            semantic_identity_id=sem_id,
                            outcome=SignalOutcome.FAIL,
                            is_hard=rule.hard_constraint,
                            raw_score=Decimal("0.0000"),
                            relative_weight=rule.relative_weight,
                            expected=expected_dict,
                            actual=actual_dict,
                            reason_code=SpecificationReasonCode.OUTSIDE_TOLERANCE.value,
                        )
                    )

    return results


def materialize_attribute_snapshots(
    schema_version: Any,
) -> List[AttributeDefinitionSnapshot]:
    """
    Safely load AttributeDefinitionSnapshot list from a CommoditySchemaVersion.
    Always uses the specific schema_version passed; never queries active_schema_version.
    """
    if schema_version is None:
        return []
    from commodities.models import CommodityAttributeDefinition, CommoditySchemaVersion

    if isinstance(schema_version, (str, UUID)):
        schema_version = CommoditySchemaVersion.objects.get(pk=schema_version)
    if hasattr(schema_version, "attributes"):
        attrs = schema_version.attributes.all().order_by("sort_order", "key")
    else:
        attrs = CommodityAttributeDefinition.objects.filter(
            schema_version=schema_version
        ).order_by("sort_order", "key")
    return [to_attribute_snapshot(a) for a in attrs]


def materialize_specification_rules(
    policy_version: Any,
) -> Dict[UUID, SpecificationRuleSnapshot]:
    """
    Safely load SpecificationRuleSnapshot mapping from a MatchingPolicyVersion.
    """
    if policy_version is None:
        return {}
    from matching.models import MatchingPolicyVersion, SpecificationMatchingRule

    if isinstance(policy_version, (str, UUID)):
        policy_version = MatchingPolicyVersion.objects.get(pk=policy_version)
    if hasattr(policy_version, "specification_rules"):
        rules = policy_version.specification_rules.all()
    else:
        rules = SpecificationMatchingRule.objects.filter(policy_version=policy_version)
    return {r.semantic_identity_id: to_rule_snapshot(r) for r in rules}


def evaluate_candidate_specifications(
    rfq_specifications: Dict[str, Any],
    rfq_schema_version: Any,
    candidate_specifications: Dict[str, Any],
    candidate_schema_version: Optional[Any],
    policy_version: Any,
) -> List[SpecificationEvaluationResult]:
    """
    Convenience bridge: evaluates specifications between an RFQ and a candidate using their
    exact stored schema versions and the matching policy version.

    GUARANTEE: Uses only the exact schema versions provided. NEVER queries or substitutes
    active_schema_version.
    """
    rfq_attributes = materialize_attribute_snapshots(rfq_schema_version)
    cand_attributes = (
        materialize_attribute_snapshots(candidate_schema_version)
        if candidate_schema_version is not None
        else []
    )
    rules = materialize_specification_rules(policy_version)
    return evaluate_specifications(
        rfq_specifications=rfq_specifications,
        candidate_specifications=candidate_specifications,
        rfq_attributes=rfq_attributes,
        candidate_attributes=cand_attributes,
        rules_by_semantic_identity=rules,
    )

