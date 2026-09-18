from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class BaseOffersTestCase(TestCase):
    """Shared fixture foundation for Offer domain and service tests."""

    def setUp(self):
        super().setUp()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_{uuid.uuid4().hex[:6]}",
            name_fa="قیر تست",
            name_en="Test Bitumen",
            is_active=True,
        )
        self.schema_version = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=self.schema_version,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        publish_schema(self.schema_version, activate=True)

        # Buyer Organization
        self.buyer_org = Organization.objects.create(
            name="Buyer Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )

        # Buyer User & Membership
        self.buyer_user = User.objects.create_user(
            email="buyer@buyer-corp.com",
            password="testpassword123",
        )
        self.buyer_membership = OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Standard Published RFQ
        self.published_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier Organization (Supplier capability only)
        self.supplier_org = Organization.objects.create(
            name="Supplier Petro Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user = User.objects.create_user(
            email="supplier@petrocorp.com",
            password="testpassword123",
        )
        self.supplier_membership = OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Broker Organization (Broker capability only)
        self.broker_org = Organization.objects.create(
            name="Brokerage Global",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.broker_user = User.objects.create_user(
            email="broker@global.com",
            password="testpassword123",
        )
        self.broker_membership = OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Multi-capability Organization (Both Supplier and Broker)
        self.multi_org = Organization.objects.create(
            name="Dual Capability Commercial Co",
            country="TR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.multi_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCapability.objects.create(
            organization=self.multi_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.multi_user = User.objects.create_user(
            email="dual@commercial.com",
            password="testpassword123",
        )
        self.multi_membership = OrganizationMembership.objects.create(
            organization=self.multi_org,
            user=self.multi_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # External Counterparty (off-platform)
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Gulf Bitumen External FZE",
            contact_name="Farhad Khan",
            phone="+971501234567",
            email="farhad@gulfbitumen.ae",
            geography="Dubai, UAE",
        )

        # Platform Operator (with SystemRoleAssignment)
        self.operator_user = User.objects.create_user(
            email="operator@platform.internal",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # Platform Product Admin (with SystemRoleAssignment)
        self.admin_user = User.objects.create_user(
            email="admin@platform.internal",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Django staff-only (NO SystemRoleAssignment)
        self.staff_only_user = User.objects.create_user(
            email="staff@platform.internal",
            password="testpassword123",
            is_staff=True,
        )

        # Django superuser-only (NO SystemRoleAssignment)
        self.superuser_only_user = User.objects.create_superuser(
            email="superuser@platform.internal",
            password="testpassword123",
        )

        # Qualified Supply Opportunity for external counterparty
        self.opp_external_qualified = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )
