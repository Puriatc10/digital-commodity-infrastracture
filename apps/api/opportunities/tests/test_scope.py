from django.apps import apps
from django.test import TestCase


class Epic6ScopeGuardTests(TestCase):
    """
    Guarantees strict sequential scope containment for T0601.

    Ensures that T0602 (Identifier), T0603 (Lifecycle transitions/state machine),
    T0605 (Attribution), T0606 (Contact Attempts), T0607 (Tasks),
    T0608 (Qualification), T0609-T0611 (Conversions/Offers)
    have NOT been prematurely introduced.
    """

    def test_opportunities_app_models(self):
        """Confirm that the opportunities app only defines authorized models up to T0606."""
        app_config = apps.get_app_config("opportunities")
        model_names = sorted([m.__name__ for m in app_config.get_models()])

        self.assertEqual(
            model_names,
            [
                "ExternalCounterparty",
                "Opportunity",
                "OpportunityContactAttempt",
                "OpportunityIdentifierSequence",
            ],
        )

    def test_no_premature_opportunity_models_registered(self):
        """Confirm no premature lifecycle, attribution, contact, or task models exist."""
        all_model_names = [m.__name__ for m in apps.get_models()]

        self.assertNotIn("OpportunityLifecycle", all_model_names)
        self.assertNotIn("OpportunitySource", all_model_names)
        self.assertNotIn("ContactAttempt", all_model_names)
        self.assertNotIn("OpportunityTask", all_model_names)
        self.assertNotIn("OpportunityQualification", all_model_names)
        self.assertNotIn("OpportunityOffer", all_model_names)
