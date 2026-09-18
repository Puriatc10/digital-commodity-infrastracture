from datetime import timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from offers.enums import OfferorRole
from offers.exceptions import (
    OfferConflictError,
    OfferPermissionDeniedError,
    OfferStateError,
    OfferValidationError,
)
from offers.services import create_offer
from offers.tests.base import BaseOffersTestCase
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationMembership,
)
from trade_hub.models import RFQStatus, RFQVisibility

User = get_user_model()


class OfferCreationServiceTests(BaseOffersTestCase):
    """
    Unit & integration tests for the authoritative create_offer domain service (T0801).
    Validates capability rules, external provenance, system role authorization,
    anti-spoofing, RFQ lifecycle integrity, and no-fake-identity guarantees.
    """

    # --- Capability Tests ---

    def test_supplier_role_with_supplier_capability_passes(self):
        """Supplier role + Supplier capability succeeds."""
        offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.offeror_role, OfferorRole.SUPPLIER)
        self.assertEqual(offer.offering_organization, self.supplier_org)

    def test_supplier_role_with_broker_only_fails(self):
        """Supplier role with broker-only organization is rejected."""
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.broker_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.broker_org,
            )
        self.assertIn("lacks required Supplier capability", str(ctx.exception))

    def test_broker_role_with_broker_capability_passes(self):
        """Broker role + Broker capability succeeds."""
        offer = create_offer(
            actor=self.broker_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.offeror_role, OfferorRole.BROKER)
        self.assertEqual(offer.offering_organization, self.broker_org)

    def test_broker_role_with_supplier_only_fails(self):
        """Broker role with supplier-only organization is rejected."""
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.BROKER,
                offering_organization=self.supplier_org,
            )
        self.assertIn("lacks required Broker capability", str(ctx.exception))

    def test_multi_capability_organization_both_roles_valid(self):
        """Multi-capability organization can explicitly create offers in either role."""
        offer_sup = create_offer(
            actor=self.multi_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.multi_org,
        )
        self.assertEqual(offer_sup.offeror_role, OfferorRole.SUPPLIER)

        offer_brk = create_offer(
            actor=self.multi_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.multi_org,
        )
        self.assertEqual(offer_brk.offeror_role, OfferorRole.BROKER)

    # --- External Provenance Tests ---

    def test_external_offer_qualified_supply_same_counterparty_passes(self):
        """Qualified Supply Opportunity with matching ExternalCounterparty succeeds."""
        offer = create_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
        )
        self.assertIsNotNone(offer.id)
        self.assertEqual(offer.external_counterparty, self.external_cp)
        self.assertEqual(offer.source_opportunity, self.opp_external_qualified)

    def test_external_offer_missing_source_opportunity_rejected(self):
        """External counterparty offer without source_opportunity is rejected."""
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=None,
            )
        self.assertIn("requires a source Opportunity", str(ctx.exception))

    def test_external_offer_demand_opportunity_rejected(self):
        """Demand opportunity cannot be used as provenance for an external supply offer."""
        opp_demand = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=opp_demand,
            )
        self.assertIn("SUPPLY", str(ctx.exception))

    def test_external_offer_non_qualified_supply_opportunity_rejected(self):
        """Non-Qualified supply opportunity is rejected."""
        for non_qual_status in [
            OpportunityStatus.CAPTURED,
            OpportunityStatus.CONTACTED,
            OpportunityStatus.MATCHING,
            OpportunityStatus.ON_HOLD,
            OpportunityStatus.REJECTED,
            OpportunityStatus.LOST,
            OpportunityStatus.EXPIRED,
        ]:
            opp = Opportunity.objects.create(
                identifier=f"OPP-{uuid.uuid4().hex[:6]}",
                direction=OpportunityDirection.SUPPLY,
                external_counterparty=self.external_cp,
                commodity=self.commodity,
                schema_version=self.schema_version,
                quantity=Decimal("300.000"),
                unit="MT",
                status=non_qual_status,
                created_by=self.operator_user,
            )
            with self.assertRaises(OfferStateError) as ctx:
                create_offer(
                    actor=self.operator_user,
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    external_counterparty=self.external_cp,
                    source_opportunity=opp,
                )
            self.assertIn("Qualified", str(ctx.exception))

    def test_external_offer_different_counterparty_rejected(self):
        """Opportunity for a different counterparty cannot be used."""
        other_cp = ExternalCounterparty.objects.create(
            company_name="Different Off-Platform Supplier Ltd",
        )
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.operator_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=other_cp,
                source_opportunity=self.opp_external_qualified,
            )
        self.assertIn("external counterparty does not match", str(ctx.exception))

    # --- Authorization Tests ---

    def test_operator_can_create_external_offer(self):
        """Operator (via SystemRoleAssignment) can create external offer."""
        offer = create_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
        )
        self.assertIsNotNone(offer.id)

    def test_product_admin_can_create_external_offer(self):
        """Product Admin (via SystemRoleAssignment) can create external offer."""
        offer = create_offer(
            actor=self.admin_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.BROKER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
        )
        self.assertIsNotNone(offer.id)

    def test_buyer_cannot_create_external_offer(self):
        """Buyer member without system role cannot create external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=self.buyer_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    def test_supplier_cannot_create_external_offer(self):
        """Supplier member without system role cannot create external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    def test_broker_cannot_create_external_offer(self):
        """Broker member without system role cannot create external offer."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=self.broker_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.BROKER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    def test_django_staff_only_cannot_create_external_offer(self):
        """Django is_staff alone does NOT grant product operator authority."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=self.staff_only_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    def test_django_superuser_only_cannot_create_external_offer(self):
        """Django is_superuser alone does NOT grant product admin authority."""
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=self.superuser_only_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    def test_anonymous_user_cannot_create_offer(self):
        """Anonymous caller cannot create internal or external offer."""
        anon = AnonymousUser()
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=anon,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=anon,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                external_counterparty=self.external_cp,
                source_opportunity=self.opp_external_qualified,
            )

    # --- Internal Organization Membership Role Tests ---

    def test_internal_membership_roles(self):
        """Owner, Manager, Member can create offers; Viewer is rejected."""
        user_owner = User.objects.create_user(email="owner@test.com")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=user_owner,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        user_member = User.objects.create_user(email="member@test.com")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=user_member,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        user_viewer = User.objects.create_user(email="viewer@test.com")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=user_viewer,
            role=OrganizationMembership.OrganizationRole.VIEWER,
            is_active=True,
        )

        user_inactive = User.objects.create_user(email="inactive@test.com")
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=user_inactive,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=False,
        )

        user_non_member = User.objects.create_user(email="outsider@test.com")

        # Owner -> PASS
        offer = create_offer(
            actor=user_owner,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.assertIsNotNone(offer)
        offer.delete()

        # Member -> PASS
        offer = create_offer(
            actor=user_member,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.assertIsNotNone(offer)
        offer.delete()

        # Viewer -> REJECT
        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            create_offer(
                actor=user_viewer,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )
        self.assertIn("Viewer", str(ctx.exception))

        # Inactive membership -> REJECT
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=user_inactive,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )

        # Non-member -> REJECT
        with self.assertRaises(OfferPermissionDeniedError):
            create_offer(
                actor=user_non_member,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )

    # --- Target RFQ Lifecycle & State Tests ---

    def test_rfq_collecting_offers_status_passes(self):
        """Offer creation is allowed when RFQ is in Collecting Offers status."""
        self.published_rfq.status = RFQStatus.COLLECTING_OFFERS
        self.published_rfq.save()

        offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.assertIsNotNone(offer.id)

    def test_rfq_draft_closed_cancelled_awarded_rejected(self):
        """Offer creation is rejected if RFQ is not in Published or Collecting Offers."""
        for forbidden_status in [
            RFQStatus.DRAFT,
            RFQStatus.CLOSED,
            RFQStatus.CANCELLED,
            RFQStatus.AWARDED,
        ]:
            self.published_rfq.status = forbidden_status
            self.published_rfq.save()

            with self.assertRaises(OfferStateError) as ctx:
                create_offer(
                    actor=self.supplier_user,
                    rfq=self.published_rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=self.supplier_org,
                )
            self.assertIn("cannot accept offers", str(ctx.exception))

    def test_rfq_submission_deadline_passed_rejected(self):
        """Offer creation is rejected when the RFQ submission deadline has passed."""
        self.published_rfq.submission_deadline = timezone.now() - timedelta(minutes=5)
        self.published_rfq.save()

        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )
        self.assertIn("deadline has passed", str(ctx.exception))

    def test_buyer_cannot_offer_on_own_rfq(self):
        """Owning buyer organization cannot create an offer against its own RFQ."""
        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.buyer_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.buyer_org,
            )
        self.assertIn("Owning buyer organization cannot create an offer", str(ctx.exception))

    def test_private_rfq_without_invitation_rejected(self):
        """Private RFQ cannot receive offers from uninvited organizations."""
        self.published_rfq.visibility = RFQVisibility.PRIVATE
        self.published_rfq.save()

        with self.assertRaises(OfferPermissionDeniedError) as ctx:
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )
        self.assertIn("not visible or accessible", str(ctx.exception))

    # --- No RFQ Lifecycle Mutation ---

    def test_offer_creation_does_not_mutate_rfq_status(self):
        """Creating an Offer parent must NOT advance RFQ from Published to Collecting Offers."""
        self.assertEqual(self.published_rfq.status, RFQStatus.PUBLISHED)

        create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        self.published_rfq.refresh_from_db()
        self.assertEqual(self.published_rfq.status, RFQStatus.PUBLISHED)

    # --- Actor Spoofing Prevention ---

    def test_actor_spoofing_prevented(self):
        """created_by is always derived from actor context; client spoofing attempts fail."""
        rogue_user = User.objects.create_user(email="rogue@attacker.com")

        offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            created_by=rogue_user,
            entered_by=rogue_user,
            operator_user=rogue_user,
        )
        self.assertEqual(offer.created_by, self.supplier_user)
        self.assertNotEqual(offer.created_by, rogue_user)

    # --- No Fake Identity Creation ---

    def test_external_offer_creates_no_fake_identities(self):
        """External counterparty offer creation creates no User, Organization, or Membership rows."""
        user_count_before = User.objects.count()
        org_count_before = Organization.objects.count()
        membership_count_before = OrganizationMembership.objects.count()

        create_offer(
            actor=self.operator_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            external_counterparty=self.external_cp,
            source_opportunity=self.opp_external_qualified,
        )

        self.assertEqual(User.objects.count(), user_count_before)
        self.assertEqual(Organization.objects.count(), org_count_before)
        self.assertEqual(OrganizationMembership.objects.count(), membership_count_before)

    # --- Internal Source Opportunity (Optional) ---

    def test_internal_source_opportunity_optional_valid(self):
        """Internal organization offer can reference an optional supply opportunity."""
        opp_internal = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )

        offer = create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
            source_opportunity=opp_internal,
        )
        self.assertEqual(offer.source_opportunity, opp_internal)

    def test_internal_source_opportunity_wrong_org_rejected(self):
        """Internal offer cannot reference an opportunity belonging to another organization."""
        opp_other_org = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            organization=self.broker_org,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("300.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator_user,
        )

        with self.assertRaises(OfferValidationError) as ctx:
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
                source_opportunity=opp_other_org,
            )
        self.assertIn("does not match the offering organization", str(ctx.exception))

    def test_duplicate_offer_raises_controlled_conflict_error(self):
        """Subsequent creation of duplicate thread raises OfferConflictError."""
        create_offer(
            actor=self.supplier_user,
            rfq=self.published_rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

        with self.assertRaises(OfferConflictError):
            create_offer(
                actor=self.supplier_user,
                rfq=self.published_rfq,
                offeror_role=OfferorRole.SUPPLIER,
                offering_organization=self.supplier_org,
            )
