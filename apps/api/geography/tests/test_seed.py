from django.test import TestCase

from geography.models import AreaType, GeographicArea
from geography.seed import SeedConflictError, seed_iran_geography


class GeographySeedTests(TestCase):
    """
    Tests for deterministic Iran geography seed and strict conflict policy.
    """

    def test_seed_creates_expected_nodes_and_hierarchy(self):
        """Seed should create Iran (1), 31 provinces, and pilot cities (6) = 38 total."""
        created_map = seed_iran_geography()
        self.assertEqual(len(created_map), 38)

        # Check Iran
        iran = created_map["IR"]
        self.assertEqual(iran.area_type, AreaType.COUNTRY)
        self.assertIsNone(iran.parent)

        # Check Tehran Province
        tehran_prov = created_map["IR-07"]
        self.assertEqual(tehran_prov.parent, iran)
        self.assertEqual(tehran_prov.area_type, AreaType.ADMINISTRATIVE_AREA)

        # Check Shahriar under Tehran
        shahriar = created_map["IR-07-SHH"]
        self.assertEqual(shahriar.parent, tehran_prov)
        self.assertEqual(shahriar.area_type, AreaType.CITY)

        # Check Bandar Abbas under Hormozgan
        hormozgan = created_map["IR-23"]
        bandar_abbas = created_map["IR-23-BND"]
        self.assertEqual(bandar_abbas.parent, hormozgan)
        self.assertEqual(bandar_abbas.area_type, AreaType.CITY)

    def test_seed_rerun_creates_no_duplicates(self):
        """9. Seed rerun creates no duplicates (idempotent)."""
        seed_iran_geography()
        count_before = GeographicArea.objects.count()

        # Re-run
        seed_iran_geography()
        count_after = GeographicArea.objects.count()
        self.assertEqual(count_before, count_after)

    def test_safe_label_change_does_not_change_identity(self):
        """10. Label change does not change identity and updates existing record safely."""
        created_map = seed_iran_geography()
        tehran = created_map["IR-07-THR"]
        orig_id = tehran.id

        # Update label directly in DB
        tehran.name_en = "Tehran Metropolis"
        tehran.save()

        # Re-running seed resets or preserves according to seed spec, but keeps same UUID
        reseeded_map = seed_iran_geography()
        reseeded_tehran = reseeded_map["IR-07-THR"]
        self.assertEqual(reseeded_tehran.id, orig_id)
        self.assertEqual(reseeded_tehran.code, "IR-07-THR")

    def test_seed_conflict_policy_rejects_silent_reparenting(self):
        """Conflicting structural identity raises SeedConflictError and refuses to silently reparent."""
        seed_iran_geography()

        # Deliberately modify Tehran Province parent to point to another country to simulate conflict
        uae = GeographicArea.objects.create(
            code="AE",
            area_type=AreaType.COUNTRY,
            country_code="AE",
            name_en="United Arab Emirates",
            name_fa="امارات",
            parent=None,
        )
        # Update raw without clean to simulate legacy corrupted/conflicting record
        GeographicArea.objects.filter(code="IR-07").update(parent_id=uae.id, country_code="AE")

        with self.assertRaises(SeedConflictError) as ctx:
            seed_iran_geography()

        self.assertIn("Conflicting structural identity", str(ctx.exception))
        self.assertIn("Silent reparenting or structural redefinition is prohibited", str(ctx.exception))
