from django.test import TestCase
from django.db import IntegrityError
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition


class CommodityDefinitionTests(TestCase):
    def test_commodity_creation(self):
        commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.assertEqual(commodity.code, "bitumen")
        self.assertTrue(commodity.is_active)
        self.assertIsNone(commodity.active_schema_version)

    def test_code_uniqueness(self):
        CommodityDefinition.objects.create(code="test", name_fa="test", name_en="test")
        with self.assertRaises(IntegrityError):
            CommodityDefinition.objects.create(code="test", name_fa="test2", name_en="test2")


class CommoditySchemaVersionTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.commodity2 = CommodityDefinition.objects.create(
            code="base_oil",
            name_fa="روغن پایه",
            name_en="Base Oil"
        )

    def test_schema_belongs_to_commodity(self):
        schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )
        self.assertEqual(schema.commodity.code, "bitumen")

    def test_multiple_versions(self):
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2)
        self.assertEqual(self.commodity.schema_versions.count(), 2)

    def test_duplicate_version_rejected(self):
        CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)

    def test_same_version_different_commodities(self):
        schema1 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        schema2 = CommoditySchemaVersion.objects.create(commodity=self.commodity2, version=1)
        self.assertEqual(schema1.version, schema2.version)

    def test_invalid_status_rejection(self):
        # We need to test DB check constraint
        # Django's TestCase wraps tests in transactions, so IntegrityError will be raised
        with self.assertRaises(IntegrityError):
            CommoditySchemaVersion.objects.create(
                commodity=self.commodity,
                version=1,
                status="invalid_status"
            )


class CommodityAttributeDefinitionTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen",
            name_fa="قیر",
            name_en="Bitumen"
        )
        self.schema1 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1)
        self.schema2 = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=2)

    def test_attribute_belongs_to_schema(self):
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            label_fa="نقطه نرمی",
            label_en="Softening Point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        self.assertEqual(attr.schema_version.version, 1)

    def test_duplicate_key_rejected(self):
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        with self.assertRaises(IntegrityError):
            CommodityAttributeDefinition.objects.create(
                schema_version=self.schema1,
                key="softening_point",
                data_type=CommodityAttributeDefinition.DataType.NUMBER
            )

    def test_same_key_across_versions_allowed(self):
        attr1 = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        attr2 = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema2,
            key="softening_point",
            data_type=CommodityAttributeDefinition.DataType.NUMBER
        )
        self.assertEqual(attr1.key, attr2.key)

    def test_invalid_data_type_rejected(self):
        with self.assertRaises(IntegrityError):
            CommodityAttributeDefinition.objects.create(
                schema_version=self.schema1,
                key="test",
                data_type="invalid_type"
            )

    def test_metadata_fields(self):
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=self.schema1,
            key="penetration_grade",
            label_fa="گرید نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.ENUM,
            is_required=True,
            unit_metadata={"allowed_units": []},
            enum_metadata={"options": [{"value": "60_70", "label_en": "60/70"}]},
            validation_metadata={},
            display_group="Main",
            sort_order=10
        )
        self.assertTrue(attr.is_required)
        self.assertEqual(attr.enum_metadata["options"][0]["value"], "60_70")
