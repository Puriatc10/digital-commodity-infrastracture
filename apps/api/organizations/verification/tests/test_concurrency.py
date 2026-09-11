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
