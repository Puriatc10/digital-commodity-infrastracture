from django.test import TestCase
from django.contrib.auth import get_user_model
from organizations.models import Organization
from documents.models import VerificationDocument, DocumentType
from organizations.verification.models import VerificationStatus
from organizations.verification.services import VerificationService, VerificationDomainException

User = get_user_model()

class VerificationDomainTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(email="admin@test.com", password="password")
        self.org = Organization.objects.create(name="Test Org", country="IR")
        VerificationService.get_or_create_verification(self.org.id)
        self.doc_reg = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.COMPANY_REGISTRATION,
            object_key="key1", size_bytes=100
        )
        self.doc_tax = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.TAX_ID,
            object_key="key2", size_bytes=100
        )
        self.doc_auth = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.AUTHORIZED_REPRESENTATIVE,
            object_key="key3", size_bytes=100
        )
        self.doc_trade = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.TRADE_LICENSE,
            object_key="key4", size_bytes=100
        )
        self.doc_bank = VerificationDocument.objects.create(
            organization=self.org, type=DocumentType.BANK_DETAILS,
            object_key="key5", size_bytes=100
        )
        self.doc_reg.verification_status = "accepted"
        self.doc_reg.save()
        self.doc_tax.verification_status = "accepted"
        self.doc_tax.save()
        self.doc_auth.verification_status = "accepted"
        self.doc_auth.save()
        self.doc_trade.verification_status = "accepted"
        self.doc_trade.save()
        self.doc_bank.verification_status = "accepted"
        self.doc_bank.save()


    def test_initial_state(self):
        verification = VerificationService.get_or_create_verification(self.org.id)
        self.assertEqual(verification.status, VerificationStatus.UNVERIFIED)

    def test_valid_lifecycle_to_verified(self):
        # 1. Submit
        verification = VerificationService.submit(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.DOCUMENTS_SUBMITTED)
        self.assertEqual(verification.version, 2)

        # 2. Start Review
        verification = VerificationService.start_review(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.UNDER_REVIEW)
        self.assertEqual(verification.version, 3)

        self.doc_reg.verification_status = "accepted"
        self.doc_reg.save()
        self.doc_tax.verification_status = "accepted"
        self.doc_tax.save()
        self.doc_auth.verification_status = "accepted"
        self.doc_auth.save()
        # 3. Basic Verified
        verification = VerificationService.basic_approval(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.BASIC_VERIFIED)
        self.assertEqual(verification.version, 4)

        # 4. Under Review again (Upgrade)
        # Note: This is an unlisted specific transition, reopening from Basic Verified to Under Review
        verification = VerificationService.reopen(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.UNDER_REVIEW)

        self.doc_trade.verification_status = "accepted"
        self.doc_trade.save()
        self.doc_bank.verification_status = "accepted"
        self.doc_bank.save()
        # 5. Verified
        verification = VerificationService.full_approval(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.VERIFIED)

        # Ensure history matches
        decisions = verification.decisions.all().order_by('created_at')
        self.assertEqual(decisions.count(), 5)
        self.assertEqual(decisions[0].new_status, VerificationStatus.DOCUMENTS_SUBMITTED)
        self.assertEqual(decisions[1].new_status, VerificationStatus.UNDER_REVIEW)
        self.assertEqual(decisions[2].new_status, VerificationStatus.BASIC_VERIFIED)

    def test_rejection_requires_reason(self):
        VerificationService.submit(self.org.id, self.actor)
        VerificationService.start_review(self.org.id, self.actor)

        with self.assertRaisesMessage(VerificationDomainException, "requires a reason"):
            VerificationService.reject(self.org.id, self.actor, reason="")

        verification = VerificationService.reject(self.org.id, self.actor, reason="Missing tax ID")
        self.assertEqual(verification.status, VerificationStatus.UNVERIFIED)

    def test_suspension_requires_reason(self):
        VerificationService.submit(self.org.id, self.actor)
        VerificationService.start_review(self.org.id, self.actor)
        self.doc_reg.verification_status = "accepted"
        self.doc_reg.save()
        self.doc_tax.verification_status = "accepted"
        self.doc_tax.save()
        self.doc_auth.verification_status = "accepted"
        self.doc_auth.save()
        self.doc_trade.verification_status = "accepted"
        self.doc_trade.save()
        self.doc_bank.verification_status = "accepted"
        self.doc_bank.save()
        VerificationService.full_approval(self.org.id, self.actor)

        with self.assertRaisesMessage(VerificationDomainException, "requires a reason"):
            VerificationService.suspend(self.org.id, self.actor, reason="")

        verification = VerificationService.suspend(self.org.id, self.actor, reason="Suspicious activity")
        self.assertEqual(verification.status, VerificationStatus.SUSPENDED)

    def test_reset_evidence_replacement(self):
        VerificationService.submit(self.org.id, self.actor)
        VerificationService.start_review(self.org.id, self.actor)
        self.doc_reg.verification_status = "accepted"
        self.doc_reg.save()
        self.doc_tax.verification_status = "accepted"
        self.doc_tax.save()
        self.doc_auth.verification_status = "accepted"
        self.doc_auth.save()
        VerificationService.basic_approval(self.org.id, self.actor)

        verification = VerificationService.reset_due_to_evidence_replacement(self.org.id, self.actor)
        self.assertEqual(verification.status, VerificationStatus.DOCUMENTS_SUBMITTED)

    def test_invalid_transition(self):
        # Attempt to suspend an unverified org
        # Must initialize Verification first because suspend reads the state
        VerificationService.get_or_create_verification(self.org.id)
        with self.assertRaises(VerificationDomainException):
            VerificationService.suspend(self.org.id, self.actor, reason="Test")

    def test_decision_history_is_append_only_on_success(self):
        verification = VerificationService.get_or_create_verification(self.org.id)

        try:
             VerificationService.full_approval(self.org.id, self.actor)
        except VerificationDomainException:
             pass

        self.assertEqual(verification.decisions.count(), 0)
