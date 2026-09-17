from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from geography.seed import seed_iran_geography

User = get_user_model()


class GeographyApiTests(TestCase):
    """
    Tests for Geography Read API, filtering, and query count optimization.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="geography_user@example.com",
            password="testpassword123",
        )
        self.client.force_authenticate(user=self.user)
        self.areas_map = seed_iran_geography()

    def test_list_areas_query_count_single_query(self):
        """Verify GET /api/geography/areas/ runs in a single query with select_related('parent') avoiding N+1."""
        # Warmup or direct check
        with self.assertNumQueries(1):
            response = self.client.get("/api/geography/areas/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 38)
            # Verify parent is serialized
            tehran_city_data = next(a for a in data if a["code"] == "IR-07-THR")
            self.assertIsNotNone(tehran_city_data["parent"])
            self.assertEqual(tehran_city_data["parent"]["code"], "IR-07")

    def test_retrieve_area_by_id(self):
        """Verify GET /api/geography/areas/{id}/."""
        tehran = self.areas_map["IR-07-THR"]
        response = self.client.get(f"/api/geography/areas/{tehran.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "IR-07-THR")
        self.assertEqual(data["name_en"], "Tehran")
        self.assertEqual(data["parent"]["code"], "IR-07")

    def test_filter_by_type(self):
        """Verify type filter."""
        response = self.client.get("/api/geography/areas/?type=COUNTRY")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["code"], "IR")

        response = self.client.get("/api/geography/areas/?type=CITY")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 6)

    def test_filter_by_parent(self):
        """Verify parent filter by code, id, and null."""
        # Root country (parent is null)
        response = self.client.get("/api/geography/areas/?parent=null")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["code"], "IR")

        # Cities under Tehran Province
        tehran_prov = self.areas_map["IR-07"]
        response = self.client.get(f"/api/geography/areas/?parent={tehran_prov.code}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        codes = [a["code"] for a in data]
        self.assertIn("IR-07-THR", codes)
        self.assertIn("IR-07-SHH", codes)

    def test_filter_by_search(self):
        """Verify case-insensitive search by code or name."""
        response = self.client.get("/api/geography/areas/?search=shahriar")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["code"], "IR-07-SHH")

    def test_no_write_endpoints(self):
        """Verify no write endpoint exists."""
        post_res = self.client.post("/api/geography/areas/", {"code": "FAKE"})
        self.assertEqual(post_res.status_code, 405)

        del_res = self.client.delete(f"/api/geography/areas/{self.areas_map['IR'].id}/")
        self.assertEqual(del_res.status_code, 405)
