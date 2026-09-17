from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition as Attribute,
    CommodityAttributeSemanticIdentity,
    CommodityDefinition as Commodity,
    CommoditySchemaVersion as Schema,
)
from commodities.services import (
    check_semantic_compatibility,
    clone_schema_to_draft,
    publish_schema,
    rotate_attribute_semantic_identity,
)


class SemanticIdentityLifecycleTests(TestCase):
    def setUp(self):
        self.commodity = Commodity.objects.create(
            code="test_bitumen",
            name_fa="قیر آزمایشی",
            name_en="Test Bitumen",
        )
        self.schema_v1 = Schema.objects.create(commodity=self.commodity, version=1)
        self.attr = Attribute.objects.create(
            schema_version=self.schema_v1,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=Attribute.DataType.ENUM,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={"options": [{"value": "60/70", "label_fa": "60/70", "label_en": "60/70"}]},
            validation_metadata={},
        )

    def test_attribute_creation_assigns_semantic_identity(self):
        """Newly created attribute definition automatically gets an explicit semantic identity."""
        self.assertIsNotNone(self.attr.semantic_identity)
        self.assertEqual(self.attr.semantic_identity.commodity, self.commodity)
        self.assertIn("penetration_grade", self.attr.semantic_identity.code)

    def test_clone_schema_preserves_semantic_identity(self):
        """Cloning a schema to draft preserves exact semantic identities for attributes."""
        publish_schema(self.schema_v1)
        schema_v2 = clone_schema_to_draft(self.schema_v1)

        attr_v2 = schema_v2.attributes.get(key="penetration_grade")
        self.assertEqual(attr_v2.semantic_identity_id, self.attr.semantic_identity_id)

    def test_editing_label_preserves_semantic_identity(self):
        """Updating presentation metadata like labels preserves the same semantic identity."""
        self.attr.label_fa = "درجه نفوذ اصلاح‌شده"
        self.attr.label_en = "Updated Penetration Grade"
        self.attr.save()

        self.attr.refresh_from_db()
        self.assertEqual(self.attr.label_fa, "درجه نفوذ اصلاح‌شده")
        self.assertEqual(self.attr.semantic_identity_id, self.attr.semantic_identity.id)

    def test_rotate_semantic_identity_in_draft(self):
        """Rotating semantic identity in a draft schema creates and links a new identity."""
        original_identity_id = self.attr.semantic_identity_id
        rotated = rotate_attribute_semantic_identity(self.attr)

        self.assertNotEqual(rotated.semantic_identity_id, original_identity_id)
        self.assertEqual(rotated.semantic_identity.commodity, self.commodity)

    def test_rotate_semantic_identity_rejected_on_published_schema(self):
        """Cannot rotate semantic identity of an attribute in a published schema."""
        publish_schema(self.schema_v1)
        with self.assertRaises(ValidationError):
            rotate_attribute_semantic_identity(self.attr)

    def test_semantic_identity_immutable_on_published_schema(self):
        """Directly modifying semantic_identity on an attribute of a published schema raises ValidationError."""
        publish_schema(self.schema_v1)

        new_sem = CommodityAttributeSemanticIdentity.objects.create(
            commodity=self.commodity,
            code="new_identity_code",
            name_fa="هویت جدید",
            name_en="New Identity",
        )
        self.attr.semantic_identity = new_sem
        with self.assertRaises(ValidationError):
            self.attr.save()

    def test_semantic_identity_unique_per_commodity(self):
        """Cannot create duplicate semantic identity codes for the same commodity."""
        code = self.attr.semantic_identity.code
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CommodityAttributeSemanticIdentity.objects.create(
                    commodity=self.commodity,
                    code=code,
                )

    def test_semantic_identity_distinct_across_commodities(self):
        """Different commodities can have the same code for semantic identity."""
        other_commodity = Commodity.objects.create(
            code="test_base_oil",
            name_fa="روغن پایه آزمایشی",
            name_en="Test Base Oil",
        )
        code = self.attr.semantic_identity.code
        other_sem = CommodityAttributeSemanticIdentity.objects.create(
            commodity=other_commodity,
            code=code,
        )
        self.assertEqual(other_sem.code, code)
        self.assertEqual(other_sem.commodity, other_commodity)

    def test_semantic_compatibility_checks(self):
        """Test technical compatibility guard between two attribute definitions."""
        attr_same = Attribute(
            data_type=Attribute.DataType.ENUM,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={"options": [{"value": "60/70"}]},
        )
        compat, _ = check_semantic_compatibility(self.attr, attr_same)
        self.assertTrue(compat)

        # 1. Data type mismatch
        attr_diff_type = Attribute(
            data_type=Attribute.DataType.NUMBER,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={},
        )
        compat, err = check_semantic_compatibility(self.attr, attr_diff_type)
        self.assertFalse(compat)
        self.assertEqual(err, "data_type_mismatch")

        # 2. Unit mismatch
        attr_diff_unit = Attribute(
            data_type=Attribute.DataType.ENUM,
            unit_metadata={"canonical_unit": "mm"},
            enum_metadata={"options": [{"value": "60/70"}]},
        )
        compat, err = check_semantic_compatibility(self.attr, attr_diff_unit)
        self.assertFalse(compat)
        self.assertEqual(err, "unit_not_comparable")

        # 3. Enum domain incompatible (disjoint)
        attr_disjoint_enum = Attribute(
            data_type=Attribute.DataType.ENUM,
            unit_metadata={"canonical_unit": "0.1mm"},
            enum_metadata={"options": [{"value": "85/100"}]},
        )
        compat, err = check_semantic_compatibility(self.attr, attr_disjoint_enum)
        self.assertFalse(compat)
        self.assertEqual(err, "enum_domain_incompatible")

