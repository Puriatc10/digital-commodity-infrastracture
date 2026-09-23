from decimal import Decimal
from typing import Optional
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from deals.models import Deal
from deals.services.materialization import materialize_deals_from_award
from deals.tests.base import BaseDealsTestMixin
from execution.services import (
    add_milestone_definition,
    create_draft_version,
    create_workflow_template,
)
from offers.enums import LogisticsCostStatus, OfferorRole
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    create_offer,
    finalize_award,
    submit_internal_offer_version,
)
from organizations.models import OrganizationMembership
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class BaseExecutionTestMixin(BaseDealsTestMixin):
    """Shared test base mixin for Execution Monitor test suites."""

    def setUp(self):
        super().setUp()
        self.buyer_user = self.buyer_owner
        self.supplier_owner = self.supplier_user

        self.supplier_viewer = User.objects.create_user(
            email=f"supplier_view_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

    def create_sample_deal(
        self,
        *,
        external_seller: bool = False,
        logistics_cost_status: Optional[str] = None,
        logistics_cost_amount: Optional[Decimal] = None,
    ) -> Deal:
        """Helper to create a fresh, materialized Deal aggregate for execution tests."""
        rfq = RFQ.objects.create(
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

        if external_seller:
            award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
            add_award_allocation(
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
            all_deals, _ = materialize_deals_from_award(finalized_award.id, actor=self.operator_user)
            return all_deals[0]

        offer = create_offer(
            actor=self.supplier_user,
            rfq=rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        l_status = logistics_cost_status or LogisticsCostStatus.INCLUDED_IN_PRICE
        v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB Bandar Abbas",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=l_status,
            logistics_cost_amount=logistics_cost_amount,
        )
        offer.refresh_from_db()
        v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v1.id,
            expected_version=offer.aggregate_version,
        )

        award = create_draft_award(rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            award.id,
            offer_version_id=v1.id,
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
        all_deals, _ = materialize_deals_from_award(finalized_award.id, actor=self.operator_user)
        return all_deals[0]

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


class BaseExecutionTestCase(BaseExecutionTestMixin, TestCase):
    """Shared test base for Execution Monitor test suites."""


class BaseExecutionTransactionTestCase(BaseExecutionTestMixin, TransactionTestCase):
    """Shared test base for multi-threaded Execution concurrency tests."""

