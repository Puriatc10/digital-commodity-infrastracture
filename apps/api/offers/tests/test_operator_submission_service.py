from datetime import date, timedelta
from decimal import Decimal
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from offers.enums import CostComponentKind, LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import (
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
)
from offers.models import Offer, OfferVersion
from offers.services import create_offer, submit_operator_external_offer
from offers.tests.base import BaseOffersTestCase
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from organizations.models import Organization, OrganizationCapability, OrganizationMembership
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class OperatorExternalOfferSubmissionServiceTests(BaseOffersTestCase):
    """
    Comprehensive domain service tests for T0804 (Operator Submission on Behalf)
    and executable closure proof for Epic 6 T0611.
    """

    def _get_valid_commercial_kwargs(self):
        return {
            "offered_quantity": Decimal("150.000"),
            "quantity_unit": "MT",
            "unit_price": Decimal("480.00"),
            "currency": "USD",
            "payment_terms": "LC at sight",
            "delivery_terms": "FOB Bandar Abbas",
            "incoterm": "FOB",
            "delivery_start": date.today() + timedelta(days=5),
            "delivery_end": date.today() + timedelta(days=20),
            "valid_until": timezone.now() + timedelta(days=10),
            "logistics_cost_status": LogisticsCostStatus.INCLUDED_IN_PRICE,
            "specifications": {"penetration_grade": "60/70"},
            "notes": "Direct refinery external allocation.",
        }

    # --- Authorization Tests ---

    def test_operator_can_submit_external_offer(self):
        """Operator user (with SystemRoleAssignment) can authoritatively submit an external offer."""
        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.rfq_id, self.published_rfq.id)
        self.assertEqual(offer.external_counterparty_id, self.external_cp.id)
        self.assertIsNone(offer.offering_organization_id)
        self.assertEqual(offer.offeror_role, OfferorRole.SUPPLIER)
        self.assertEqual(offer.source_opportunity_id, self.opp_external_qualified.id)
        self.assertEqual(offer.created_by_id, self.operator_user.id)
        self.assertTrue(offer.entered_by_operator)
        self.assertTrue(offer.is_external)

        self.assertEqual(version.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.submitted_by_id, self.operator_user.id)
        self.assertIsNotNone(version.submitted_at)
        self.assertEqual(offer.current_submitted_version_id, version.id)

    def test_product_admin_can_submit_external_offer(self):
        """Product Admin (with SystemRoleAssignment) can submit an external offer."""
        offer, version = submit_operator_external_offer(
            actor=self.admin_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(version.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(version.submitted_by_id, self.admin_user.id)

    def test_buyer_member_cannot_submit_external_offer(self):
        """Buyer organization member without system role cannot submit an external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=self.buyer_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    def test_supplier_member_cannot_submit_external_offer(self):
        """Supplier organization member without system role cannot submit an external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    def test_broker_member_cannot_submit_external_offer(self):
        """Broker organization member without system role cannot submit an external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=self.broker_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    def test_django_staff_only_cannot_submit_external_offer(self):
        """Django is_staff alone does NOT grant product operator authority."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=self.staff_only_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    def test_django_superuser_only_cannot_submit_external_offer(self):
        """Django is_superuser alone does NOT grant product operator authority."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=self.superuser_only_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    def test_unauthenticated_actor_rejected(self):
        """Unauthenticated or None actor is rejected."""
        with self.assertRaises(OfferPermissionDeniedError):
            submit_operator_external_offer(
                actor=None,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )

    # --- Opportunity Validation & Counterparty Derivation Tests ---

    def test_demand_opportunity_rejected(self):
        """Demand opportunity cannot yield an external offer."""
        demand_opp = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )
        with self.assertRaises(OfferValidationError) as ctx:
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=demand_opp,
                **self._get_valid_commercial_kwargs(),
            )
        self.assertIn("direction must be SUPPLY", str(ctx.exception))

    def test_non_qualified_opportunity_rejected(self):
        """Opportunity not in Qualified status rejects submission across all invalid states."""
        invalid_statuses = [
            OpportunityStatus.CAPTURED,
            OpportunityStatus.CONTACTED,
            OpportunityStatus.ON_HOLD,
            OpportunityStatus.LOST,
            OpportunityStatus.REJECTED,
            OpportunityStatus.EXPIRED,
        ]
        for bad_status in invalid_statuses:
            bad_opp = Opportunity.objects.create(
                identifier=f"OPP-{bad_status}-{uuid.uuid4().hex[:6]}",
                direction=OpportunityDirection.SUPPLY,
                external_counterparty=self.external_cp,
                commodity=self.commodity,
                schema_version=self.schema_version,
                status=bad_status,
                created_by=self.operator_user,
            )
            with self.assertRaises(OfferStateError) as ctx:
                submit_operator_external_offer(
                    actor=self.operator_user,
                    rfq=self.published_rfq,
                    opportunity=bad_opp,
                    **self._get_valid_commercial_kwargs(),
                )
            self.assertIn("must be in Qualified status", str(ctx.exception))

    def test_internal_organization_opportunity_rejected(self):
        """Opportunity belonging to an internal platform organization cannot use external flow."""
        internal_opp = Opportunity.objects.create(
            identifier=f"OPP-INT-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )
        with self.assertRaises(OfferValidationError) as ctx:
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=internal_opp,
                **self._get_valid_commercial_kwargs(),
            )
        self.assertIn("must belong to an off-platform ExternalCounterparty", str(ctx.exception))

    def test_mismatched_caller_supplied_external_counterparty_rejected(self):
        """Caller cannot substitute an unrelated external counterparty ID."""
        other_cp = ExternalCounterparty.objects.create(
            company_name="Other External Ltd",
            phone="+1234567890",
        )
        with self.assertRaises(OfferValidationError) as ctx:
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                external_counterparty=other_cp,
                **self._get_valid_commercial_kwargs(),
            )
        self.assertIn("does not match the source Opportunity", str(ctx.exception))

    def test_opportunity_human_readable_identifier_lookup(self):
        """Can resolve source Opportunity using its human-readable identifier (OPP-...)."""
        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified.identifier,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertEqual(offer.source_opportunity_id, self.opp_external_qualified.id)

    # --- Fake Identity Proof (Zero Fake User/Org/Membership) ---

    def test_no_fake_identity_created_during_external_submission(self):
        """External submission strictly creates zero User, Organization, or Membership records."""
        users_before = User.objects.count()
        orgs_before = Organization.objects.count()
        memberships_before = OrganizationMembership.objects.count()

        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )

        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(Organization.objects.count(), orgs_before)
        self.assertEqual(OrganizationMembership.objects.count(), memberships_before)

    # --- Broker Provenance & Trust Isolation Tests ---

    def test_broker_referral_provenance_preserved_without_becoming_economic_party(self):
        """
        When opportunity originated from a Broker referral, the Broker attribution
        is preserved in Opportunity, but the Offer economic party is strictly the ExternalCounterparty.
        """
        brokered_opp = Opportunity.objects.create(
            identifier=f"OPP-BROKER-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )

        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=brokered_opp,
            **self._get_valid_commercial_kwargs(),
        )

        # Economic party is ExternalCounterparty, NOT the broker
        self.assertEqual(offer.external_counterparty_id, self.external_cp.id)
        self.assertIsNone(offer.offering_organization_id)
        self.assertEqual(offer.offeror_role, OfferorRole.SUPPLIER)

        # Provenance links back to the brokered opportunity
        self.assertEqual(offer.source_opportunity_id, brokered_opp.id)
        self.assertEqual(offer.source_opportunity.broker_id, self.broker_org.id)

    # --- RFQ Lifecycle & Deadline Integration Tests ---

    def test_first_external_submission_transitions_rfq_to_collecting_offers(self):
        """Submitting an external offer against a PUBLISHED RFQ transitions it to COLLECTING_OFFERS."""
        self.assertEqual(self.published_rfq.status, RFQStatus.PUBLISHED)

        submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)

    def test_external_submission_succeeds_on_collecting_offers_rfq(self):
        """Submitting an external offer against a COLLECTING_OFFERS RFQ succeeds."""
        self.published_rfq.status = RFQStatus.COLLECTING_OFFERS
        self.published_rfq.save(update_fields=["status"])

        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertEqual(version.status, OfferVersionStatus.SUBMITTED)

    def test_submission_rejected_on_terminal_rfq_states(self):
        """Draft, Closed, Cancelled, and Awarded RFQs strictly reject external offers."""
        for terminal_status in [RFQStatus.DRAFT, RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED]:
            rfq = RFQ.objects.create(
                organization=self.buyer_org,
                created_by=self.buyer_user,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("100.000"),
                unit="MT",
                status=terminal_status,
                visibility=RFQVisibility.PUBLIC,
            )
            with self.assertRaises(OfferStateError):
                submit_operator_external_offer(
                    actor=self.operator_user,
                    rfq=rfq,
                    opportunity=self.opp_external_qualified,
                    **self._get_valid_commercial_kwargs(),
                )

    def test_submission_deadline_strictly_enforced_no_late_override(self):
        """Even platform Operator/Admin is rejected if the RFQ submission deadline has passed."""
        self.published_rfq.submission_deadline = timezone.now() - timedelta(minutes=5)
        self.published_rfq.save(update_fields=["submission_deadline"])

        with self.assertRaises(OfferValidationError) as ctx:
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )
        self.assertIn("submission deadline has passed", str(ctx.exception))

    # --- Commodity Schema Lock & Commercial Validation Tests ---

    def test_schema_lock_strictly_uses_rfq_schema_version_not_active_v2(self):
        """
        When active commodity schema changes to v2, external submission strictly
        uses and revalidates against the RFQ's frozen schema v1.
        """
        # Publish active v2 schema with mandatory flash_point
        schema_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=schema_v2,
            key="penetration_grade",
            label_fa="درجه نفوذ",
            label_en="Penetration Grade",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=1,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=schema_v2,
            key="flash_point_mandatory_in_v2",
            label_fa="نقطه اشتعال",
            label_en="Flash Point Mandatory in v2",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
            sort_order=2,
        )
        publish_schema(schema_v2, activate=True)

        # Submit offer: does NOT contain flash_point_mandatory_in_v2, but matches RFQ schema v1
        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertEqual(version.schema_version_id, self.published_rfq.schema_version_id)
        self.assertEqual(version.schema_version.version, 1)

    def test_commercial_validation_rejections(self):
        """Revalidates positive quantity, price, unit compatibility, and delivery window."""
        kwargs = self._get_valid_commercial_kwargs()

        # Zero quantity
        with self.assertRaises(OfferValidationError):
            bad = kwargs.copy()
            bad["offered_quantity"] = Decimal("0.000")
            submit_operator_external_offer(
                actor=self.operator_user, rfq=self.published_rfq, opportunity=self.opp_external_qualified, **bad
            )

        # Incompatible unit
        with self.assertRaises(OfferValidationError):
            bad = kwargs.copy()
            bad["quantity_unit"] = "BARRELS"  # RFQ is in MT
            submit_operator_external_offer(
                actor=self.operator_user, rfq=self.published_rfq, opportunity=self.opp_external_qualified, **bad
            )

        # Negative price
        with self.assertRaises(OfferValidationError):
            bad = kwargs.copy()
            bad["unit_price"] = Decimal("-10.00")
            submit_operator_external_offer(
                actor=self.operator_user, rfq=self.published_rfq, opportunity=self.opp_external_qualified, **bad
            )

        # Inverted delivery window
        with self.assertRaises(OfferValidationError):
            bad = kwargs.copy()
            bad["delivery_start"] = date.today() + timedelta(days=20)
            bad["delivery_end"] = date.today() + timedelta(days=5)
            submit_operator_external_offer(
                actor=self.operator_user, rfq=self.published_rfq, opportunity=self.opp_external_qualified, **bad
            )

    # --- Thread Resolution & Existing Version Guard Tests ---

    def test_resubmission_on_existing_thread_with_submitted_version_conflicts_safely(self):
        """
        If current_submitted_version already exists on the thread, re-calling submission
        fails safely with OfferConflictError rather than overwriting or bypassing revision workflow.
        """
        offer1, v1 = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )
        self.assertEqual(v1.version_number, 1)

        # Second submission attempt against the same RFQ and ExternalCounterparty
        with self.assertRaises(OfferConflictError) as ctx:
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=self.opp_external_qualified,
                **self._get_valid_commercial_kwargs(),
            )
        self.assertIn("already been submitted", str(ctx.exception))
        self.assertIn("revision workflow", str(ctx.exception))

        # Confirm v1 was not modified or overwritten
        v1.refresh_from_db()
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v1.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(Offer.objects.filter(rfq=self.published_rfq).count(), 1)
        self.assertEqual(OfferVersion.objects.filter(offer=offer1).count(), 1)

    def test_reuses_existing_parent_offer_if_draft_was_not_yet_submitted(self):
        """
        If an Offer parent was created beforehand without a submitted version,
        submit_operator_external_offer reuses that parent instead of duplicating it.
        """
        existing_offer = create_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
        )
        self.assertIsNone(existing_offer.current_submitted_version)

        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **self._get_valid_commercial_kwargs(),
        )

        self.assertEqual(offer.id, existing_offer.id)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(offer.current_submitted_version_id, version.id)
        self.assertEqual(
            Offer.objects.filter(
                rfq=self.published_rfq, external_counterparty=self.external_cp
            ).count(),
            1,
        )

    # --- Child Cost Components Tests ---

    def test_cost_components_persisted_atomically_with_external_offer(self):
        """Child cost components are validated and persisted atomically with the submitted version."""
        kwargs = self._get_valid_commercial_kwargs()
        kwargs["logistics_cost_status"] = LogisticsCostStatus.KNOWN_SEPARATE
        kwargs["logistics_cost_amount"] = Decimal("35.00")
        kwargs["cost_components"] = [
            {
                "kind": CostComponentKind.LOGISTICS,
                "amount": Decimal("35.00"),
                "currency": "USD",
                "description": "Port handling and FOB barging",
            },
            {
                "kind": CostComponentKind.OTHER,
                "amount": Decimal("10.00"),
                "currency": "USD",
                "description": "SGS Quality Certification",
            },
        ]

        offer, version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=self.opp_external_qualified,
            **kwargs,
        )

        self.assertEqual(version.cost_components.count(), 2)
        logistics_comp = version.cost_components.filter(kind=CostComponentKind.LOGISTICS).first()
        self.assertEqual(logistics_comp.amount, Decimal("35.00"))
        self.assertEqual(logistics_comp.currency, "USD")

    # --- Executable T0611 Closure Proof ---

    def test_t0611_closure_proof_end_to_end(self):
        """
        Executable closure proof for deferred Epic 6 T0611 (Submit Offer from Opportunity):
        Broker Referral
        -> External Supplier Opportunity
        -> Qualified
        -> Operator external quote
        -> Submitted Offer
        """
        users_before = User.objects.count()
        orgs_before = Organization.objects.count()

        # 1. External Supplier Opportunity created via Broker referral
        opp = Opportunity.objects.create(
            identifier=f"OPP-T0611-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            quantity=Decimal("200.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )

        # 2. Operator enters quote against target RFQ on behalf of external counterparty
        offer, submitted_version = submit_operator_external_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            opportunity=opp,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("495.00"),
            currency="USD",
            payment_terms="100% CAD",
            delivery_terms="CIF Jebel Ali",
            incoterm="CIF",
            delivery_start=date.today() + timedelta(days=10),
            delivery_end=date.today() + timedelta(days=25),
            specifications={"penetration_grade": "60/70"},
            notes="T0611 verified external quote",
        )

        # 3. Verify all invariants
        self.assertEqual(offer.rfq_id, self.published_rfq.id)
        self.assertEqual(offer.external_counterparty_id, self.external_cp.id)
        self.assertIsNone(offer.offering_organization_id)
        self.assertEqual(offer.source_opportunity_id, opp.id)
        self.assertEqual(offer.offeror_role, OfferorRole.SUPPLIER)
        self.assertEqual(offer.created_by_id, self.operator_user.id)
        self.assertTrue(offer.entered_by_operator)

        self.assertEqual(submitted_version.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(submitted_version.submitted_by_id, self.operator_user.id)
        self.assertEqual(offer.current_submitted_version_id, submitted_version.id)

        # RFQ state moved to Collecting Offers
        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)

        # Zero fake identity created
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(Organization.objects.count(), orgs_before)


class OperatorExternalOfferTransactionRollbackTests(TransactionTestCase):
    """
    Tests proving transaction atomicity and rollback under failure.
    Uses TransactionTestCase against real PostgreSQL database.
    """

    def setUp(self):
        super().setUp()
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_rb_{uuid.uuid4().hex[:6]}",
            name_fa="قیر",
            name_en="Bitumen",
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

        self.buyer_org = Organization.objects.create(name=f"Buyer RB {uuid.uuid4().hex[:4]}", is_active=True)
        OrganizationCapability.objects.create(organization=self.buyer_org, capability=OrganizationCapability.CapabilityType.BUYER)
        self.buyer_user = User.objects.create_user(email=f"buyer_{uuid.uuid4().hex[:4]}@buyer.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.buyer_org, user=self.buyer_user, role=OrganizationMembership.OrganizationRole.MANAGER, is_active=True
        )

        self.published_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        self.external_cp = ExternalCounterparty.objects.create(
            company_name=f"External CP {uuid.uuid4().hex[:4]}",
            phone="+971500000000",
        )

        self.operator_user = User.objects.create_user(email=f"op_{uuid.uuid4().hex[:4]}@platform.internal", password="pw")
        SystemRoleAssignment.objects.create(user=self.operator_user, role=SystemRoleAssignment.SystemRole.OPERATOR)

        self.opp = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )

    def test_injected_failure_after_offer_creation_rolls_back_entire_transaction(self):
        """
        Inject a failure during draft creation / submission after the Offer parent is created.
        Proves rollback removes Offer, OfferVersion, and reverts RFQ status with zero orphan rows.
        """
        offers_before = Offer.objects.count()
        versions_before = OfferVersion.objects.count()

        # Invalidate specifications to trigger failure in validate_commodity_payload during version creation
        with self.assertRaises(OfferValidationError):
            submit_operator_external_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                opportunity=self.opp,
                offered_quantity=Decimal("100.000"),
                quantity_unit="MT",
                unit_price=Decimal("450.00"),
                specifications={"penetration_grade": 12345},  # Invalid type: expected string!
            )

        # Verify full transaction rollback: zero orphan Offer, zero orphan OfferVersion
        self.assertEqual(Offer.objects.count(), offers_before)
        self.assertEqual(OfferVersion.objects.count(), versions_before)

        # RFQ status was NOT transitioned
        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.PUBLISHED)

    def test_concurrent_same_party_external_submissions(self):
        """
        Two operators concurrently submit an external offer for the exact same RFQ
        and ExternalCounterparty. Exactly one succeeds, the other raises a controlled conflict.
        Zero duplicate Offer parent or duplicate version.
        """
        operator2 = User.objects.create_user(email=f"op2_{uuid.uuid4().hex[:4]}@platform.internal", password="pw")
        SystemRoleAssignment.objects.create(user=operator2, role=SystemRoleAssignment.SystemRole.OPERATOR)

        results = []
        errors = []

        def worker(op_user):
            connection.close()
            try:
                res = submit_operator_external_offer(
                    actor=op_user,
                    rfq=self.published_rfq.id,
                    opportunity=self.opp.id,
                    offered_quantity=Decimal("100.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("450.00"),
                    specifications={"penetration_grade": "60/70"},
                )
                results.append(res)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=(self.operator_user,))
        t2 = threading.Thread(target=worker, args=(operator2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one thread succeeds, the other gets OfferConflictError
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], OfferConflictError)

        # DB integrity: exactly one Offer and exactly one OfferVersion exist
        self.assertEqual(
            Offer.objects.filter(rfq=self.published_rfq, external_counterparty=self.external_cp).count(),
            1,
        )
        self.assertEqual(OfferVersion.objects.filter(offer__rfq=self.published_rfq).count(), 1)
