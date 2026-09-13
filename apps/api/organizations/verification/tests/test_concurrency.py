from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from organizations.models import Organization
from documents.models import VerificationDocument, DocumentType
from organizations.verification.models import OrganizationVerification, VerificationStatus
from organizations.verification.services import VerificationService
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from identity.models import SystemRoleAssignment

User = get_user_model()

class VerificationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Concurrency Org", country="IR")
        self.operator1 = User.objects.create_user(email="op1@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator1, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.operator2 = User.objects.create_user(email="op2@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator2, role=SystemRoleAssignment.SystemRole.OPERATOR)

        verification = VerificationService.get_or_create_verification(self.org.id)
        verification.status = VerificationStatus.UNDER_REVIEW
        verification.save()
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

        self.doc_reg.verification_status = "accepted"
        self.doc_reg.save()
        self.doc_tax.verification_status = "accepted"
        self.doc_tax.save()
        self.doc_auth.verification_status = "accepted"
        self.doc_auth.save()


    def test_stale_update_is_rejected(self):
        client1 = APIClient()
        client1.force_authenticate(user=self.operator1)

        client2 = APIClient()
        client2.force_authenticate(user=self.operator2)

        detail_url = reverse('verification:detail', kwargs={'org_id': self.org.id})

        # Both operators get the detail (version = 1)
        resp1 = client1.get(detail_url)
        resp2 = client2.get(detail_url)

        version1 = resp1.data['version']
        version2 = resp2.data['version']
        self.assertEqual(version1, version2)

        # Operator 1 approves basic
        approve_basic_url = reverse('verification:approve-basic', kwargs={'org_id': self.org.id})
        res1 = client1.post(approve_basic_url, {"expected_version": version1}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        # Operator 2 attempts to reject with the stale version
        reject_url = reverse('verification:reject', kwargs={'org_id': self.org.id})
        res2 = client2.post(reject_url, {"reason": "Not enough docs", "expected_version": version2}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale object", res2.data['detail'])

        # Confirm DB state is BASIC_VERIFIED (Operator 1 won)
        verification = OrganizationVerification.objects.get(organization_id=self.org.id)
        self.assertEqual(verification.status, VerificationStatus.BASIC_VERIFIED)

    def test_approval_vs_evidence_replacement_race(self):
        # Real B1 race condition test using threading and multiple database connections.
        # Reviewer A begins Basic approval using current accepted evidence, but a
        # concurrent request replaces required evidence before they acquire the lock.

        from django.db import connection, transaction
        from documents.models import DocumentType
        import threading
        import time

        verification = OrganizationVerification.objects.get(organization_id=self.org.id)
        current_version = verification.version
        org_id = self.org.id
        operator = self.operator1

        barrier = threading.Barrier(2)
        results = {}

        def thread_approve():
            try:
                barrier.wait()
                time.sleep(0.1) # yield to let upload acquire lock

                VerificationService.basic_approval(org_id, operator, expected_version=current_version)
                results['approve'] = 'success'
            except Exception as e:
                results['approve'] = str(e)
            finally:
                connection.close()

        def thread_upload():
            try:
                barrier.wait()
                with transaction.atomic():
                    # lock verification
                    v = OrganizationVerification.objects.select_for_update().get(organization_id=org_id)

                    VerificationDocument.objects.filter(
                        organization_id=org_id,
                        type=DocumentType.COMPANY_REGISTRATION,
                        is_current=True
                    ).update(is_current=False)

                    VerificationDocument.objects.create(
                        organization_id=org_id,
                        type=DocumentType.COMPANY_REGISTRATION,
                        object_key="key_new_concurrent",
                        size_bytes=100,
                        is_current=True,
                        verification_status="pending"
                    )

                    time.sleep(0.5)

                    v.version += 1
                    v.save()

                results['upload'] = 'success'
            except Exception as e:
                results['upload'] = str(e)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_approve)
        t2 = threading.Thread(target=thread_upload)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Upload should succeed
        self.assertEqual(results['upload'], 'success')

        # Approval MUST fail since evidence was replaced and is no longer accepted
        err = results.get('approve', '')
        self.assertTrue(
            "Stale object error" in err or "Missing accepted documents" in err,
            f"Expected domain exception for approve, got: {err}"
        )

        verification.refresh_from_db()
        self.assertEqual(verification.status, VerificationStatus.UNDER_REVIEW)

    def test_concurrent_first_uploads(self):
        # M4: Two concurrent first uploads cannot leave two is_current=True documents
        from django.db import IntegrityError

        # Test creation of first upload
        VerificationDocument.objects.create(
            organization=self.org,
            type=DocumentType.TRADE_LICENSE,
            object_key="trade1",
            size_bytes=100,
            is_current=True
        )

        # Simulating concurrent transaction uploading a second one of the same type without
        # toggling is_current on doc1
        with self.assertRaises(IntegrityError):
            VerificationDocument.objects.create(
                organization=self.org,
                type=DocumentType.TRADE_LICENSE,
                object_key="trade2",
                size_bytes=100,
                is_current=True
            )

    def test_concurrent_checklist_reviewers(self):
        # Prove two concurrent checklist reviewers cannot overwrite each other
        verification = OrganizationVerification.objects.get(organization_id=self.org.id)
        current_version = verification.version

        # Operator 1 accepts
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.operator1, "accepted", expected_version=current_version)

        # Operator 2 attempts to reject using the old version
        with self.assertRaises(Exception) as context:
            VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.operator2, "rejected", expected_version=current_version)

        self.assertIn("Stale object error", str(context.exception))

        # Verify the review history reflects only Operator 1
        reviews = self.doc_reg.reviews.all()
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews[0].reviewer, self.operator1)
        self.assertEqual(reviews[0].outcome, "accepted")

    def test_approval_vs_checklist_rejection_race(self):
        # Prove approval fails if a checklist item is concurrently rejected.
        verification = OrganizationVerification.objects.get(organization_id=self.org.id)
        current_version = verification.version

        # Simulate checklist rejection
        VerificationService.review_checklist_item(self.org.id, self.doc_reg.id, self.operator2, "rejected", expected_version=current_version)

        # Operator 1 tries to approve with old version
        with self.assertRaises(Exception) as context:
             VerificationService.basic_approval(self.org.id, self.operator1, expected_version=current_version)

        self.assertIn("Stale object error", str(context.exception))
