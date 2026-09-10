from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from .services import publish_schema, retire_schema, clone_schema_to_draft
from .services import generate_json_schema, validate_commodity_payload


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

    def test_active_schema_must_be_published(self):
        commodity = CommodityDefinition.objects.create(code="test1", name_en="Test1", name_fa="Test1")
        draft_schema = CommoditySchemaVersion.objects.create(commodity=commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        commodity.active_schema_version = draft_schema
        with self.assertRaises(ValidationError):
            commodity.save()

    def test_active_schema_must_belong_to_same_commodity(self):
        comm1 = CommodityDefinition.objects.create(code="c1", name_en="C1", name_fa="C1")
        comm2 = CommodityDefinition.objects.create(code="c2", name_en="C2", name_fa="C2")
        schema = CommoditySchemaVersion.objects.create(commodity=comm2, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        comm1.active_schema_version = schema
        with self.assertRaises(ValidationError):
            comm1.save()

    def test_valid_active_schema(self):
        commodity = CommodityDefinition.objects.create(code="valid", name_en="Valid", name_fa="Valid")
        pub_schema = CommoditySchemaVersion.objects.create(commodity=commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(pub_schema)
        commodity.active_schema_version = pub_schema
        commodity.save()
        self.assertEqual(commodity.active_schema_version, pub_schema)


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

    def test_cannot_mutate_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        schema.version = 2
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_revert_published_to_draft(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        schema.status = CommoditySchemaVersion.SchemaStatus.DRAFT
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_mutate_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        # Retire the schema properly using explicit domain service
        retire_schema(schema)

        schema.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
        with self.assertRaises(ValidationError):
            schema.save()

    def test_cannot_delete_published_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        with self.assertRaises(ValidationError):
            schema.delete()

    def test_cannot_delete_retired_schema(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        retire_schema(schema)
        with self.assertRaises(ValidationError):
            schema.delete()

    def test_publish_service(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema, activate=True)
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version, schema)

    def test_retire_service(self):
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(schema)
        retire_schema(schema)
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.RETIRED)

    def test_clone_service(self):
        # Create as DRAFT first, as expected in real application lifecycle
        schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=1, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=schema, key="test", data_type=CommodityAttributeDefinition.DataType.STRING
        )

        # Publish the schema to verify we can clone from a published source
        publish_schema(schema)

        new_schema = clone_schema_to_draft(schema)

        self.assertEqual(new_schema.version, 2)
        self.assertEqual(new_schema.status, CommoditySchemaVersion.SchemaStatus.DRAFT)
        self.assertEqual(new_schema.commodity, self.commodity)
        self.assertEqual(new_schema.attributes.count(), 1)

        new_attr = new_schema.attributes.first()
        self.assertEqual(new_attr.key, attr.key)
        self.assertNotEqual(new_attr.id, attr.id)

        # Ensure the source remains unchanged
        schema.refresh_from_db()
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)
        self.assertEqual(schema.attributes.count(), 1)


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

    def test_can_mutate_attribute_of_draft_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=3, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(
            schema_version=draft_schema, key="k1", data_type="string"
        )
        attr.label_en = "Updated"
        attr.save() # Should not raise
        self.assertEqual(attr.label_en, "Updated")
        attr.delete() # Should not raise
        self.assertEqual(CommodityAttributeDefinition.objects.count(), 0)

    def test_cannot_mutate_attribute_of_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=4, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(schema_version=draft_schema, key="k2", data_type="string")
        publish_schema(draft_schema)

        attr.label_en = "Mutate"
        with self.assertRaises(ValidationError):
            attr.save()

    def test_cannot_add_attribute_to_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=5, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        publish_schema(draft_schema)
        with self.assertRaises(ValidationError):
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_schema, key="k3", data_type="string"
            )

    def test_cannot_delete_attribute_of_published_schema(self):
        draft_schema = CommoditySchemaVersion.objects.create(commodity=self.commodity, version=6, status=CommoditySchemaVersion.SchemaStatus.DRAFT)
        attr = CommodityAttributeDefinition.objects.create(schema_version=draft_schema, key="k4", data_type="string")
        publish_schema(draft_schema)

        with self.assertRaises(ValidationError):
            attr.delete()


class CommodityValidationTests(TestCase):
    def setUp(self):
        self.commodity = CommodityDefinition.objects.create(code="val_test", name_en="ValTest", name_fa="ValTest")
        self.schema = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )

        # Add varied attributes to cover types
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="str_field",
            data_type="string",
            is_required=True,
            validation_metadata={"minLength": 2, "maxLength": 10},
            sort_order=1
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="num_field",
            data_type="number",
            is_required=False,
            validation_metadata={"minimum": 0, "maximum": 100},
            sort_order=2
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="int_field",
            data_type="integer",
            is_required=True,
            sort_order=3
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="bool_field",
            data_type="boolean",
            is_required=False,
            sort_order=4
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema,
            key="enum_field",
            data_type="enum",
            is_required=True,
            enum_metadata={"options": [{"value": "A"}, {"value": "B"}]},
            sort_order=5
        )

    def test_schema_generation_deterministic(self):
        json_schema = generate_json_schema(self.schema)
        self.assertEqual(json_schema["type"], "object")
        self.assertFalse(json_schema["additionalProperties"])
        self.assertCountEqual(json_schema["required"], ["str_field", "int_field", "enum_field"])

        props = json_schema["properties"]
        self.assertEqual(props["str_field"]["type"], "string")
        self.assertEqual(props["str_field"]["minLength"], 2)
        self.assertEqual(props["str_field"]["maxLength"], 10)

        self.assertEqual(props["num_field"]["type"], "number")
        self.assertEqual(props["num_field"]["minimum"], 0)
        self.assertEqual(props["num_field"]["maximum"], 100)

        self.assertEqual(props["int_field"]["type"], "integer")
        self.assertEqual(props["bool_field"]["type"], "boolean")

        self.assertEqual(props["enum_field"]["type"], "string")
        self.assertEqual(props["enum_field"]["enum"], ["A", "B"])

        # Test Generation leaves definition unchanged
        # Since generating schema just reads, it naturally doesn't change it, but we can assert no save was needed
        # Just ensure the schema is still draft and unchanged
        schema_refresh = CommoditySchemaVersion.objects.get(pk=self.schema.pk)
        self.assertEqual(schema_refresh.status, CommoditySchemaVersion.SchemaStatus.DRAFT)

    def test_validation_valid_payload(self):
        payload = {
            "str_field": "hello",
            "num_field": 50.5,
            "int_field": 10,
            "bool_field": True,
            "enum_field": "A"
        }
        # Should not raise
        validate_commodity_payload(self.schema, payload)

        # num and bool are optional, missing them is fine
        payload_optional_missing = {
            "str_field": "hello",
            "int_field": 10,
            "enum_field": "B"
        }
        validate_commodity_payload(self.schema, payload_optional_missing)

    def test_validation_missing_required(self):
        payload = {
            "int_field": 10,
            "enum_field": "A"
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "str_field" and e["code"] == "required" for e in errors))

    def test_validation_unknown_field(self):
        payload = {
            "str_field": "hello",
            "int_field": 10,
            "enum_field": "A",
            "magic_field": 123
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "magic_field" and e["code"] == "unknown_field" for e in errors))

    def test_validation_invalid_type_and_bool_strictness(self):
        payload = {
            "str_field": 123, # Wrong type
            "int_field": 10.5, # Wrong type (number vs int)
            "enum_field": "A"
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "str_field" and e["code"] == "invalid_type" for e in errors))
        self.assertTrue(any(e["field"] == "int_field" and e["code"] == "invalid_type" for e in errors))

        # Test bool strictness (1 is not True)
        payload2 = {
            "str_field": "hi",
            "int_field": 10,
            "enum_field": "A",
            "bool_field": 1 # Should fail
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload2)
        errors2 = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "bool_field" and e["code"] == "invalid_type" for e in errors2))

    def test_validation_explicit_null(self):
        payload = {
            "str_field": "hello",
            "int_field": 10,
            "enum_field": "A",
            "num_field": None # explicit null
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "num_field" and e["code"] == "invalid_type" for e in errors))

    def test_validation_enum_bounds(self):
        payload = {
            "str_field": "hello",
            "int_field": 10,
            "enum_field": "C" # Invalid enum
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "enum_field" and e["code"] == "invalid_enum" for e in errors))

    def test_validation_numeric_and_string_constraints(self):
        payload = {
            "str_field": "h", # minLength is 2
            "num_field": 101, # max is 100
            "int_field": 10,
            "enum_field": "A"
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(self.schema, payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "str_field" and e["code"] == "min_length" for e in errors))
        self.assertTrue(any(e["field"] == "num_field" and e["code"] == "max_value" for e in errors))

    def test_schema_version_aware(self):
        # Create v2
        v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=v2,
            key="new_field",
            data_type="string",
            is_required=True
        )

        # Valid for v1, but missing required new_field for v2
        payload_v1 = {
            "str_field": "hello",
            "int_field": 10,
            "enum_field": "A"
        }
        # v1 passes
        validate_commodity_payload(self.schema, payload_v1)

        # v2 fails (new_field is required, plus unknown fields)
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(v2, payload_v1)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "new_field" and e["code"] == "required" for e in errors))
