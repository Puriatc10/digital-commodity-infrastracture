from django.test import TestCase

from opportunities.api.serializers import ExternalCounterpartySerializer


class ExternalCounterpartyValidationTests(TestCase):
    """
    Validates field constraints and input sanitation for ExternalCounterparty.
    """

    def test_missing_company_name_fails(self):
        """Company name is required."""
        serializer = ExternalCounterpartySerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("company_name", serializer.errors)

    def test_blank_company_name_fails(self):
        """Company name cannot be blank or empty string."""
        serializer = ExternalCounterpartySerializer(data={"company_name": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("company_name", serializer.errors)

    def test_whitespace_only_company_name_fails(self):
        """Company name cannot be purely whitespace."""
        serializer = ExternalCounterpartySerializer(data={"company_name": "   "})
        self.assertFalse(serializer.is_valid())
        self.assertIn("company_name", serializer.errors)

    def test_company_name_is_trimmed(self):
        """Leading and trailing whitespace on company name is trimmed."""
        serializer = ExternalCounterpartySerializer(
            data={"company_name": "  Trimmed Petroleum Corp  "}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["company_name"], "Trimmed Petroleum Corp")

    def test_invalid_email_format_fails(self):
        """Malformed email strings fail validation."""
        serializer = ExternalCounterpartySerializer(
            data={
                "company_name": "Acme Energy",
                "email": "not-a-valid-email",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_valid_email_passes(self):
        """Properly formatted email succeeds."""
        serializer = ExternalCounterpartySerializer(
            data={
                "company_name": "Acme Energy",
                "email": "desk@acme-energy.com",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_blank_email_passes(self):
        """Email is optional and blank email is valid."""
        serializer = ExternalCounterpartySerializer(
            data={
                "company_name": "Acme Energy",
                "email": "",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_max_length_exceeded_company_name(self):
        """Company name exceeding 255 chars fails."""
        serializer = ExternalCounterpartySerializer(
            data={"company_name": "A" * 256}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("company_name", serializer.errors)

    def test_max_length_exceeded_contact_name(self):
        """Contact name exceeding 255 chars fails."""
        serializer = ExternalCounterpartySerializer(
            data={
                "company_name": "Valid Corp",
                "contact_name": "B" * 256,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_name", serializer.errors)

    def test_max_length_exceeded_phone(self):
        """Phone exceeding 50 chars fails."""
        serializer = ExternalCounterpartySerializer(
            data={
                "company_name": "Valid Corp",
                "phone": "+1" * 30,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("phone", serializer.errors)
