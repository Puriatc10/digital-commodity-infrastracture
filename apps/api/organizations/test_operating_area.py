from django.db import IntegrityError, transaction
from django.test import TestCase

from geography.models import AreaType, GeographicArea
from organizations.models import Organization, OrganizationOperatingArea


class OrganizationOperatingAreaTests(TestCase):
    """
    Tests for OrganizationOperatingArea explicit coverage and database constraints.
    """

    def setUp(self):
        self.org = Organization.objects.create(
            name="Pars Bitumen Co",
            registration_identifier="REG-12345",
            country="IR",
        )
        self.iran = GeographicArea.objects.create(
            code="IR",
            area_type=AreaType.COUNTRY,
            country_code="IR",
            name_en="Iran",
            name_fa="ایران",
        )
        self.tehran_prov = GeographicArea.objects.create(
            code="IR-07",
            area_type=AreaType.ADMINISTRATIVE_AREA,
            country_code="IR",
            name_en="Tehran",
            name_fa="تهران",
            parent=self.iran,
        )

    def test_explicit_operating_area_creation(self):
        """Operating area must be explicitly created and link organization to geographic area."""
        op_area = OrganizationOperatingArea.objects.create(
            organization=self.org,
            area=self.tehran_prov,
        )
        self.assertEqual(self.org.operating_areas.count(), 1)
        self.assertEqual(self.org.operating_areas.first().area, self.tehran_prov)
        self.assertIn(op_area, self.tehran_prov.operating_organizations.all())

    def test_operating_area_uniqueness_constraint(self):
        """Duplicate [organization, area] records are rejected by PostgreSQL unique constraint."""
        OrganizationOperatingArea.objects.create(
            organization=self.org,
            area=self.tehran_prov,
        )
        dup = OrganizationOperatingArea(
            organization=self.org,
            area=self.tehran_prov,
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                dup.save()

    def test_operating_area_not_inferred_from_hq(self):
        """Organization with registered country but no OrganizationOperatingArea has empty operating_areas."""
        new_org = Organization.objects.create(
            name="Shiraz Petrochemical",
            registration_identifier="REG-67890",
            country="IR",
        )
        # Even though registered country is 'IR', operating_areas relation is empty
        self.assertEqual(new_org.operating_areas.count(), 0)
