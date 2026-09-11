from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from organizations.models import Organization, OrganizationMembership
from identity.models import SystemRoleAssignment
from organizations.verification.services import VerificationService

User = get_user_model()

class VerificationPermissionTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Perm Test Org", country="IR")
        self.other_org = Organization.objects.create(name="Other Org", country="US")

        self.owner = User.objects.create_user(email="owner@test.com", password="password")
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role=OrganizationMembership.OrganizationRole.OWNER)

        self.viewer = User.objects.create_user(email="viewer@test.com", password="password")
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role=OrganizationMembership.OrganizationRole.VIEWER)

        self.operator = User.objects.create_user(email="operator@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.admin = User.objects.create_user(email="admin@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.admin, role=SystemRoleAssignment.SystemRole.ADMIN)

        self.superuser = User.objects.create_user(email="super@test.com", password="password", is_staff=True, is_superuser=True)

        self.submit_url = reverse('verification:submit', kwargs={'org_id': self.org.id})
        self.start_review_url = reverse('verification:start-review', kwargs={'org_id': self.org.id})

    def test_owner_can_submit(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(self.submit_url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_submit(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(self.submit_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_cannot_review(self):
        self.client.force_authenticate(user=self.owner)
        self.client.post(self.submit_url, {})

        response = self.client.post(self.start_review_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_can_review(self):
        VerificationService.submit(self.org.id, self.owner)

        self.client.force_authenticate(user=self.operator)
        # Note: Need expected version
        v = VerificationService.get_or_create_verification(self.org.id)
        response = self.client.post(self.start_review_url, {"expected_version": v.version}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_django_superuser_cannot_review_without_product_role(self):
        VerificationService.submit(self.org.id, self.owner)

        self.client.force_authenticate(user=self.superuser)
        v = VerificationService.get_or_create_verification(self.org.id)
        response = self.client.post(self.start_review_url, {"expected_version": v.version}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_organization_mutations_blocked(self):
        self.org.is_active = False
        self.org.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(self.submit_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        VerificationService.get_or_create_verification(self.org.id)
        # Attempt review with operator
        self.client.force_authenticate(user=self.operator)
        response = self.client.post(self.start_review_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail_read_projection(self):
        VerificationService.submit(self.org.id, self.owner)
        detail_url = reverse('verification:detail', kwargs={'org_id': self.org.id})

        # Owner can read
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(reverse('verification:notes-create', kwargs={'org_id': self.org.id}), {'note': 'Test'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN) # only operator can write notes

        self.client.force_authenticate(user=self.operator)
        self.client.post(reverse('verification:notes-create', kwargs={'org_id': self.org.id}), {'note': 'Internal note'}, format='json')

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['notes']) # Owner cannot see internal notes

        self.client.force_authenticate(user=self.operator)
        response = self.client.get(detail_url)
        self.assertIsNotNone(response.data['notes'])
        self.assertEqual(len(response.data['notes']), 1)

    def test_foreign_organization_isolation(self):
        self.client.force_authenticate(user=self.owner)
        # Owner of self.org tries to submit for self.other_org
        submit_other_url = reverse('verification:submit', kwargs={'org_id': self.other_org.id})
        response = self.client.post(submit_other_url, {})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
