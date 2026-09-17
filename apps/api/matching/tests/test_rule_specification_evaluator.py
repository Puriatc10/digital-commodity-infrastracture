from decimal import Decimal
from unittest import TestCase
import uuid

from django.test import TestCase as DjangoTestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import clone_schema_to_draft, publish_schema
from matching.enums import PolicyLifecycleStatus, SignalOutcome
from matching.models import (
    MatchingPolicy,
    MatchingPolicyVersion,
    SpecificationMatchingRule,
    SpecificationRuleOperator,
)
from matching.rules.specification import (
    AttributeDefinitionSnapshot,
    SpecificationReasonCode,
    SpecificationRuleSnapshot,
    evaluate_candidate_specifications,
    evaluate_specifications,
)


class PureSpecificationEvaluatorTests(TestCase):
    """
    Unit tests for pure side-effect-free specification evaluator.
    Decoupled from database models using pure snapshots.
    """

    def setUp(self):
        self.sem_pen = uuid.uuid4()
        self.sem_soft = uuid.uuid4()
        self.sem_duct = uuid.uuid4()
        self.sem_ignored = uuid.uuid4()

        self.rfq_attrs = [
            AttributeDefinitionSnapshot(
                key="penetration_grade",
                label="Penetration Grade",
                data_type="enum",
                unit="0.1mm",
                enum_choices=("60/70", "85/100"),
                semantic_identity_id=self.sem_pen,
            ),
            AttributeDefinitionSnapshot(
                key="softening_point",
                label="Softening Point",
                data_type="number",
                unit="°C",
                semantic_identity_id=self.sem_soft,
            ),
            AttributeDefinitionSnapshot(
                key="ductility",
                label="Ductility",
                data_type="number",
                unit="cm",
                semantic_identity_id=self.sem_duct,
            ),
            AttributeDefinitionSnapshot(
                key="internal_note_attr",
                label="Ignored Attribute",
                data_type="string",
                semantic_identity_id=self.sem_ignored,
            ),
        ]

        # By default, candidate attributes match 1:1 in semantic identity
        self.cand_attrs = list(self.rfq_attrs)

        self.rules = {
            self.sem_pen: SpecificationRuleSnapshot(
                semantic_identity_id=self.sem_pen,
                operator=SpecificationRuleOperator.EXACT,
                hard_constraint=True,
                relative_weight=Decimal("2.0000"),
            ),
            self.sem_soft: SpecificationRuleSnapshot(
                semantic_identity_id=self.sem_soft,
                operator=SpecificationRuleOperator.TARGET_WITH_TOLERANCE,
                tolerance=Decimal("2.0000"),
                hard_constraint=False,
                relative_weight=Decimal("1.5000"),
            ),
            self.sem_duct: SpecificationRuleSnapshot(
                semantic_identity_id=self.sem_duct,
                operator=SpecificationRuleOperator.MIN_REQUIRED,
                hard_constraint=True,
                relative_weight=Decimal("1.0000"),
            ),
            self.sem_ignored: SpecificationRuleSnapshot(
                semantic_identity_id=self.sem_ignored,
                operator=SpecificationRuleOperator.IGNORE,
                hard_constraint=False,
                relative_weight=Decimal("0.0000"),
            ),
        }

    def test_exact_operator_pass_and_fail(self):
        """EXACT operator matches identical values and rejects differing values."""
        # Match
        res = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"penetration_grade": "60/70"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res[0].raw_score, Decimal("1.0000"))
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.SPEC_EXACT_MATCH.value)
        self.assertTrue(res[0].is_eligible)

        # Mismatch
        res_fail = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"penetration_grade": "85/100"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(len(res_fail), 1)
        self.assertEqual(res_fail[0].outcome, SignalOutcome.FAIL)
        self.assertEqual(res_fail[0].raw_score, Decimal("0.0000"))
        self.assertEqual(res_fail[0].reason_code, SpecificationReasonCode.SPEC_VALUE_MISMATCH.value)
        self.assertFalse(res_fail[0].is_eligible)  # hard constraint -> ineligible

    def test_exact_operator_numeric_equivalence(self):
        """EXACT operator handles integer and decimal numerical equivalence float-free."""
        sem_num = uuid.uuid4()
        rfq_num = [
            AttributeDefinitionSnapshot(
                key="density",
                data_type="number",
                semantic_identity_id=sem_num,
            )
        ]
        rule = {
            sem_num: SpecificationRuleSnapshot(
                semantic_identity_id=sem_num,
                operator=SpecificationRuleOperator.EXACT,
            )
        }
        res = evaluate_specifications(
            rfq_specifications={"density": 1000},
            candidate_specifications={"density": "1000.0"},
            rfq_attributes=rfq_num,
            candidate_attributes=rfq_num,
            rules_by_semantic_identity=rule,
        )
        self.assertEqual(res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res[0].raw_score, Decimal("1.0000"))

    def test_min_required_operator(self):
        """MIN_REQUIRED passes if candidate >= target, fails if candidate < target."""
        rule_dict = {self.sem_duct: self.rules[self.sem_duct]}
        attr_duct = [self.rfq_attrs[2]]

        # Greater: candidate 105 >= target 100 -> PASS
        res = evaluate_specifications(
            rfq_specifications={"ductility": 100},
            candidate_specifications={"ductility": 105},
            rfq_attributes=attr_duct,
            candidate_attributes=attr_duct,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.MIN_REQUIREMENT_MET.value)

        # Equal: candidate 100 == target 100 -> PASS
        res_eq = evaluate_specifications(
            rfq_specifications={"ductility": 100},
            candidate_specifications={"ductility": 100},
            rfq_attributes=attr_duct,
            candidate_attributes=attr_duct,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res_eq[0].outcome, SignalOutcome.PASS)

        # Lesser: candidate 95 < target 100 -> FAIL
        res_less = evaluate_specifications(
            rfq_specifications={"ductility": 100},
            candidate_specifications={"ductility": 95},
            rfq_attributes=attr_duct,
            candidate_attributes=attr_duct,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res_less[0].outcome, SignalOutcome.FAIL)
        self.assertEqual(res_less[0].raw_score, Decimal("0.0000"))
        self.assertEqual(res_less[0].reason_code, SpecificationReasonCode.MIN_REQUIREMENT_NOT_MET.value)

    def test_max_allowed_operator(self):
        """MAX_ALLOWED passes if candidate <= target, fails if candidate > target."""
        sem_loss = uuid.uuid4()
        attr_loss = [
            AttributeDefinitionSnapshot(
                key="loss_on_heating",
                data_type="number",
                unit="%",
                semantic_identity_id=sem_loss,
            )
        ]
        rule_loss = {
            sem_loss: SpecificationRuleSnapshot(
                semantic_identity_id=sem_loss,
                operator=SpecificationRuleOperator.MAX_ALLOWED,
                hard_constraint=True,
            )
        }

        # Lesser: candidate 0.2 <= target 0.5 -> PASS
        res = evaluate_specifications(
            rfq_specifications={"loss_on_heating": "0.5"},
            candidate_specifications={"loss_on_heating": "0.2"},
            rfq_attributes=attr_loss,
            candidate_attributes=attr_loss,
            rules_by_semantic_identity=rule_loss,
        )
        self.assertEqual(res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.MAX_ALLOWANCE_MET.value)

        # Greater: candidate 0.8 > target 0.5 -> FAIL
        res_fail = evaluate_specifications(
            rfq_specifications={"loss_on_heating": "0.5"},
            candidate_specifications={"loss_on_heating": "0.8"},
            rfq_attributes=attr_loss,
            candidate_attributes=attr_loss,
            rules_by_semantic_identity=rule_loss,
        )
        self.assertEqual(res_fail[0].outcome, SignalOutcome.FAIL)
        self.assertEqual(res_fail[0].reason_code, SpecificationReasonCode.MAX_ALLOWANCE_EXCEEDED.value)

    def test_target_with_tolerance_boundary_and_score(self):
        """TARGET_WITH_TOLERANCE evaluates distance from target within tolerance bound."""
        rule_dict = {self.sem_soft: self.rules[self.sem_soft]}
        attr_soft = [self.rfq_attrs[1]]

        # Target = 50, Tolerance = 2.0 (Range: [48.0, 52.0])

        # Exact boundary lower (48.0): d = 2.0 <= 2.0 -> PASS
        res_bound_low = evaluate_specifications(
            rfq_specifications={"softening_point": 50},
            candidate_specifications={"softening_point": 48},
            rfq_attributes=attr_soft,
            candidate_attributes=attr_soft,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res_bound_low[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res_bound_low[0].raw_score, Decimal("1.0000"))
        self.assertEqual(res_bound_low[0].reason_code, SpecificationReasonCode.WITHIN_TOLERANCE.value)

        # Exact boundary upper (52.0): d = 2.0 <= 2.0 -> PASS
        res_bound_high = evaluate_specifications(
            rfq_specifications={"softening_point": 50},
            candidate_specifications={"softening_point": 52},
            rfq_attributes=attr_soft,
            candidate_attributes=attr_soft,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res_bound_high[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res_bound_high[0].raw_score, Decimal("1.0000"))

        # Outside boundary (52.1): d = 2.1 > 2.0 -> FAIL
        res_out = evaluate_specifications(
            rfq_specifications={"softening_point": 50},
            candidate_specifications={"softening_point": 52.1},
            rfq_attributes=attr_soft,
            candidate_attributes=attr_soft,
            rules_by_semantic_identity=rule_dict,
        )
        self.assertEqual(res_out[0].outcome, SignalOutcome.FAIL)
        self.assertEqual(res_out[0].raw_score, Decimal("0.0000"))
        self.assertEqual(res_out[0].reason_code, SpecificationReasonCode.OUTSIDE_TOLERANCE.value)

    def test_ignore_operator_produces_not_applicable(self):
        """IGNORE operator produces NOT_APPLICABLE and is excluded from score."""
        res = evaluate_specifications(
            rfq_specifications={"internal_note_attr": "Custom special demand"},
            candidate_specifications={"internal_note_attr": "Different note"},
            rfq_attributes=[self.rfq_attrs[3]],
            candidate_attributes=[self.cand_attrs[3]],
            rules_by_semantic_identity={self.sem_ignored: self.rules[self.sem_ignored]},
        )
        self.assertEqual(res[0].outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res[0].raw_score)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.RULE_OPERATOR_IGNORE.value)

    def test_rfq_unspecified_value_produces_not_applicable(self):
        """Attributes where RFQ did not specify a value produce NOT_APPLICABLE."""
        res = evaluate_specifications(
            rfq_specifications={},  # penetration_grade omitted
            candidate_specifications={"penetration_grade": "60/70"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(res[0].outcome, SignalOutcome.NOT_APPLICABLE)
        self.assertIsNone(res[0].raw_score)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.RFQ_VALUE_NOT_SPECIFIED.value)

    def test_missing_matching_rule_produces_unknown(self):
        """Target attribute without a configured matching rule produces UNKNOWN without guessing."""
        res = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"penetration_grade": "60/70"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={},  # No rules configured
        )
        self.assertEqual(res[0].outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res[0].raw_score)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.MATCHING_RULE_NOT_CONFIGURED.value)

    def test_candidate_missing_value_in_jsonb(self):
        """Candidate specification missing from JSONB yields rule's missing_data_policy."""
        # Default policy is UNKNOWN
        res = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={},  # missing
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(res[0].outcome, SignalOutcome.UNKNOWN)
        self.assertIsNone(res[0].raw_score)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.CANDIDATE_SPEC_MISSING.value)

        # Policy configured as FAIL
        fail_rule = SpecificationRuleSnapshot(
            semantic_identity_id=self.sem_pen,
            operator=SpecificationRuleOperator.EXACT,
            missing_data_policy=SignalOutcome.FAIL,
            hard_constraint=True,
        )
        res_fail = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=[self.cand_attrs[0]],
            rules_by_semantic_identity={self.sem_pen: fail_rule},
        )
        self.assertEqual(res_fail[0].outcome, SignalOutcome.FAIL)
        self.assertEqual(res_fail[0].raw_score, Decimal("0.0000"))
        self.assertFalse(res_fail[0].is_eligible)

    def test_candidate_schema_lacks_semantic_identity(self):
        """Candidate schema having no attribute with matching semantic identity yields UNKNOWN."""
        cand_different_schema = [
            AttributeDefinitionSnapshot(
                key="other_attribute",
                semantic_identity_id=uuid.uuid4(),  # totally different identity
            )
        ]
        res = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"other_attribute": "foo"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=cand_different_schema,
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(res[0].outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.CANDIDATE_SPEC_MISSING.value)

    def test_semantic_compatibility_guard_fails(self):
        """Technical incompatibility between matching semantic identities produces UNKNOWN."""
        # Unit mismatch
        cand_incompat_unit = [
            AttributeDefinitionSnapshot(
                key="penetration_grade",
                data_type="enum",
                unit="mm",  # RFQ is 0.1mm
                enum_choices=("60/70",),
                semantic_identity_id=self.sem_pen,
            )
        ]
        res_unit = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"penetration_grade": "60/70"},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=cand_incompat_unit,
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(res_unit[0].outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(res_unit[0].reason_code, SpecificationReasonCode.UNIT_NOT_COMPARABLE.value)

        # Data type mismatch
        cand_incompat_type = [
            AttributeDefinitionSnapshot(
                key="penetration_grade",
                data_type="number",  # RFQ is enum
                semantic_identity_id=self.sem_pen,
            )
        ]
        res_type = evaluate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            candidate_specifications={"penetration_grade": 65},
            rfq_attributes=[self.rfq_attrs[0]],
            candidate_attributes=cand_incompat_type,
            rules_by_semantic_identity={self.sem_pen: self.rules[self.sem_pen]},
        )
        self.assertEqual(res_type[0].outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(res_type[0].reason_code, SpecificationReasonCode.SEMANTIC_COMPATIBILITY_FAILED.value)

    def test_same_key_attack_prevented(self):
        """ATTACK: RFQ and Candidate have identical key 'viscosity' but different semantic identities."""
        sem_rfq = uuid.uuid4()
        sem_cand = uuid.uuid4()

        rfq_spec = [
            AttributeDefinitionSnapshot(
                key="viscosity",
                data_type="number",
                semantic_identity_id=sem_rfq,
            )
        ]
        cand_spec = [
            AttributeDefinitionSnapshot(
                key="viscosity",
                data_type="number",
                semantic_identity_id=sem_cand,  # Different semantic identity!
            )
        ]
        rules = {
            sem_rfq: SpecificationRuleSnapshot(
                semantic_identity_id=sem_rfq,
                operator=SpecificationRuleOperator.EXACT,
            )
        }

        # Both have same value 100 for key 'viscosity'
        res = evaluate_specifications(
            rfq_specifications={"viscosity": 100},
            candidate_specifications={"viscosity": 100},
            rfq_attributes=rfq_spec,
            candidate_attributes=cand_spec,
            rules_by_semantic_identity=rules,
        )
        # MUST NOT match just because keys are identical!
        self.assertEqual(res[0].outcome, SignalOutcome.UNKNOWN)
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.CANDIDATE_SPEC_MISSING.value)

    def test_different_key_semantic_equivalence(self):
        """ATTACK/FEATURE: RFQ and Candidate have different keys but identical semantic identity."""
        sem_shared = uuid.uuid4()

        rfq_spec = [
            AttributeDefinitionSnapshot(
                key="pen_grade",  # RFQ key
                data_type="enum",
                enum_choices=("60/70",),
                semantic_identity_id=sem_shared,
            )
        ]
        cand_spec = [
            AttributeDefinitionSnapshot(
                key="penetration_25c",  # Candidate key
                data_type="enum",
                enum_choices=("60/70",),
                semantic_identity_id=sem_shared,  # Shared semantic identity!
            )
        ]
        rules = {
            sem_shared: SpecificationRuleSnapshot(
                semantic_identity_id=sem_shared,
                operator=SpecificationRuleOperator.EXACT,
            )
        }

        res = evaluate_specifications(
            rfq_specifications={"pen_grade": "60/70"},
            candidate_specifications={"penetration_25c": "60/70"},
            rfq_attributes=rfq_spec,
            candidate_attributes=cand_spec,
            rules_by_semantic_identity=rules,
        )
        # Matches based on shared semantic identity across renamed keys!
        self.assertEqual(res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(res[0].raw_score, Decimal("1.0000"))
        self.assertEqual(res[0].reason_code, SpecificationReasonCode.SPEC_EXACT_MATCH.value)

    def test_multi_commodity_generic_execution(self):
        """Multi-commodity proof: Bitumen and Base Oil evaluated through the same pure engine."""
        # Commodity 1: Bitumen
        sem_bit_grade = uuid.uuid4()
        bit_rfq_attrs = [
            AttributeDefinitionSnapshot(
                key="grade",
                data_type="enum",
                enum_choices=("60/70",),
                semantic_identity_id=sem_bit_grade,
            )
        ]
        bit_rules = {
            sem_bit_grade: SpecificationRuleSnapshot(
                semantic_identity_id=sem_bit_grade,
                operator=SpecificationRuleOperator.EXACT,
            )
        }
        bit_res = evaluate_specifications(
            rfq_specifications={"grade": "60/70"},
            candidate_specifications={"grade": "60/70"},
            rfq_attributes=bit_rfq_attrs,
            candidate_attributes=bit_rfq_attrs,
            rules_by_semantic_identity=bit_rules,
        )
        self.assertEqual(bit_res[0].outcome, SignalOutcome.PASS)

        # Commodity 2: Base Oil
        sem_bo_kv = uuid.uuid4()
        sem_bo_flash = uuid.uuid4()
        bo_rfq_attrs = [
            AttributeDefinitionSnapshot(
                key="kv_100",
                data_type="number",
                unit="cSt",
                semantic_identity_id=sem_bo_kv,
            ),
            AttributeDefinitionSnapshot(
                key="flash_point",
                data_type="number",
                unit="°C",
                semantic_identity_id=sem_bo_flash,
            ),
        ]
        bo_rules = {
            sem_bo_kv: SpecificationRuleSnapshot(
                semantic_identity_id=sem_bo_kv,
                operator=SpecificationRuleOperator.TARGET_WITH_TOLERANCE,
                tolerance=Decimal("0.5000"),
            ),
            sem_bo_flash: SpecificationRuleSnapshot(
                semantic_identity_id=sem_bo_flash,
                operator=SpecificationRuleOperator.MIN_REQUIRED,
            ),
        }
        bo_res = evaluate_specifications(
            rfq_specifications={"kv_100": "5.2", "flash_point": 210},
            candidate_specifications={"kv_100": "5.4", "flash_point": 220},
            rfq_attributes=bo_rfq_attrs,
            candidate_attributes=bo_rfq_attrs,
            rules_by_semantic_identity=bo_rules,
        )
        self.assertEqual(len(bo_res), 2)
        # kv_100 diff = 0.2 <= 0.5 -> PASS
        self.assertEqual(bo_res[0].code, "flash_point")  # sorted by key
        self.assertEqual(bo_res[0].outcome, SignalOutcome.PASS)
        self.assertEqual(bo_res[1].code, "kv_100")
        self.assertEqual(bo_res[1].outcome, SignalOutcome.PASS)


class ActiveSchemaAttackDbTests(DjangoTestCase):
    """
    Database-backed integration test proving the Active Schema Attack fails.

    Guarantees:
    - Matching always uses the exact schema version stored on the RFQ and Candidate records.
    - Altering the commodity's active_schema_version does NOT affect historical matching results.
    """

    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_active_schema_test",
            name_fa="قیر آزمایشی اسکیما",
            name_en="Test Bitumen Active Schema",
        )

        # Version 1: original schema
        self.schema_v1 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
        )
        self.attr_v1 = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_v1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.ENUM,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={"options": [{"value": "60/70"}]},
        )
        publish_schema(self.schema_v1, activate=True)
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version, self.schema_v1)

        # Policy with rule for penetration_grade
        self.policy = MatchingPolicy.objects.create(name="Policy Active Schema")
        self.policy_version = MatchingPolicyVersion.objects.create(
            policy=self.policy,
            version=1,
            status=PolicyLifecycleStatus.DRAFT,
        )
        SpecificationMatchingRule.objects.create(
            policy_version=self.policy_version,
            semantic_identity=self.attr_v1.semantic_identity,
            operator=SpecificationRuleOperator.EXACT,
            hard_constraint=True,
        )
        self.policy_version.status = PolicyLifecycleStatus.PUBLISHED
        self.policy_version.save(update_fields=["status"])

    def test_active_schema_mutation_does_not_affect_matching(self):
        """Active schema transition to v2/v3 does not reinterpret historical v1 records."""
        # Initial evaluation under v1 stored schema
        results_before = evaluate_candidate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            rfq_schema_version=self.schema_v1,
            candidate_specifications={"penetration_grade": "60/70"},
            candidate_schema_version=self.schema_v1,
            policy_version=self.policy_version,
        )
        self.assertEqual(results_before[0].outcome, SignalOutcome.PASS)

        # Now clone schema to v2, add a new required attribute, publish v2 so active schema becomes v2
        schema_v2 = clone_schema_to_draft(self.schema_v1)
        CommodityAttributeDefinition.objects.create(
            schema_version=schema_v2,
            key="new_breaking_spec",
            label_fa="مشخصه جدید",
            label_en="New Spec",
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
        )
        publish_schema(schema_v2, activate=True)
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version, schema_v2)

        # Evaluate historical records again: MUST still produce identical results based on v1, NOT v2!
        results_after = evaluate_candidate_specifications(
            rfq_specifications={"penetration_grade": "60/70"},
            rfq_schema_version=self.schema_v1,
            candidate_specifications={"penetration_grade": "60/70"},
            candidate_schema_version=self.schema_v1,
            policy_version=self.policy_version,
        )
        self.assertEqual(len(results_after), 1)
        self.assertEqual(results_after[0].outcome, SignalOutcome.PASS)
        self.assertEqual(results_after[0].code, "penetration_grade")
        self.assertNotIn("new_breaking_spec", [r.code for r in results_after])

