from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from organizations.models import Organization, OrganizationMembership
from identity.models import SystemRoleAssignment
from documents.models import VerificationDocument, DocumentType
from organizations.verification.models import VerificationStatus
from organizations.verification.services import VerificationService

User = get_user_model()

class VerificationEpicIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Integration Org", country="IR", registration_identifier="123456")

        self.owner = User.objects.create_user(email="owner@test.com", password="password")
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role=OrganizationMembership.OrganizationRole.OWNER)

        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.superuser = User.objects.create_user(email="super@test.com", password="password", is_staff=True, is_superuser=True)

        self.queue_url = reverse('verification-queue')

    def test_queue_authorization_and_visibility(self):
        # 1. Unverified initially, shouldn't be in pending queue
        VerificationService.get_or_create_verification(self.org.id)

        client_op = APIClient()
        client_op.force_authenticate(user=self.operator)

        response = client_op.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']) if isinstance(response.data, dict) and 'results' in response.data else len(response.data), 0)

        # 2. Ordinary user cannot access queue
        client_owner = APIClient()
        client_owner.force_authenticate(user=self.owner)
        response = client_owner.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Superuser without role cannot access
        client_super = APIClient()
        client_super.force_authenticate(user=self.superuser)
        response = client_super.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Submit
        VerificationService.submit(self.org.id, self.owner)

        # 5. Should be in pending queue now
        response = client_op.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(len(response.data['results']) if isinstance(response.data, dict) and 'results' in response.data else len(response.data), 1)
        self.assertEqual(response.data['results'][0]['status'] if isinstance(response.data, dict) and 'results' in response.data else response.data[0]['status'], VerificationStatus.DOCUMENTS_SUBMITTED)
        self.assertEqual(response.data['results'][0]['organization_name'] if isinstance(response.data, dict) and 'results' in response.data else response.data[0]['organization_name'], "Integration Org")
        self.assertNotIn('notes', response.data['results'][0] if isinstance(response.data, dict) and 'results' in response.data else response.data[0]) # queue shouldn't expose sensitive data

    def test_end_to_end_operator_workflow(self):
        client_owner = APIClient()
        client_owner.force_authenticate(user=self.owner)

        client_op = APIClient()
        client_op.force_authenticate(user=self.operator)

        # 1. Start unverified
        v = VerificationService.get_or_create_verification(self.org.id)

        # 2. Owner submits
        submit_url = reverse('verification:submit', kwargs={'org_id': self.org.id})
        res = client_owner.post(submit_url, {"expected_version": v.version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        current_version = res.data['version']

        # 3. Op sees in queue
        res = client_op.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(len(res.data['results']) if isinstance(res.data, dict) and 'results' in res.data else len(res.data), 1)

        # 4. Op starts review
        start_review_url = reverse('verification:start-review', kwargs={'org_id': self.org.id})
        res = client_op.post(start_review_url, {"expected_version": current_version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        current_version = res.data['version']

        # 5. Documents submitted externally (simulating document upload)
        doc_reg = VerificationDocument.objects.create(organization=self.org, type=DocumentType.COMPANY_REGISTRATION, object_key="k1", size_bytes=10, uploaded_by=self.owner, is_current=True)
        doc_tax = VerificationDocument.objects.create(organization=self.org, type=DocumentType.TAX_ID, object_key="k2", size_bytes=10, uploaded_by=self.owner, is_current=True)
        doc_auth = VerificationDocument.objects.create(organization=self.org, type=DocumentType.AUTHORIZED_REPRESENTATIVE, object_key="k3", size_bytes=10, uploaded_by=self.owner, is_current=True)

        # 6. Op reviews checklist
        checklist_url = reverse('verification:checklist-review', kwargs={'org_id': self.org.id})
        res = client_op.post(checklist_url, {"document_id": doc_reg.id, "outcome": "accepted", "expected_version": current_version}, format='json')
        current_version = res.data['version']
        res = client_op.post(checklist_url, {"document_id": doc_tax.id, "outcome": "accepted", "expected_version": current_version}, format='json')
        current_version = res.data['version']
        res = client_op.post(checklist_url, {"document_id": doc_auth.id, "outcome": "accepted", "expected_version": current_version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        current_version = res.data['version']

        # 7. Op writes a note
        notes_url = reverse('verification:notes-create', kwargs={'org_id': self.org.id})
        res = client_op.post(notes_url, {"note": "Looks good"}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # 8. Op basic approves
        approve_basic_url = reverse('verification:approve-basic', kwargs={'org_id': self.org.id})
        res = client_op.post(approve_basic_url, {"expected_version": current_version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 9. No longer pending
        res = client_op.get(self.queue_url, {'is_pending': 'true'})
        self.assertEqual(len(res.data['results']) if isinstance(res.data, dict) and 'results' in res.data else len(res.data), 0)

        # 10. Check directory projection matches
        dir_url = reverse('directory-list')
        client_anon = APIClient()
        res = client_anon.get(dir_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN) # Directory requires auth

        client_owner.force_authenticate(user=self.owner)
        res = client_owner.get(dir_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        data_list = res.data['results'] if isinstance(res.data, dict) and 'results' in res.data else res.data
        org_data = next((item for item in data_list if item["id"] == str(self.org.id)), None)
        self.assertIsNotNone(org_data)
        self.assertEqual(org_data['verification_status'], VerificationStatus.BASIC_VERIFIED)

    def test_rejection_reason_validation(self):
        client_op = APIClient()
        client_op.force_authenticate(user=self.operator)
        v = VerificationService.submit(self.org.id, self.owner)
        v = VerificationService.start_review(self.org.id, self.operator, expected_version=v.version)

        reject_url = reverse('verification:reject', kwargs={'org_id': self.org.id})
        res = client_op.post(reject_url, {"expected_version": v.version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST) # Reason required

        res = client_op.post(reject_url, {"reason": "Fake docs", "expected_version": v.version}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
