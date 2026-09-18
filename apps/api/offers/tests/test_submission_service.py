from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, PropertyMock
import uuid

from django.core.exceptions import ValidationError
from django.utils import timezone

from commodities.models import (
    CommodityAttributeDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from offers.enums import LogisticsCostStatus, OfferorRole, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
    StaleVersionError,
)
from offers.models import Offer, OfferCostComponent, OfferVersion
from offers.services.creation import create_offer
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from offers.tests.base import BaseOffersTestCase, User
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationCommodity,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQInvitation, RFQInvitationStatus, RFQStatus, RFQVisibility


class OfferSubmissionServiceTests(BaseOffersTestCase):
    """Comprehensive service-level unit tests for T0803 Supplier/Broker Offer Submission."""

    def setUp(self):
        super().setUp()
        # Create standard internal Supplier Offer and Draft Version
        self.supplier_offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.draft_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("450.00"),
            currency="USD",
            payment_terms="LC at sight",
            delivery_terms="CIF Bandar Abbas",
            incoterm="CIF",
            delivery_start=timezone.now().date() + timedelta(days=10),
            delivery_end=timezone.now().date() + timedelta(days=20),
            valid_until=timezone.now() + timedelta(days=30),
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("25.00"),
            specifications={"penetration_grade": "60/70"},
            notes="Standard initial commercial offer",
        )
        self.supplier_offer.refresh_from_db()


    # -------------------------------------------------------------------------
    # 1. Membership & Role Authorization Tests
    # -------------------------------------------------------------------------

    def test_owner_can_submit(self):
        """Organization Owner can submit draft offer version."""
        owner_user = User.objects.create_user(email="owner@petrocorp.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=owner_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        submitted = submit_internal_offer_version(actor=owner_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(submitted.submitted_by, owner_user)

    def test_manager_can_submit(self):
        """Organization Manager can submit draft offer version."""
        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(submitted.submitted_by, self.supplier_user)

    def test_member_can_submit(self):
        """Organization Member can submit draft offer version."""
        member_user = User.objects.create_user(email="member@petrocorp.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=member_user,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )
        submitted = submit_internal_offer_version(actor=member_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(submitted.submitted_by, member_user)

    def test_viewer_is_denied_read_only(self):
        """Organization Viewer has read-only access and cannot submit."""
        viewer_user = User.objects.create_user(email="viewer@petrocorp.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=viewer_user,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )
        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            submit_internal_offer_version(actor=viewer_user, offer_version=self.draft_v1)
        self.assertIn("Viewers have read-only access", str(ctx.exception))

    def test_inactive_membership_is_denied(self):
        """Inactive membership cannot submit."""
        inactive_user = User.objects.create_user(email="inactive@petrocorp.com", password="pw")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=inactive_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=False,
        )
        with self.assertRaises(OfferPermissionDeniedError):
            submit_internal_offer_version(actor=inactive_user, offer_version=self.draft_v1)

    def test_non_member_is_denied(self):
        """User with no membership in the offering organization is denied."""
        outsider = User.objects.create_user(email="outsider@random.com", password="pw")
        with self.assertRaises(OfferPermissionDeniedError):
            submit_internal_offer_version(actor=outsider, offer_version=self.draft_v1)

    def test_member_of_different_organization_is_denied(self):
        """Member of a competitor or different organization cannot submit."""
        competitor_user = User.objects.create_user(email="comp@competitor.com", password="pw")
        competitor_org = Organization.objects.create(name="Competitor Corp", country="AE", is_active=True)
        OrganizationCapability.objects.create(
            organization=competitor_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationMembership.objects.create(
            organization=competitor_org,
            user=competitor_user,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        with self.assertRaises(OfferPermissionDeniedError):
            submit_internal_offer_version(actor=competitor_user, offer_version=self.draft_v1)

    # -------------------------------------------------------------------------
    # 2. Capability Revalidation at Action Time Tests
    # -------------------------------------------------------------------------

    def test_supplier_capability_revalidated_at_submit(self):
        """Revoking Supplier capability after Draft creation rejects submission."""
        # Revoke capability
        OrganizationCapability.objects.filter(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        ).delete()

        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertIn("lacks required Supplier capability", str(ctx.exception))

    def test_broker_capability_revalidated_at_submit(self):
        """Revoking Broker capability after Draft creation rejects submission."""
        broker_offer = create_offer(
            actor=self.broker_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        broker_draft = create_draft_offer_version(
            actor=self.broker_user,
            offer=broker_offer,
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("410.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        # Revoke Broker capability
        OrganizationCapability.objects.filter(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        ).delete()

        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.broker_user, offer_version=broker_draft)
        self.assertIn("lacks required Broker capability", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. RFQ Participation & Visibility Tests (Private, Network, Public)
    # -------------------------------------------------------------------------

    def test_private_rfq_invited_organization_can_submit(self):
        """For Private RFQ, invited organization can submit offer."""
        private_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PRIVATE,
        )
        # Invite supplier_org
        RFQInvitation.objects.create(
            rfq=private_rfq,
            organization=self.supplier_org,
            status=RFQInvitationStatus.INVITED,
        )

        offer = create_offer(
            actor=self.supplier_user,
            rfq=private_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        draft = create_draft_offer_version(
            actor=self.supplier_user,
            offer=offer,
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("440.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=draft)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

        # Verify invitation transitioned to RESPONDED
        invitation = RFQInvitation.objects.get(rfq=private_rfq, organization=self.supplier_org)
        self.assertEqual(invitation.status, RFQInvitationStatus.RESPONDED)
        self.assertIsNotNone(invitation.responded_at)

    def test_private_rfq_uninvited_organization_rejected(self):
        """For Private RFQ, uninvited organization cannot submit."""
        private_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PRIVATE,
        )
        # Manually create offer without invitation
        offer = Offer.objects.create(
            rfq=private_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        draft = OfferVersion.objects.create(
            offer=offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("440.00"),
            currency="USD",
            created_by=self.supplier_user,
        )
        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            submit_internal_offer_version(actor=self.supplier_user, offer_version=draft)
        self.assertIn("not visible or accessible", str(ctx.exception))

    def test_private_rfq_declined_invitation_rejected(self):
        """Organization that declined private RFQ invitation cannot submit."""
        private_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PRIVATE,
        )
        RFQInvitation.objects.create(
            rfq=private_rfq,
            organization=self.supplier_org,
            status=RFQInvitationStatus.DECLINED,
            declined_at=timezone.now(),
        )
        offer = Offer.objects.create(
            rfq=private_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        draft = OfferVersion.objects.create(
            offer=offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("440.00"),
            currency="USD",
            created_by=self.supplier_user,
        )
        with self.assertRaises(OfferPermissionDeniedError):
            submit_internal_offer_version(actor=self.supplier_user, offer_version=draft)

    def test_network_rfq_requires_matching_commodity(self):
        """Network RFQ requires matching OrganizationCommodity at submit time."""
        network_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.NETWORK,
        )
        # Without OrganizationCommodity
        offer = Offer.objects.create(
            rfq=network_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=self.supplier_user,
        )
        draft = OfferVersion.objects.create(
            offer=offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("200.000"),
            quantity_unit="MT",
            unit_price=Decimal("440.00"),
            currency="USD",
            created_by=self.supplier_user,
        )
        with self.assertRaises(OfferPermissionDeniedError):
            submit_internal_offer_version(actor=self.supplier_user, offer_version=draft)

        # Associate commodity
        OrganizationCommodity.objects.create(
            organization=self.supplier_org,
            commodity=self.commodity,
        )
        # Now submit succeeds
        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=draft)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

    def test_owning_buyer_cannot_submit_offer_to_own_rfq(self):
        """Buyer Organization cannot submit an offer to its own RFQ."""
        # Force create an offer row owned by buyer_org
        offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.buyer_org,
            created_by=self.buyer_user,
        )
        draft = OfferVersion.objects.create(
            offer=offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("100.000"),
            quantity_unit="MT",
            unit_price=Decimal("400.00"),
            currency="USD",
            created_by=self.buyer_user,
        )
        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.buyer_user, offer_version=draft)
        self.assertIn("cannot submit an offer for its own RFQ", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4. RFQ Lifecycle Transitions & Restrictions Tests
    # -------------------------------------------------------------------------

    def test_submit_published_rfq_transitions_to_collecting_offers(self):
        """First successful submit against Published RFQ transitions RFQ to Collecting Offers."""
        self.assertEqual(self.published_rfq.status, RFQStatus.PUBLISHED)
        initial_rfq_version = self.published_rfq.version

        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)
        self.assertEqual(self.published_rfq.version, initial_rfq_version + 1)

    def test_submit_collecting_offers_rfq_remains_collecting_offers(self):
        """Submission against an RFQ already in Collecting Offers leaves RFQ in Collecting Offers."""
        self.published_rfq.status = RFQStatus.COLLECTING_OFFERS
        self.published_rfq.save(update_fields=["status"])
        rfq_version_before = self.published_rfq.version

        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.COLLECTING_OFFERS)
        # Version does not advance if already COLLECTING_OFFERS
        self.assertEqual(self.published_rfq.version, rfq_version_before)

    def test_submit_rejected_on_terminal_or_draft_rfq(self):
        """Offers cannot be submitted against Draft, Closed, Cancelled, or Awarded RFQs."""
        for disallowed_status in [RFQStatus.DRAFT, RFQStatus.CLOSED, RFQStatus.CANCELLED, RFQStatus.AWARDED]:
            with self.subTest(status=disallowed_status):
                self.published_rfq.status = disallowed_status
                self.published_rfq.save(update_fields=["status"])

                with self.assertRaises(OfferStateError) as ctx:
                    submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
                self.assertIn("Offers can only be submitted against Published or Collecting Offers RFQs.", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 5. Deadline Tests
    # -------------------------------------------------------------------------

    def test_submit_before_deadline_succeeds(self):
        """Submission before submission deadline succeeds."""
        self.published_rfq.submission_deadline = timezone.now() + timedelta(days=2)
        self.published_rfq.save(update_fields=["submission_deadline"])

        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)

    def test_submit_past_deadline_rejected(self):
        """Submission after deadline is rejected."""
        self.published_rfq.submission_deadline = timezone.now() - timedelta(minutes=5)
        self.published_rfq.save(update_fields=["submission_deadline"])

        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertIn("deadline has passed", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 6. Optimistic Concurrency Tests
    # -------------------------------------------------------------------------

    def test_submit_with_correct_expected_version_succeeds(self):
        """Submitting with expected_version equal to Offer aggregate_version succeeds."""
        current_agg_version = self.supplier_offer.aggregate_version
        submitted = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.draft_v1,
            expected_version=current_agg_version,
            require_expected_version=True,
        )
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.supplier_offer.refresh_from_db()
        self.assertEqual(self.supplier_offer.aggregate_version, current_agg_version + 1)
        self.assertEqual(self.supplier_offer.current_submitted_version_id, submitted.id)

    def test_submit_with_stale_expected_version_raises_stale_version_error(self):
        """Submitting with stale expected_version raises StaleVersionError."""
        current_agg_version = self.supplier_offer.aggregate_version
        with self.assertRaises(StaleVersionError):
            submit_internal_offer_version(
                actor=self.supplier_user,
                offer_version=self.draft_v1,
                expected_version=current_agg_version + 5,
                require_expected_version=True,
            )

    def test_submit_with_missing_expected_version_when_required(self):
        """Missing expected_version when required raises InvalidVersionError."""
        with self.assertRaises(InvalidVersionError):
            submit_internal_offer_version(
                actor=self.supplier_user,
                offer_version=self.draft_v1,
                expected_version=None,
                require_expected_version=True,
            )

    def test_submit_with_invalid_expected_version(self):
        """Malformed or negative expected_version raises InvalidVersionError."""
        for invalid_val in [0, -1, "three", True]:
            with self.subTest(val=invalid_val):
                with self.assertRaises(InvalidVersionError):
                    submit_internal_offer_version(
                        actor=self.supplier_user,
                        offer_version=self.draft_v1,
                        expected_version=invalid_val,
                    )

    # -------------------------------------------------------------------------
    # 7. Exact Schema Lock & Revalidation Tests
    # -------------------------------------------------------------------------

    def test_submit_revalidates_against_rfq_schema_not_active_schema(self):
        """
        When active commodity schema changes (e.g. v2 published with new mandatory fields),
        Offer submission strictly revalidates against the RFQ's schema (v1), NOT active v2!
        """
        # Create Schema Version 2 with an extra required field
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
            data_type=CommodityAttributeDefinition.DataType.NUMBER,
            is_required=True,
            sort_order=2,
        )
        publish_schema(schema_v2, activate=True)

        # draft_v1 does NOT have 'flash_point_mandatory_in_v2'
        # But RFQ was created under v1!
        # Submission MUST succeed because it validates against RFQ schema v1.
        submitted = submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertEqual(submitted.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(submitted.schema_version_id, self.published_rfq.schema_version_id)

    def test_revalidate_positive_quantity_at_submit(self):
        """Non-positive quantity at submit time fails."""
        with patch.object(OfferVersion, "offered_quantity", new_callable=PropertyMock, return_value=Decimal("0.000")):
            with self.assertRaises(OfferValidationError) as ctx:
                submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
            self.assertIn("quantity must be positive", str(ctx.exception))

    def test_revalidate_unit_compatibility_at_submit(self):
        """Incompatible unit at submit time fails."""
        OfferVersion.objects.filter(pk=self.draft_v1.pk).update(quantity_unit="BARRELS")
        self.draft_v1.refresh_from_db()

        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
        self.assertIn("incompatible with RFQ unit", str(ctx.exception))

    def test_revalidate_positive_price_at_submit(self):
        """Non-positive price at submit time fails."""
        with patch.object(OfferVersion, "unit_price", new_callable=PropertyMock, return_value=Decimal("-10.00")):
            with self.assertRaises(OfferValidationError) as ctx:
                submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
            self.assertIn("price must be positive", str(ctx.exception))

    def test_revalidate_logistics_consistency_at_submit(self):
        """Inconsistent logistics cost at submit time fails."""
        with patch.object(OfferVersion, "logistics_cost_status", new_callable=PropertyMock, return_value=LogisticsCostStatus.INCLUDED_IN_PRICE), \
             patch.object(OfferVersion, "logistics_cost_amount", new_callable=PropertyMock, return_value=Decimal("50.00")):
            with self.assertRaises(OfferValidationError) as ctx:
                submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
            self.assertIn("must be absent", str(ctx.exception))

    def test_revalidate_cost_components_consistency_at_submit(self):
        """Mismatched cost component currency at submit time fails."""
        OfferCostComponent.objects.create(
            offer_version=self.draft_v1,
            kind="LOGISTICS",
            amount=Decimal("15.00"),
            currency="USD",
            description="Freight fee",
        )
        with patch.object(OfferCostComponent, "currency", new_callable=PropertyMock, return_value="EUR"):
            with self.assertRaises(OfferValidationError) as ctx:
                submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)
            self.assertIn("must match OfferVersion currency", str(ctx.exception))


    # -------------------------------------------------------------------------
    # 8. Failure Atomicity Tests
    # -------------------------------------------------------------------------

    def test_failure_atomicity_rolls_back_draft_and_rfq(self):
        """
        If a failure occurs during submission before commit, Draft remains DRAFT,
        current_submitted_version remains None, aggregate_version is unchanged,
        and RFQ remains Published!
        """
        initial_rfq_status = self.published_rfq.status
        initial_rfq_version = self.published_rfq.version
        initial_agg_version = self.supplier_offer.aggregate_version

        # Inject an exception during RFQ transition
        with patch(
            "trade_hub.services.rfq_lifecycle.RFQLifecycleService.start_collecting_offers",
            side_effect=RuntimeError("Simulated database failure during RFQ transition"),
        ):
            with self.assertRaises(RuntimeError):
                submit_internal_offer_version(actor=self.supplier_user, offer_version=self.draft_v1)

        # Verify full rollback
        self.draft_v1.refresh_from_db()
        self.assertEqual(self.draft_v1.status, OfferVersionStatus.DRAFT)
        self.assertIsNone(self.draft_v1.submitted_at)
        self.assertIsNone(self.draft_v1.submitted_by)

        self.supplier_offer.refresh_from_db()
        self.assertIsNone(self.supplier_offer.current_submitted_version_id)
        self.assertEqual(self.supplier_offer.aggregate_version, initial_agg_version)

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, initial_rfq_status)
        self.assertEqual(self.published_rfq.version, initial_rfq_version)

    # -------------------------------------------------------------------------
    # 9. External Counterparty Guard Tests
    # -------------------------------------------------------------------------

    def test_external_counterparty_offer_rejected_on_internal_flow(self):
        """Attempting to submit an external counterparty offer via internal flow is rejected."""
        ext_offer = Offer.objects.create(
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
            created_by=self.operator_user,
        )
        ext_draft = OfferVersion.objects.create(
            offer=ext_offer,
            version_number=1,
            status=OfferVersionStatus.DRAFT,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("420.00"),
            currency="USD",
            created_by=self.operator_user,
        )
        with self.assertRaises(OfferValidationError) as ctx:
            submit_internal_offer_version(actor=self.supplier_user, offer_version=ext_draft)
        self.assertIn("External counterparty offers cannot be submitted", str(ctx.exception))
