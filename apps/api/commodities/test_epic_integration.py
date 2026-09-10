from django.test import TestCase
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from django.urls import reverse
from commodities.models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from commodities.services import validate_commodity_payload, clone_schema_to_draft, publish_schema

class EpicIntegrationTests(TestCase):
    def test_version_evolution_and_historical_stability(self):
        # 1. Seed initial data (v1 Published)
        call_command('seed_bitumen')

        commodity = CommodityDefinition.objects.get(code="bitumen")
        v1_schema = commodity.active_schema_version
        self.assertEqual(v1_schema.version, 1)
        self.assertEqual(v1_schema.status, CommoditySchemaVersion.SchemaStatus.PUBLISHED)

        # Keep track of v1 attributes count
        v1_attr_count = v1_schema.attributes.count()

        valid_v1_payload = {
            "penetration_grade": "60/70",
            "penetration": 65,
            "softening_point": 49,
            "ductility": 100,
            "flash_point": 250,
            "solubility": 99.5,
            "loss_on_heating": 0.1
        }

        # Validates correctly against v1
        validate_commodity_payload(v1_schema, valid_v1_payload)

        # 2. Clone v2 Draft
        v2_schema = clone_schema_to_draft(v1_schema)
        self.assertEqual(v2_schema.version, 2)
        self.assertEqual(v2_schema.status, CommoditySchemaVersion.SchemaStatus.DRAFT)
        self.assertEqual(commodity.active_schema_version.version, 1) # active is still v1

        # 3. Change v2 (Add a new required attribute)
        CommodityAttributeDefinition.objects.create(
            schema_version=v2_schema,
            key="new_v2_field",
            label_en="New Field",
            label_fa="فیلد جدید",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True
        )

        # 4. Publish/Activate v2
        publish_schema(v2_schema, activate=True)

        commodity.refresh_from_db()
        self.assertEqual(commodity.active_schema_version.version, 2)

        # 5. Prove v1 unchanged
        v1_schema.refresh_from_db()
        self.assertEqual(v1_schema.attributes.count(), v1_attr_count)
        self.assertFalse(v1_schema.attributes.filter(key="new_v2_field").exists())

        # 6. Prove v1 still validates according to v1
        validate_commodity_payload(v1_schema, valid_v1_payload)

        # 7. Prove v2 rejects the v1 payload because of the new required field
        with self.assertRaises(ValidationError) as ctx:
            validate_commodity_payload(v2_schema, valid_v1_payload)
        errors = ctx.exception.params["errors"]
        self.assertTrue(any(e["field"] == "new_v2_field" and e["code"] == "required" for e in errors))

        # 8. Prove v2 accepts the updated payload
        valid_v2_payload = valid_v1_payload.copy()
        valid_v2_payload["new_v2_field"] = "some value"
        validate_commodity_payload(v2_schema, valid_v2_payload)

class EpicIntegrationAPI_Flow_Tests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")
        self.client.force_login(self.user)

    def test_bitumen_epic_integration_pipeline(self):
        # 1. Seed
        call_command('seed_bitumen')
        CommodityDefinition.objects.get(code="bitumen")

        # 2. Retrieve through API
        url = reverse("commodity-active-schema", kwargs={"code": "bitumen"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(len(response.data["attributes"]), 7)

        # 3. Retrieve Historical Schema directly
        historical_url = reverse("commodity-schema", kwargs={"id": response.data["id"]})
        hist_response = self.client.get(historical_url)
        self.assertEqual(hist_response.status_code, 200)
        self.assertEqual(hist_response.data["id"], response.data["id"])

    def test_base_oil_epic_integration_pipeline(self):
        # 1. Seed Base Oil
        call_command('seed_base_oil')
        CommodityDefinition.objects.get(code="base_oil")

        # 2. Retrieve through API
        url = reverse("commodity-active-schema", kwargs={"code": "base_oil"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(len(response.data["attributes"]), 6)

        # 3. Retrieve Historical Schema directly
        historical_url = reverse("commodity-schema", kwargs={"id": response.data["id"]})
        hist_response = self.client.get(historical_url)
        self.assertEqual(hist_response.status_code, 200)
        self.assertEqual(hist_response.data["id"], response.data["id"])
