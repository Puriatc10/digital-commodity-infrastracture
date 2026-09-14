from django.apps import apps
from django.test import TestCase


class Epic6ScopeGuardTests(TestCase):
    """
    Guarantees strict sequential scope containment for T0604.

    Ensures that T0601 (Opportunity Domain Model), T0602 (Identifier),
    T0603 (Lifecycle), T0605 (Attribution), T0606 (Contact Attempts),
    T0607 (Tasks), T0608 (Qualification), T0609-T0611 (Conversions/Offers)
    have NOT been prematurely introduced.
    """

    def test_opportunities_app_only_contains_external_counterparty(self):
        """Confirm that the opportunities app only defines ExternalCounterparty."""
        app_config = apps.get_app_config("opportunities")
        model_names = [m.__name__ for m in app_config.get_models()]

        self.assertEqual(model_names, ["ExternalCounterparty"])

    def test_no_premature_opportunity_models_registered(self):
        """Confirm no Opportunity or ContactAttempt model exists across all apps."""
        all_model_names = [m.__name__ for m in apps.get_models()]

        self.assertNotIn("Opportunity", all_model_names)
        self.assertNotIn("OpportunityLifecycle", all_model_names)
        self.assertNotIn("OpportunitySource", all_model_names)
        self.assertNotIn("ContactAttempt", all_model_names)
        self.assertNotIn("OpportunityTask", all_model_names)
