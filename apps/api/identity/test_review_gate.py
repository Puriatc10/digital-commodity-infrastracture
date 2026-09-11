"""Executable security and integrity regressions for the Epic 2 gate."""
import io
import importlib
import os
import subprocess
import sys

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from identity.models import SystemRoleAssignment
from identity.serializers import UserSerializer
from organizations.models import Organization, OrganizationCapability, OrganizationMembership

User = get_user_model()


class ReviewGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="review@example.test", password="review-password")
        self.org = Organization.objects.create(name="Review own")
        self.foreign = Organization.objects.create(name="Review foreign")
        self.membership = OrganizationMembership.objects.create(user=self.user, organization=self.org)
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf(self):
        self.client.get('/api/auth/csrf')
        return {'HTTP_X_CSRFTOKEN': self.client.cookies['csrftoken'].value}

    def test_postgresql_is_authoritative(self):
        self.assertEqual(connection.vendor, 'postgresql')

    def test_login_requires_csrf_then_establishes_and_destroys_session(self):
        body = {'email': self.user.email, 'password': 'review-password'}
        self.assertEqual(self.client.post('/api/auth/login', body, format='json').status_code, 403)
        response = self.client.post('/api/auth/login', body, format='json', **self.csrf())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies['sessionid']['httponly'])
        self.assertEqual(response.cookies['sessionid']['samesite'], 'Lax')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 403)
        self.assertEqual(self.client.post('/api/auth/logout', **self.csrf()).status_code, 204)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 403)

    def test_session_revoked_for_inactive_user(self):
        self.client.force_login(self.user)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get('/api/auth/me').status_code, 403)

    def test_me_only_current_safe_active_context(self):
        other = User.objects.create_user(email='other@example.test')
        OrganizationMembership.objects.create(user=other, organization=self.foreign, role='owner')
        SystemRoleAssignment.objects.create(user=other, role='admin')
        inactive = Organization.objects.create(name='Inactive', is_active=False)
        OrganizationMembership.objects.create(user=self.user, organization=inactive)
        OrganizationMembership.objects.create(user=self.user, organization=self.foreign, is_active=False)
        self.client.force_login(self.user)
        data = self.client.get('/api/auth/me').json()
        self.assertEqual(set(data), {'id', 'email', 'is_active', 'system_roles', 'organizations'})
        self.assertEqual(data['system_roles'], [])
        self.assertEqual([o['organization']['id'] for o in data['organizations']], [str(self.org.id)])

    def test_me_capabilities_use_prefetch(self):
        for n in range(3):
            org = Organization.objects.create(name=f'Extra {n}')
            OrganizationMembership.objects.create(user=self.user, organization=org)
            OrganizationCapability.objects.create(organization=org, capability='buyer')
        with self.assertNumQueries(3):
            self.assertEqual(len(UserSerializer(self.user).data['organizations']), 4)

    def test_permission_matrix_real_sessions_and_csrf(self):
        for role, expected in [('viewer', 403), ('member', 403), ('manager', 200), ('owner', 200)]:
            with self.subTest(role=role):
                self.membership.role = role
                self.membership.save()
                self.client.force_login(self.user)
                headers = self.csrf()
                own = f'/api/organizations/{self.org.pk}/'
                foreign = f'/api/organizations/{self.foreign.pk}/'
                self.assertEqual(self.client.get(own).status_code, 200)
                self.assertEqual(self.client.patch(own, {'name': 'Changed'}, format='json').status_code, 403)
                self.assertEqual(self.client.patch(own, {'name': 'Changed'}, format='json', **headers).status_code, expected)
                self.assertEqual(self.client.get(foreign).status_code, 404)
                self.assertEqual(self.client.patch(foreign, {'name': 'Attack'}, format='json', **headers).status_code, 404)
                self.assertEqual([o['id'] for o in self.client.get('/api/organizations/').json()], [str(self.org.id)])

    def test_capabilities_and_malicious_payload_never_escalate(self):
        self.client.force_login(self.user)
        url = f'/api/organizations/{self.org.pk}/'
        for capability in ('buyer', 'supplier', 'broker'):
            OrganizationCapability.objects.create(organization=self.org, capability=capability)
            self.assertEqual(self.client.patch(url, {'name': 'Attack'}, format='json', **self.csrf()).status_code, 403)
        self.membership.role = 'owner'
        self.membership.save()
        response = self.client.patch(url, {'name': 'Safe', 'memberships': [{'user': self.user.pk, 'role': 'admin'}], 'role': 'admin', 'capabilities': [], 'system_roles': ['admin'], 'user': {'is_superuser': True}, 'is_active': False}, format='json', **self.csrf())
        self.assertEqual(response.status_code, 200)
        self.membership.refresh_from_db()
        self.org.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.membership.role, 'owner')
        self.assertEqual(self.org.capabilities.count(), 3)
        self.assertEqual(self.user.system_roles.count(), 0)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.org.is_active)

    def test_system_roles_independent_of_django_flags(self):
        self.membership.delete()
        self.client.force_login(self.user)
        for role, expected in [('operator', 403), ('admin', 200)]:
            self.user.system_roles.all().delete()
            SystemRoleAssignment.objects.create(user=self.user, role=role)
            self.assertEqual(len(self.client.get('/api/organizations/').json()), 2)
            self.assertEqual(self.client.patch(f'/api/organizations/{self.foreign.pk}/', {'name': 'Safe'}, format='json', **self.csrf()).status_code, expected)
            self.assertEqual(self.client.get('/api/auth/me').json()['organizations'], [])
        self.user.system_roles.all().delete()
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get('/api/organizations/').json(), [])

    def test_inactive_membership_and_org_are_hidden(self):
        self.client.force_login(self.user)
        for field, model in [('is_active', self.membership), ('is_active', self.org)]:
            setattr(model, field, False)
            model.save()
            self.assertEqual(self.client.get('/api/organizations/').json(), [])
            self.assertEqual(self.client.get('/api/auth/me').json()['organizations'], [])
            self.assertEqual(self.client.get(f'/api/organizations/{self.org.pk}/').status_code, 404)
            setattr(model, field, True)
            model.save()

    def test_bulk_database_constraints_and_role_combinations(self):
        OrganizationMembership.objects.create(user=self.user, organization=self.foreign, role='owner')
        self.assertEqual(self.membership.role, 'viewer')
        cases = [(OrganizationMembership, {'user': self.user, 'organization': self.org}),
                 (OrganizationMembership, {'user': User.objects.create_user(email='invalid@example.test'), 'organization': self.org, 'role': 'admin'})]
        OrganizationCapability.objects.create(organization=self.org, capability='buyer')
        cases += [(OrganizationCapability, {'organization': self.org, 'capability': value}) for value in ('buyer', 'trader')]
        for role in ('operator', 'admin'):
            SystemRoleAssignment.objects.create(user=self.user, role=role)
            cases.append((SystemRoleAssignment, {'user': self.user, 'role': role}))
        cases.append((SystemRoleAssignment, {'user': self.user, 'role': 'owner'}))
        for model, fields in cases:
            with self.subTest(model=model.__name__, fields=str(fields)):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.bulk_create([model(**fields)])
        self.assertEqual(set(self.user.system_roles.values_list('role', flat=True)), {'operator', 'admin'})

    def test_superuser_manager_and_password(self):
        user = User.objects.create_superuser('super@example.test', 'secret')
        self.assertTrue(user.is_superuser and user.is_staff and user.check_password('secret'))
        self.assertEqual(user.system_roles.count(), 0)
        for fields in ({'is_staff': False}, {'is_superuser': False}):
            with self.assertRaises(ValueError):
                User.objects.create_superuser('bad@example.test', **fields)

    def test_put_matches_required_profile_contract(self):
        self.membership.role = 'owner'
        self.membership.save()
        self.client.force_login(self.user)
        url = f'/api/organizations/{self.org.pk}/'
        self.assertEqual(self.client.put(url, {}, format='json', **self.csrf()).status_code, 400)
        self.assertEqual(self.client.patch(url, {}, format='json', **self.csrf()).status_code, 200)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=False)
    def test_disabled_demo_never_discloses_or_switches(self):
        self.assertEqual(self.client.get('/api/auth/demo-switch').status_code, 404)
        self.assertEqual(self.client.post('/api/auth/demo-switch', {'persona': 'buyer'}, format='json', **self.csrf()).status_code, 404)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 403)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_demo_seed_and_session_sequence(self):
        models = (User, Organization, OrganizationMembership, OrganizationCapability, SystemRoleAssignment)
        call_command('seed_demo_personas', stdout=io.StringIO())
        counts = [m.objects.count() for m in models]
        call_command('seed_demo_personas', stdout=io.StringIO())
        self.assertEqual([m.objects.count() for m in models], counts)
        self.assertEqual(self.client.post('/api/auth/demo-switch', {'persona': 'buyer'}, format='json').status_code, 403)
        for persona in ('buyer', 'supplier', 'broker', 'operator', 'admin', 'buyer'):
            response = self.client.post('/api/auth/demo-switch', {'persona': persona}, format='json', **self.csrf())
            self.assertEqual(response.status_code, 200)
            data = self.client.get('/api/auth/me').json()
            self.assertEqual(data['email'], f'{persona}@demo.local')
            self.assertEqual(data['system_roles'], [persona] if persona in ('operator', 'admin') else [])
            self.assertEqual(len(data['organizations']), 0 if persona in ('operator', 'admin') else 1)
            if data['organizations']:
                self.assertEqual(data['organizations'][0]['capabilities'], [persona])
        for payload in ({'persona': 'BUYER'}, {'persona': 'unknown'}, {'user_id': self.user.pk}, {'email': self.user.email}, {'username': self.user.email}, {'organization_id': str(self.org.pk)}):
            self.assertEqual(self.client.post('/api/auth/demo-switch', payload, format='json', **self.csrf()).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/demo-switch', '{', content_type='application/json', **self.csrf()).status_code, 400)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_demo_cannot_switch_to_inactive_account(self):
        User.objects.create_user(email='buyer@demo.local', is_active=False)
        self.assertEqual(self.client.post('/api/auth/demo-switch', {'persona': 'buyer'}, format='json', **self.csrf()).status_code, 404)

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=True)
    def test_seed_does_not_create_shared_password_login(self):
        call_command('seed_demo_personas', stdout=io.StringIO())
        for user in User.objects.filter(email__endswith='@demo.local'):
            self.assertFalse(user.has_usable_password())

    def test_upgrade_retires_only_the_public_demo_password(self):
        from django.db.migrations.executor import MigrationExecutor

        migration = importlib.import_module('identity.migrations.0003_retire_shared_demo_password')
        old = User.objects.create_user('admin@demo.local', 'demo1234')
        independent = User.objects.create_user('buyer@demo.local', 'independent-password')
        unrelated = User.objects.create_user('ordinary@example.test', 'demo1234')
        historical_apps = MigrationExecutor(connection).loader.project_state(
            [('identity', '0002_systemroleassignment')]
        ).apps
        with connection.schema_editor() as editor:
            migration.retire_shared_demo_password(historical_apps, editor)
            migration.retire_shared_demo_password(historical_apps, editor)
        old.refresh_from_db()
        independent.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertFalse(old.has_usable_password())
        self.assertTrue(independent.check_password('independent-password'))
        self.assertTrue(unrelated.check_password('demo1234'))

    @override_settings(DEMO_PERSONA_SWITCHER_ENABLED=False)
    def test_seed_requires_explicit_demo_enablement(self):
        with self.assertRaises(CommandError):
            call_command('seed_demo_personas', stdout=io.StringIO())

    def test_production_security_and_demo_flag_parsing(self):
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings.production',
               'DJANGO_DEBUG': 'false', 'DJANGO_ALLOWED_HOSTS': 'review.example.test'}
        code = ('from django.conf import settings; '
                'assert settings.SESSION_COOKIE_SECURE; '
                'assert settings.SESSION_COOKIE_HTTPONLY; '
                'assert settings.CSRF_COOKIE_SECURE; '
                'assert settings.SESSION_COOKIE_SAMESITE == "Lax"; '
                'assert not settings.DEMO_PERSONA_SWITCHER_ENABLED')
        for value in ('false', '0'):
            result = subprocess.run([sys.executable, '-c', code], env={**env, 'DEMO_PERSONA_SWITCHER_ENABLED': value}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, '-c', code], env={**env, 'DEMO_PERSONA_SWITCHER_ENABLED': 'true'}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Demo persona switching is unavailable in production', result.stderr)

    def test_me_regression_safe_fields(self):
        self.membership.role = 'owner'
        self.membership.save()
        self.client.force_login(self.user)
        response = self.client.get('/api/auth/me')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        org_context = data['organizations'][0]
        org = org_context['organization']

        # Capabilities exist on OrganizationContextSerializer directly under 'capabilities', not inside 'organization'
        self.assertIn('capabilities', org_context)

        # Ensure no sensitive fields leak in organization
        self.assertNotIn('documents', org)
        self.assertNotIn('internal_notes', org)
        self.assertNotIn('bank_details', org)

        # Ensure profile-only fields are NOT included in the identity serializer to maintain a narrow contract
        self.assertNotIn('commodities', org)
        self.assertNotIn('verification_status', org)
