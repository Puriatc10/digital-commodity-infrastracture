import uuid
from django.test import TestCase

from identity.models import User
from opportunities.models import ExternalCounterparty
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)


class ExternalCounterpartyPersistenceTests(TestCase):
    """
    Validates persistence and platform identity separation invariants.

    Critical Invariant:
        ExternalCounterparty != User
        ExternalCounterparty != Organization
    """

    def test_valid_external_counterparty_persists(self):
        """A valid counterparty with all explicit fields persists successfully."""
        cp = ExternalCounterparty.objects.create(
            company_name="Gulf Bitumen Trading LLC",
            contact_name="Ahmad Rezaei",
            phone="+971501234567",
            email="ahmad@gulfbitumen.ae",
            geography="Jebel Ali, UAE",
            notes="Active bitumen trading desk in Jebel Ali port area.",
        )

        cp.refresh_from_db()
        self.assertIsInstance(cp.id, uuid.UUID)
        self.assertEqual(cp.company_name, "Gulf Bitumen Trading LLC")
        self.assertEqual(cp.contact_name, "Ahmad Rezaei")
        self.assertEqual(cp.phone, "+971501234567")
        self.assertEqual(cp.email, "ahmad@gulfbitumen.ae")
        self.assertEqual(cp.geography, "Jebel Ali, UAE")
        self.assertEqual(cp.notes, "Active bitumen trading desk in Jebel Ali port area.")
        self.assertIsNone(cp.created_by)
        self.assertIsNotNone(cp.created_at)
        self.assertIsNotNone(cp.updated_at)

    def test_counterparty_exists_without_user(self):
        """ExternalCounterparty can exist without any User record."""
        User.objects.all().delete()
        self.assertEqual(User.objects.count(), 0)

        cp = ExternalCounterparty.objects.create(
            company_name="Standalone Counterparty Inc.",
            contact_name="John Doe",
        )

        cp.refresh_from_db()
        self.assertIsNone(cp.created_by)
        self.assertEqual(User.objects.count(), 0)

    def test_counterparty_exists_without_organization_membership_capability(self):
        """ExternalCounterparty can exist with zero organizations in the database."""
        Organization.objects.all().delete()
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(OrganizationMembership.objects.count(), 0)
        self.assertEqual(OrganizationCapability.objects.count(), 0)

        cp = ExternalCounterparty.objects.create(
            company_name="Non-Platform Supplier Ltd",
            geography="Rotterdam, Netherlands",
        )

        cp.refresh_from_db()
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(OrganizationMembership.objects.count(), 0)
        self.assertEqual(OrganizationCapability.objects.count(), 0)

    def test_no_shadow_platform_identity_created_on_save(self):
        """Creating an ExternalCounterparty creates NO fake platform identity rows."""
        user_count_before = User.objects.count()
        org_count_before = Organization.objects.count()
        membership_count_before = OrganizationMembership.objects.count()
        capability_count_before = OrganizationCapability.objects.count()

        ExternalCounterparty.objects.create(
            company_name="Off-Platform Partner FZE",
            contact_name="Karim Al-Sayed",
            phone="+9714000000",
            email="karim@offplatform.com",
            geography="Fujairah, UAE",
        )

        self.assertEqual(User.objects.count(), user_count_before)
        self.assertEqual(Organization.objects.count(), org_count_before)
        self.assertEqual(OrganizationMembership.objects.count(), membership_count_before)
        self.assertEqual(OrganizationCapability.objects.count(), capability_count_before)

    def test_duplicate_company_names_allowed(self):
        """
        Company name is NOT globally unique without an explicit business identifier.
        Allows legitimate distinct real-world entities/branches with identical names.
        """
        cp1 = ExternalCounterparty.objects.create(
            company_name="Global Trading FZE",
            geography="Dubai, UAE",
        )
        cp2 = ExternalCounterparty.objects.create(
            company_name="Global Trading FZE",
            geography="Singapore",
        )

        self.assertNotEqual(cp1.id, cp2.id)
        self.assertEqual(cp1.company_name, cp2.company_name)
        self.assertEqual(ExternalCounterparty.objects.filter(company_name="Global Trading FZE").count(), 2)

    def test_string_representation(self):
        """String representation includes contact name when present, or company name only."""
        cp_with_contact = ExternalCounterparty(
            company_name="Acme Trading", contact_name="Alice Smith"
        )
        self.assertEqual(str(cp_with_contact), "Acme Trading (Alice Smith)")

        cp_without_contact = ExternalCounterparty(company_name="Acme Trading")
        self.assertEqual(str(cp_without_contact), "Acme Trading")
