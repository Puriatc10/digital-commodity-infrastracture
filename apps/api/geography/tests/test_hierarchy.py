from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from geography.models import AreaType, GeographicArea
from geography.services import are_same, contains_area, is_ancestor, is_descendant


class GeographicAreaHierarchyTests(TestCase):
    """
    Behavioral tests for the hierarchical geographic domain on PostgreSQL.
    """

    def setUp(self):
        # Establish canonical Iran hierarchy
        self.iran = GeographicArea.objects.create(
            code="IR",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
            parent=None,
        )
        self.tehran_prov = GeographicArea.objects.create(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Tehran",
            name_fa="تهران",
            parent=self.iran,
        )
        self.tehran_city = GeographicArea.objects.create(
            code="IR-07-THR",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Tehran",
            name_fa="تهران",
            parent=self.tehran_prov,
        )
        self.shahriar = GeographicArea.objects.create(
            code="IR-07-SHH",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Shahriar",
            name_fa="شهریار",
            parent=self.tehran_prov,
        )
        self.hormozgan_prov = GeographicArea.objects.create(
            code="IR-23",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Hormozgan",
            name_fa="هرمزگان",
            parent=self.iran,
        )
        self.bandar_abbas = GeographicArea.objects.create(
            code="IR-23-BND",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Bandar Abbas",
            name_fa="بندرعباس",
            parent=self.hormozgan_prov,
        )

    def test_tehran_city_hierarchy(self):
        """1. Tehran City hierarchy under Tehran Province / Iran."""
        self.assertEqual(self.tehran_city.parent, self.tehran_prov)
        self.assertEqual(self.tehran_prov.parent, self.iran)
        self.assertIsNone(self.iran.parent)
        self.assertTrue(is_ancestor(self.iran, self.tehran_city))
        self.assertTrue(is_ancestor(self.tehran_prov, self.tehran_city))
        self.assertTrue(contains_area(self.tehran_prov, self.tehran_city))
        self.assertTrue(contains_area(self.iran, self.tehran_city))

    def test_shahriar_within_tehran_province(self):
        """2. Shahriar within Tehran Province."""
        self.assertEqual(self.shahriar.parent, self.tehran_prov)
        self.assertTrue(is_descendant(self.shahriar, self.tehran_prov))
        self.assertTrue(contains_area(self.tehran_prov, self.shahriar))
        self.assertFalse(contains_area(self.hormozgan_prov, self.shahriar))

    def test_bandar_abbas_within_hormozgan_province(self):
        """3. Bandar Abbas within Hormozgan Province."""
        self.assertEqual(self.bandar_abbas.parent, self.hormozgan_prov)
        self.assertTrue(is_descendant(self.bandar_abbas, self.hormozgan_prov))
        self.assertTrue(contains_area(self.hormozgan_prov, self.bandar_abbas))
        self.assertFalse(contains_area(self.tehran_prov, self.bandar_abbas))

    def test_self_parent_rejected(self):
        """4. Self-parent rejected."""
        self.tehran_prov.parent = self.tehran_prov
        with self.assertRaises(ValidationError) as ctx:
            self.tehran_prov.clean()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_cycle_rejected(self):
        """5. Cycle rejected."""
        # Attempt to make Iran's parent Tehran City (cycle: Iran -> Tehran Province -> Tehran City -> Iran)
        self.iran.parent = self.tehran_city
        with self.assertRaises(ValidationError) as ctx:
            self.iran.clean()
        # Clean catches either Country cannot have parent or cycle
        self.assertIn("parent", ctx.exception.message_dict)
        self.iran.parent = None

        # Also test cycle within admin areas if one was reparented
        prov_b = GeographicArea.objects.create(
            code="TEST-PROV-B",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Test Prov B",
            name_fa="تست",
            parent=self.iran,
        )
        # Force parent link to simulate cycle before clean
        prov_b.parent = self.tehran_prov
        self.tehran_prov.parent = prov_b
        with self.assertRaises(ValidationError) as ctx:
            self.tehran_prov.clean()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_invalid_type_hierarchy_rejected(self):
        """6. Invalid type hierarchy rejected: no city directly under country, no country with parent."""
        # City directly under country
        direct_city = GeographicArea(
            code="IR-DIRECT-CITY",
            area_type=AreaType.CITY,
            country_code="IR",
            name_en="Direct City",
            name_fa="شهر مستقیم",
            parent=self.iran,
        )
        with self.assertRaises(ValidationError) as ctx:
            direct_city.clean()
        self.assertIn("parent", ctx.exception.message_dict)

        # Country with parent
        child_country = GeographicArea(
            code="CHILD-COUNTRY",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Child Country",
            name_fa="کشور فرزند",
            parent=self.iran,
        )
        with self.assertRaises(ValidationError) as ctx:
            child_country.clean()
        self.assertIn("parent", ctx.exception.message_dict)

        # Admin area under City
        admin_under_city = GeographicArea(
            code="ADMIN-UNDER-CITY",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Admin Under City",
            name_fa="استان زیر شهر",
            parent=self.tehran_city,
        )
        with self.assertRaises(ValidationError) as ctx:
            admin_under_city.clean()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_cross_country_chain_rejected(self):
        """7. Cross-country chain rejected: child country_code must match parent country_code."""
        GeographicArea.objects.create(
            code="AE",
            area_type=AreaType.COUNTRY,
            country_code="AE",
            name_en="United Arab Emirates",
            name_fa="امارات متحده عربی",
            parent=None,
        )
        # Province in UAE with Iran parent
        cross_prov = GeographicArea(
            code="AE-DU",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="AE",
            name_en="Dubai",
            name_fa="دبی",
            parent=self.iran,
        )
        with self.assertRaises(ValidationError) as ctx:
            cross_prov.clean()
        self.assertIn("country_code", ctx.exception.message_dict)

    def test_duplicate_canonical_code_rejected(self):
        """8. Duplicate canonical code rejected by PostgreSQL unique constraint."""
        dup = GeographicArea(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Duplicate Tehran",
            name_fa="تکراری",
            parent=self.iran,
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                dup.save()

    def test_same_and_containment_utilities(self):
        """Verify are_same and containment logic."""
        self.assertTrue(are_same(self.tehran_city, self.tehran_city))
        self.assertFalse(are_same(self.tehran_city, self.shahriar))
        self.assertTrue(contains_area(self.tehran_prov, self.tehran_prov))
        self.assertTrue(contains_area(self.tehran_prov, self.shahriar))
        self.assertFalse(contains_area(self.shahriar, self.tehran_prov))
