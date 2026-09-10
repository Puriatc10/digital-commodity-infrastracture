from django.test import TestCase
from django.core.management import call_command
from django.core.exceptions import ValidationError
from io import StringIO
from commodities.models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from commodities.services import validate_commodity_payload

class BitumenSeedAndValidationTests(TestCase):
    def test_seed_bitumen_creates_commodity_and_schema(self):
        out = StringIO()
        call_command('seed_bitumen', stdout=out)

        # Check commodity created
        commodity = CommodityDefinition.objects.get(code="bitumen")
        self.assertEqual(commodity.name_en, "Bitumen")
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
        self.assertEqual(schema.attributes.count(), 7)
        attr_keys = list(schema.attributes.values_list('key', flat=True))
        self.assertCountEqual(attr_keys, [
            "penetration_grade",
            "penetration",
            "softening_point",
            "ductility",
            "flash_point",
            "solubility",
            "loss_on_heating"
        ])

    def test_seed_bitumen_is_idempotent_and_historically_safe(self):
        out = StringIO()
        call_command('seed_bitumen', stdout=out)

        # Modify the published schema (which shouldn't normally happen but we simulate it to test idempotency)

        # We can't easily mutate published schema attributes due to our models protections,
        # but running it again should just print a warning and skip

        out2 = StringIO()
        call_command('seed_bitumen', stdout=out2)

        self.assertIn("Published Bitumen v1 already exists. Skipping mutation", out2.getvalue())

        # Still exactly 1 schema, 7 attributes
        self.assertEqual(CommoditySchemaVersion.objects.count(), 1)
        self.assertEqual(CommodityAttributeDefinition.objects.count(), 7)

    def test_bitumen_payload_validation_valid(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        valid_payload = {
            "penetration_grade": "60/70",
            "penetration": 65,
            "softening_point": 49,
            "ductility": 100,
            "flash_point": 250,
            "solubility": 99.5,
            "loss_on_heating": 0.1
        }

        # Should not raise
        validate_commodity_payload(schema, valid_payload)

    def test_bitumen_payload_validation_optional(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        valid_minimal_payload = {
            "penetration_grade": "40/50"
        }

        # Should not raise
        validate_commodity_payload(schema, valid_minimal_payload)

    def test_bitumen_payload_validation_missing_required(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        invalid_payload = {
            "penetration": 65
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "penetration_grade" and e["code"] == "required" for e in errors))

    def test_bitumen_payload_validation_invalid_enum(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        invalid_payload = {
            "penetration_grade": "invalid_grade"
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "penetration_grade" and e["code"] == "invalid_enum" for e in errors))

    def test_bitumen_payload_validation_type(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        invalid_payload = {
            "penetration_grade": "60/70",
            "penetration": "65"  # String instead of number
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "penetration" and e["code"] == "invalid_type" for e in errors))

    def test_bitumen_payload_validation_bounds(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        invalid_payload = {
            "penetration_grade": "60/70",
            "penetration": -5  # Below minimum 0
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "penetration" and e["code"] == "min_value" for e in errors))

    def test_bitumen_payload_validation_unknown_field(self):
        call_command('seed_bitumen')
        schema = CommodityDefinition.objects.get(code="bitumen").active_schema_version

        invalid_payload = {
            "penetration_grade": "60/70",
            "unknown_property": 123
        }

        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(schema, invalid_payload)

        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "unknown_property" and e["code"] == "unknown_field" for e in errors))
