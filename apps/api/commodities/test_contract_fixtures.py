"""API-produced examples consumed by the actual generic React components.

Regenerate deliberately with UPDATE_COMMODITY_FIXTURES=1 and this test command.
Normal CI only compares; it never updates fixtures.
"""
import json
import os
from pathlib import Path
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from identity.models import User
from .models import CommodityDefinition
from .services import clone_schema_to_draft, publish_schema, retire_schema, validate_commodity_payload


class CommodityContractFixtureTests(TestCase):
    def test_seed_api_examples_match_frontend_fixtures(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user(email="contract@example.test"))
        fixtures = {}
        for code, payload in (
            ("bitumen", {"penetration_grade": "60/70", "softening_point": 49}),
            ("base_oil", {"base_oil_group": "Group I", "viscosity_grade": "SN500", "viscosity_at_40c": 96.5}),
        ):
            call_command(f"seed_{code}", stdout=StringIO())
            schema = CommodityDefinition.objects.get(code=code).active_schema_version
            validate_commodity_payload(schema, payload)
            response = client.get(f"/api/commodities/{code}/schema/")
            self.assertEqual(response.status_code, 200)
            fixtures[code] = self.normalized(response.data, code)
            if code == "bitumen":
                v2 = clone_schema_to_draft(schema)
                attr = v2.attributes.get(key="penetration_grade")
                attr.label_fa = "درجه نفوذ جدید"
                attr.enum_metadata["options"][1]["label_fa"] = "عنوان جدید ۶۰/۷۰"
                attr.save()
                publish_schema(v2, activate=True)
                retire_schema(schema)
                for name, version in (("bitumen_historical", schema), ("bitumen_v2", v2)):
                    result = client.get(f"/api/commodity-schemas/{version.pk}/")
                    self.assertEqual(result.status_code, 200)
                    fixtures[name] = self.normalized(result.data, code)
                validate_commodity_payload(schema, payload)
        path = Path(__file__).resolve().parents[2] / "web/tests/fixtures/commodity-schemas.json"
        if os.environ.get("UPDATE_COMMODITY_FIXTURES") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), fixtures)

    @staticmethod
    def normalized(data, code):
        data = json.loads(json.dumps(data, default=str))
        data["id"] = f"{code}-v{data['version']}"
        data["commodity_id"] = code
        for attr in data["attributes"]:
            attr["id"] = f"{data['id']}-{attr['key']}"
        return data
