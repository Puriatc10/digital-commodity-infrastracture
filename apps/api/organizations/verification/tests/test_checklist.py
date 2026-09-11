from django.test import TestCase
from django.contrib.auth import get_user_model
from organizations.models import Organization
from documents.models import VerificationDocument, DocumentType
from organizations.verification.models import VerificationStatus
from organizations.verification.services import VerificationService, VerificationDomainException
import uuid

User = get_user_model()

class VerificationChecklistDomainTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(email="admin@test.com", password="password")
        self.org = Organization.objects.create(name="Test Org", country="IR")
        self.org2 = Organization.objects.create(name="Other Org", country="IR")

        self.verification = VerificationService.submit(self.org.id, self.actor)
        VerificationService.start_review(self.org.id, self.actor)

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

    def test_successful_basic_approval(self):
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_tax.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_auth.id, self.actor, "accepted")

        ver = VerificationService.basic_approval(self.org.id, self.actor)
        self.assertEqual(ver.status, VerificationStatus.BASIC_VERIFIED)

    def test_missing_required_evidence_basic(self):
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_tax.id, self.actor, "accepted")
        # Missing auth rep
        with self.assertRaises(VerificationDomainException):
            VerificationService.basic_approval(self.org.id, self.actor)

    def test_rejected_evidence_basic(self):
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_tax.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_auth.id, self.actor, "rejected")

        with self.assertRaises(VerificationDomainException):
            VerificationService.basic_approval(self.org.id, self.actor)

    def test_successful_full_approval(self):
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_tax.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_auth.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_trade.id, self.actor, "accepted")
        VerificationService.review_checklist_item(self.org.id, self.doc_bank.id, self.actor, "accepted")

        ver = VerificationService.full_approval(self.org.id, self.actor)
        self.assertEqual(ver.status, VerificationStatus.VERIFIED)

    def test_superseded_evidence_blocks_review(self):
        self.doc_reg.verification_status = "replaced"
        self.doc_reg.save()

        with self.assertRaises(VerificationDomainException):
            VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted")

        with self.assertRaises(VerificationDomainException):
            VerificationService.basic_approval(self.org.id, self.actor)

    def test_foreign_organization_document(self):
        other_doc = VerificationDocument.objects.create(
            organization=self.org2, type=DocumentType.COMPANY_REGISTRATION,
            object_key="key6", size_bytes=100
        )
        # Attempt to review a document under wrong org
        with self.assertRaises(VerificationDomainException):
            VerificationService.review_checklist_item(self.org.id, other_doc.id, self.actor, "accepted")

    def test_forged_document_id(self):
        with self.assertRaises(VerificationDomainException):
            VerificationService.review_checklist_item(self.org.id, uuid.uuid4(), self.actor, "accepted")

    def test_stale_review_action(self):
        with self.assertRaises(VerificationDomainException):
            VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.actor, "accepted", expected_version=999)
