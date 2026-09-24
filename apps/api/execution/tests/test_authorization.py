from django.contrib.auth.models import AnonymousUser

from execution.exceptions import ExecutionPermissionDeniedError
from execution.services import (
    create_draft_version,
    create_workflow_template,
)
from execution.tests.base import BaseExecutionTestCase


class ExecutionWorkflowAuthorizationTests(BaseExecutionTestCase):
    """Test product-internal SystemRole authorization rules for workflow template management."""

    def test_operator_authorized(self):
        """Platform Operator holds full workflow definition management authority."""
        tmpl = create_workflow_template(
            code="auth_operator",
            name_fa="تست اپراتور",
            name_en="Operator Test",
            actor=self.operator_user,
        )
        self.assertIsNotNone(tmpl)

        v = create_draft_version(tmpl, actor=self.operator_user)
        self.assertEqual(v.version_number, 1)

    def test_admin_authorized(self):
        """Product Admin holds full workflow definition management authority."""
        tmpl = create_workflow_template(
            code="auth_admin",
            name_fa="تست ادمین",
            name_en="Admin Test",
            actor=self.admin_user,
        )
        self.assertIsNotNone(tmpl)

        v = create_draft_version(tmpl, actor=self.admin_user)
        self.assertEqual(v.version_number, 1)

    def test_django_staff_superuser_alone_denied(self):
        """
        Django staff/superuser alone without SystemRoleAssignment has zero product authority.
        """
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_workflow_template(
                code="auth_staff",
                name_fa="تست استف",
                name_en="Staff Test",
                actor=self.staff_only_user,
            )

        template = self.create_sample_template()
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_draft_version(template, actor=self.staff_only_user)

    def test_buyer_organization_denied(self):
        """Buyer organization users cannot manage workflow configurations."""
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_workflow_template(
                code="auth_buyer",
                name_fa="تست خریدار",
                name_en="Buyer Test",
                actor=self.buyer_user,
            )

    def test_supplier_organization_denied(self):
        """Supplier organization users cannot manage workflow configurations."""
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_workflow_template(
                code="auth_supplier",
                name_fa="تست تامین‌کننده",
                name_en="Supplier Test",
                actor=self.supplier_user,
            )

    def test_broker_organization_denied(self):
        """Broker organization users cannot manage workflow configurations."""
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_workflow_template(
                code="auth_broker",
                name_fa="تست بروکر",
                name_en="Broker Test",
                actor=self.broker_user,
            )

    def test_anonymous_denied(self):
        """Anonymous callers are rejected."""
        with self.assertRaises(ExecutionPermissionDeniedError):
            create_workflow_template(
                code="auth_anon",
                name_fa="ناشناس",
                name_en="Anonymous Test",
                actor=AnonymousUser(),
            )
