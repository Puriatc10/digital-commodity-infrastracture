from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .models import Organization, OrganizationCapability, OrganizationMembership

User = get_user_model()


class OrganizationModelTests(TestCase):
    def test_create_organization(self):
        org = Organization.objects.create(
            name="Test Org",
            registration_identifier="123456",
            country="IR"
        )
        self.assertEqual(org.name, "Test Org")
        self.assertTrue(org.is_active)
        self.assertIsNotNone(org.created_at)

    def test_required_fields(self):
        with self.assertRaises(IntegrityError):
            Organization.objects.create(name=None)


class OrganizationMembershipTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(email="user1@example.com", password="password")
        self.user2 = User.objects.create_user(email="user2@example.com", password="password")
        self.org1 = Organization.objects.create(name="Org 1")
        self.org2 = Organization.objects.create(name="Org 2")

    def test_create_membership(self):
        membership = OrganizationMembership.objects.create(
            user=self.user1,
            organization=self.org1,
            role=OrganizationMembership.OrganizationRole.MANAGER
        )
        self.assertEqual(membership.user, self.user1)
        self.assertEqual(membership.organization, self.org1)
        self.assertEqual(membership.role, "manager")
        self.assertTrue(membership.is_active)

    def test_default_membership_role(self):
        membership = OrganizationMembership.objects.create(
            user=self.user1,
            organization=self.org1
        )
        self.assertEqual(membership.role, "viewer")

    def test_multiple_orgs_per_user(self):
        OrganizationMembership.objects.create(
            user=self.user1, organization=self.org1, role=OrganizationMembership.OrganizationRole.OWNER
        )
        OrganizationMembership.objects.create(
            user=self.user1, organization=self.org2, role=OrganizationMembership.OrganizationRole.MEMBER
        )
        self.assertEqual(self.user1.organization_memberships.count(), 2)
        roles = set(self.user1.organization_memberships.values_list("role", flat=True))
        self.assertEqual(roles, {"owner", "member"})

    def test_multiple_users_per_org(self):
        OrganizationMembership.objects.create(user=self.user1, organization=self.org1)
        OrganizationMembership.objects.create(user=self.user2, organization=self.org1)
        self.assertEqual(self.org1.memberships.count(), 2)

    def test_duplicate_membership_rejection(self):
        OrganizationMembership.objects.create(user=self.user1, organization=self.org1)
        with self.assertRaises(IntegrityError):
            OrganizationMembership.objects.create(user=self.user1, organization=self.org1)

    def test_invalid_membership_role_rejection(self):
        with self.assertRaises(IntegrityError):
            OrganizationMembership.objects.create(
                user=self.user1,
                organization=self.org1,
                role="admin"
            )


class OrganizationCapabilityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")

    def test_create_capability(self):
        capability = OrganizationCapability.objects.create(
            organization=self.org,
            capability=OrganizationCapability.CapabilityType.BUYER
        )
        self.assertEqual(capability.capability, "buyer")

    def test_multiple_capabilities(self):
        OrganizationCapability.objects.create(
            organization=self.org,
            capability=OrganizationCapability.CapabilityType.BUYER
        )
        OrganizationCapability.objects.create(
            organization=self.org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER
        )
        self.assertEqual(self.org.capabilities.count(), 2)

    def test_duplicate_capability_rejection(self):
        OrganizationCapability.objects.create(
            organization=self.org,
            capability=OrganizationCapability.CapabilityType.BROKER
        )
        with self.assertRaises(IntegrityError):
            OrganizationCapability.objects.create(
                organization=self.org,
                capability=OrganizationCapability.CapabilityType.BROKER
            )

    def test_invalid_capability_rejection(self):
        with self.assertRaises(IntegrityError):
            OrganizationCapability.objects.create(
                organization=self.org,
                capability="trader"
            )
