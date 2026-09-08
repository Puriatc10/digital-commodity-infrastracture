from django.test import SimpleTestCase


class HealthTests(SimpleTestCase):
    # SimpleTestCase rejects database queries: health must remain liveness-only.
    def test_health_is_public_and_returns_ok_json(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_remains_json_for_browser_accept_header(self):
        response = self.client.get("/api/health", HTTP_ACCEPT="text/html,*/*")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_rejects_write_methods(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/api/health")

                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Content-Type"], "application/json")
