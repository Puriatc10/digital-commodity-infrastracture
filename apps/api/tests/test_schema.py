from django.test import SimpleTestCase
from drf_spectacular.validation import validate_schema


class SchemaTests(SimpleTestCase):
    def test_public_schema_is_valid_and_describes_health(self):
        response = self.client.get("/api/schema/", {"format": "json"})

        self.assertEqual(response.status_code, 200)
        schema = response.json()
        validate_schema(schema)
        self.assertIn("/api/health", schema["paths"])
        self.assertIn("200", schema["paths"]["/api/health"]["get"]["responses"])

    def test_public_docs_render_and_reference_schema(self):
        response = self.client.get("/api/docs/")

        self.assertContains(response, "SwaggerUIBundle")
        self.assertContains(response, "/api/schema/")
