from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from offers.enums import LogisticsCostStatus, OfferorRole
from offers.models import Award, AwardAllocation, Offer, OfferVersion
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    create_offer,
    finalize_award,
    submit_internal_offer_version,
)
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class BaseDealsTestMixin:
    """Shared test foundation mixin for Deal models, services, and API endpoints."""

    def setUp(self):
        super().setUp()

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_deal_{uuid.uuid4().hex[:6]}",
            name_fa="قیر تست معامله",
            name_en="Deal Test Bitumen",
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

        # Buyer Organization & Members
        self.buyer_org = Organization.objects.create(
            name="Buyer Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )

        self.buyer_owner = User.objects.create_user(
            email=f"buyer_owner_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.buyer_manager = User.objects.create_user(
            email=f"buyer_mgr_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_manager,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        self.buyer_member = User.objects.create_user(
            email=f"buyer_mem_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        self.buyer_viewer = User.objects.create_user(
            email=f"buyer_view_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        # Foreign / Competitor Buyer Organization
        self.foreign_buyer_org = Organization.objects.create(
            name="Foreign Buyer Ltd",
            country="TR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.foreign_buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.foreign_buyer_user = User.objects.create_user(
            email=f"foreign_{uuid.uuid4().hex[:4]}@foreign.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.foreign_buyer_org,
            user=self.foreign_buyer_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        # Platform Operator & Admin
        self.operator_user = User.objects.create_user(
            email=f"operator_{uuid.uuid4().hex[:4]}@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        self.admin_user = User.objects.create_user(
            email=f"admin_{uuid.uuid4().hex[:4]}@platform.com",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Staff/superuser only (no SystemRoleAssignment)
        self.staff_only_user = User.objects.create_user(
            email=f"staff_{uuid.uuid4().hex[:4]}@platform.com",
            password="testpassword123",
            is_staff=True,
            is_superuser=True,
        )

        # Supplier Organization & User
        self.supplier_org = Organization.objects.create(
            name="Supplier Petro Corp",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationVerification.objects.create(
            organization=self.supplier_org,
            status=VerificationStatus.VERIFIED,
            version=1,
        )
        self.supplier_user = User.objects.create_user(
            email=f"supplier_{uuid.uuid4().hex[:4]}@petrocorp.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Broker Organization & User
        self.broker_org = Organization.objects.create(
            name="Broker Global Corp",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationVerification.objects.create(
            organization=self.broker_org,
            status=VerificationStatus.VERIFIED,
            version=1,
        )
        self.broker_user = User.objects.create_user(
            email=f"broker_{uuid.uuid4().hex[:4]}@brokerglobal.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Target RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_owner,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.COLLECTING_OFFERS,
            visibility=RFQVisibility.PUBLIC,
        )

        # Internal Supplier Offer & Submitted V1
        self.supplier_offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.supplier_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.supplier_offer.refresh_from_db()
        self.supplier_v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.supplier_v1.id,
            expected_version=self.supplier_offer.aggregate_version,
        )
        self.supplier_offer.refresh_from_db()

        # Broker Offer & Submitted V1
        self.broker_offer = create_offer(
            actor=self.broker_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        self.broker_v1 = create_draft_offer_version(
            actor=self.broker_user,
            offer=self.broker_offer.id,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("345.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="TT 30 days",
            delivery_terms="CIF Mersin",
            incoterm="CIF",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.broker_offer.refresh_from_db()
        self.broker_v1 = submit_internal_offer_version(
            actor=self.broker_user,
            offer_version=self.broker_v1.id,
            expected_version=self.broker_offer.aggregate_version,
        )
        self.broker_offer.refresh_from_db()

        # External Counterparty & Offer
        self.ext_counterparty = ExternalCounterparty.objects.create(
            company_name="External Bitumen Trader Ltd",
            contact_name="Mr. Karimi",
            email="karimi@external.com",
            phone="+989123456789",
            geography="Iran",
        )
        self.supply_opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            status=OpportunityStatus.QUALIFIED,
            source=OpportunitySource.OPERATOR_SOURCING,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("200.000"),
            unit="MT",
            indicative_price=Decimal("340.00"),
            currency="USD",
            external_counterparty=self.ext_counterparty,
            created_by=self.operator_user,
        )
        self.ext_offer = Offer.objects.create(
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.ext_counterparty,
            source_opportunity=self.supply_opp,
            created_by=self.operator_user,
        )
        self.ext_v1 = OfferVersion.objects.create(
            offer=self.ext_offer,
            version_number=1,
            status=OfferVersion.OfferVersionStatus.SUBMITTED if hasattr(OfferVersion, "OfferVersionStatus") else "SUBMITTED",
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
            submitted_by=self.operator_user,
            submitted_at=timezone.now(),
            created_by=self.operator_user,
        )
        self.ext_offer.current_submitted_version = self.ext_v1
        self.ext_offer.save(update_fields=["current_submitted_version"])

    def create_and_finalize_single_award(self) -> tuple[Award, AwardAllocation]:
        """Creates a finalized award with a single allocation for testing."""
        award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        award.refresh_from_db()
        finalized_award = finalize_award(
            award.id,
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        alloc.refresh_from_db()
        return finalized_award, alloc

    def create_and_finalize_multi_award(self) -> tuple[Award, list[AwardAllocation]]:
        """Creates a finalized award with 3 allocations (Supplier, Broker, External)."""
        award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        alloc1 = add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        award.refresh_from_db()
        alloc2 = add_award_allocation(
            award.id,
            offer_version_id=self.broker_v1.id,
            awarded_quantity=Decimal("300.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        award.refresh_from_db()
        alloc3 = add_award_allocation(
            award.id,
            offer_version_id=self.ext_v1.id,
            awarded_quantity=Decimal("200.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        award.refresh_from_db()
        finalized_award = finalize_award(
            award.id,
            expected_version=award.version,
            actor=self.buyer_owner,
        )
        alloc1.refresh_from_db()
        alloc2.refresh_from_db()
        alloc3.refresh_from_db()
        return finalized_award, [alloc1, alloc2, alloc3]


class BaseDealsTestCase(BaseDealsTestMixin, TestCase):
    """Shared test foundation for Deal models, services, and API endpoints."""


class BaseDealsTransactionTestCase(BaseDealsTestMixin, TransactionTestCase):
    """Shared test foundation for Deal tests requiring multi-threaded transactions."""

