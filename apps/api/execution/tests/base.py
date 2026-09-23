import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from execution.services import (
    add_milestone_definition,
    create_draft_version,
    create_workflow_template,
)
from identity.models import SystemRoleAssignment
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class BaseExecutionTestCase(TestCase):
    """Shared test base for Execution Monitor test suites."""

    def setUp(self):
        super().setUp()

        # Platform Operator & Admin
        self.operator_user = User.objects.create_user(
            email=f"operator_{uuid.uuid4().hex[:6]}@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        self.admin_user = User.objects.create_user(
            email=f"admin_{uuid.uuid4().hex[:6]}@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Staff/superuser only (no SystemRoleAssignment)
        self.staff_only_user = User.objects.create_user(
            email=f"staff_{uuid.uuid4().hex[:6]}@platform.com",
            password="testpassword123",
            is_staff=True,
            is_superuser=True,
        )

        # Customer User (Buyer)
        self.buyer_org = Organization.objects.create(
            name="Buyer Organization",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email=f"buyer_{uuid.uuid4().hex[:6]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Customer User (Supplier)
        self.supplier_org = Organization.objects.create(
            name="Supplier Organization",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user = User.objects.create_user(
            email=f"supplier_{uuid.uuid4().hex[:6]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Customer User (Broker)
        self.broker_org = Organization.objects.create(
            name="Broker Organization",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.broker_user = User.objects.create_user(
            email=f"broker_{uuid.uuid4().hex[:6]}@broker.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

    def create_sample_template(self, code=None, name_en="Standard Execution", name_fa="اجرای استاندارد"):
        if not code:
            code = f"template_{uuid.uuid4().hex[:8]}"
        return create_workflow_template(
            code=code,
            name_fa=name_fa,
            name_en=name_en,
            description="Sample execution workflow",
            actor=self.operator_user,
        )

    def create_sample_linear_draft(self, template=None):
        """Create a valid 3-step linear workflow version (M1 -> M2 -> M3[terminal])."""
        if not template:
            template = self.create_sample_template()

        version = create_draft_version(template, actor=self.operator_user)

        m1 = add_milestone_definition(
            version,
            code="STEP_ONE",
            name_fa="مرحله اول",
            name_en="Step One",
            sort_order=1,
            required=True,
            blocking=False,
            terminal=False,
            actor=self.operator_user,
        )
        m2 = add_milestone_definition(
            version,
            code="STEP_TWO",
            name_fa="مرحله دوم",
            name_en="Step Two",
            sort_order=2,
            required=True,
            blocking=True,
            terminal=False,
            prerequisite_codes=["STEP_ONE"],
            actor=self.operator_user,
        )
        m3 = add_milestone_definition(
            version,
            code="FINAL_STEP",
            name_fa="مرحله نهایی",
            name_en="Final Step",
            sort_order=3,
            required=True,
            blocking=True,
            terminal=True,
            prerequisite_codes=["STEP_TWO"],
            actor=self.operator_user,
        )
        return version, (m1, m2, m3)
