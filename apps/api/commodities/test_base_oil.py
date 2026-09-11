from django.test import TestCase
from django.core.management import call_command
from django.core.exceptions import ValidationError
from io import StringIO
from commodities.models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from commodities.services import validate_commodity_payload

class BaseOilSeedAndValidationTests(TestCase):
    def test_seed_base_oil_creates_commodity_and_schema(self):
        out = StringIO()
        call_command('seed_base_oil', stdout=out)

        # Check commodity created
        commodity = CommodityDefinition.objects.get(code="base_oil")
        self.assertEqual(commodity.name_en, "Base Oil")
        self.assertTrue(commodity.is_active)

        # Check exactly one v1 schema exists and is published
        schemas = CommoditySchemaVersion.objects.filter(commodity=commodity)
        self.assertEqual(schemas.count(), 1)
        schema = schemas.first()
        self.assertEqual(schema.version, 1)
        self.assertEqual(schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)

        # Check active schema is v1
        self.assertEqual(commodity.active_schema_version, schema)

        # Check attributes created correctly
        self.assertEqual(schema.attributes.count(), 6)
        attr_keys = list(schema.attributes.values_list('key', flat=True))
        self.assertCountEqual(attr_keys, [
            "base_oil_group",
            "viscosity_grade",
            "viscosity_at_40c",
            "viscosity_index",
            "flash_point",
            "pour_point"
        ])

    def test_seed_base_oil_is_idempotent(self):
        out = StringIO()
        call_command('seed_base_oil', stdout=out)

        out2 = StringIO()
        call_command('seed_base_oil', stdout=out2)

        self.assertIn("Published Base Oil v1 already exists. Skipping mutation", out2.getvalue())

        # Still exactly 1 schema, 6 attributes
        self.assertEqual(CommoditySchemaVersion.objects.filter(commodity__code="base_oil").count(), 1)
        schema = CommoditySchemaVersion.objects.get(commodity__code="base_oil")
        self.assertEqual(CommodityAttributeDefinition.objects.filter(schema_version=schema).count(), 6)

    def test_base_oil_payload_validation_valid(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        valid_payload = {
            "base_oil_group": "Group I",
            "viscosity_grade": "SN500",
            "viscosity_at_40c": 96.5,
            "viscosity_index": 95,
            "flash_point": 240,
            "pour_point": -9
        }

        # Should not raise
        validate_commodity_payload(schema, valid_payload)

    def test_base_oil_payload_validation_optional(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        valid_minimal_payload = {
            "base_oil_group": "Group II",
            "viscosity_grade": "SN150"
            # Optional fields absent
        }

        # Should not raise
        validate_commodity_payload(schema, valid_minimal_payload)

    def test_base_oil_payload_validation_missing_required(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "viscosity_grade": "SN500"
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "base_oil_group" and e["code"] == "required" for e in errors))

    def test_base_oil_payload_validation_invalid_enum(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "Group IV", # Not in options
            "viscosity_grade": "SN500"
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "base_oil_group" and e["code"] == "invalid_enum" for e in errors))

    def test_base_oil_payload_validation_localized_label_rejected(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "گروه ۱", # localized label instead of canonical "Group I"
            "viscosity_grade": "SN500"
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "base_oil_group" and e["code"] == "invalid_enum" for e in errors))

    def test_base_oil_payload_validation_wrong_type(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "Group I",
            "viscosity_grade": "SN500",
            "viscosity_at_40c": "96.5"  # String instead of number
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "viscosity_at_40c" and e["code"] == "invalid_type" for e in errors))

    def test_base_oil_payload_validation_bounds(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "Group I",
            "viscosity_grade": "SN500",
            "viscosity_index": 250  # Over maximum 200
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "viscosity_index" and e["code"] == "max_value" for e in errors))

    def test_base_oil_payload_validation_invalid_null(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "Group I",
            "viscosity_grade": "SN500",
            "viscosity_at_40c": None # Explicit nulls are rejected
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "viscosity_at_40c" and e["code"] == "invalid_type" for e in errors))

    def test_base_oil_payload_validation_unknown_field(self):
        call_command('seed_base_oil')
        schema = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        invalid_payload = {
            "base_oil_group": "Group I",
            "viscosity_grade": "SN500",
            "color": "yellow" # Unknown field
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "color" and e["code"] == "unknown_field" for e in errors))

    def test_base_oil_schema_generation(self):
        call_command('seed_base_oil')
        schema_version = CommodityDefinition.objects.get(code="base_oil").active_schema_version

        from commodities.services import generate_json_schema
        json_schema = generate_json_schema(schema_version)

        self.assertEqual(json_schema["$schema"], "http://json-schema.org/draft-07/schema#")
        self.assertEqual(json_schema["type"], "object")
        self.assertFalse(json_schema["additionalProperties"]) # closed world semantics
        self.assertCountEqual(json_schema["required"], ["base_oil_group", "viscosity_grade"])

        props = json_schema["properties"]
        self.assertIn("base_oil_group", props)
        self.assertEqual(props["base_oil_group"]["type"], "string")
        self.assertEqual(props["base_oil_group"]["enum"], ["Group I", "Group II", "Group III"])

        self.assertIn("viscosity_at_40c", props)
        self.assertEqual(props["viscosity_at_40c"]["type"], "number")
        self.assertEqual(props["viscosity_at_40c"]["minimum"], 0)
