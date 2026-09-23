from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model

from deals.exceptions import (
    AwardNotFinalizedError,
    DealPermissionDeniedError,
    DealSourceIntegrityError,
    StaleVersionError,
)
from deals.models import Deal
from deals.services import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase
from offers.services import add_award_allocation, create_draft_award
from organizations.models import Organization, OrganizationMembership
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class DealMaterializationServiceTests(BaseDealsTestCase):
    """Domain tests for materialize_deals_from_award service."""

    def test_single_allocation_creates_exactly_one_deal(self):
        """Finalized Award with 1 allocation materializes into exactly 1 Deal."""
        award, alloc = self.create_and_finalize_single_award()

        deals, newly_created = materialize_deals_from_award(
            award.id,
            actor=self.buyer_owner,
        )

        self.assertTrue(newly_created)
        self.assertEqual(len(deals), 1)
        deal = deals[0]
        self.assertEqual(deal.award, award)
        self.assertEqual(deal.award_allocation, alloc)
        self.assertEqual(deal.rfq, self.rfq)
        self.assertEqual(deal.offer, self.supplier_offer)
        self.assertEqual(deal.offer_version, self.supplier_v1)
        self.assertEqual(deal.buyer_organization, self.buyer_org)
        self.assertEqual(deal.seller_organization, self.supplier_org)
        self.assertIsNone(deal.seller_external_counterparty)

    def test_multi_award_creates_n_separate_deals(self):
        """Multi-Award with N allocations creates N separate Deals, never one multi-seller Deal."""
        award, allocs = self.create_and_finalize_multi_award()
        self.assertEqual(len(allocs), 3)

        deals, newly_created = materialize_deals_from_award(
            award.id,
            actor=self.buyer_owner,
        )

        self.assertTrue(newly_created)
        self.assertEqual(len(deals), 3)
        self.assertEqual(Deal.objects.filter(award=award).count(), 3)

        # Assert each deal is bound to exactly one unique allocation and has one counterparty
        deal_alloc_ids = [d.award_allocation_id for d in deals]
        self.assertEqual(len(set(deal_alloc_ids)), 3)

        # Deal 1: Supplier Org
        deal1 = next(d for d in deals if d.award_allocation_id == allocs[0].id)
        self.assertEqual(deal1.seller_organization, self.supplier_org)
        self.assertIsNone(deal1.seller_external_counterparty)

        # Deal 2: Broker Org
        deal2 = next(d for d in deals if d.award_allocation_id == allocs[1].id)
        self.assertEqual(deal2.seller_organization, self.broker_org)
        self.assertIsNone(deal2.seller_external_counterparty)

        # Deal 3: External Counterparty
        deal3 = next(d for d in deals if d.award_allocation_id == allocs[2].id)
        self.assertIsNone(deal3.seller_organization)
        self.assertEqual(deal3.seller_external_counterparty, self.ext_counterparty)

    def test_repeat_materialization_is_idempotent(self):
        """Calling materialization twice returns identical Deal set with no duplicates created."""
        award, allocs = self.create_and_finalize_multi_award()

        deals1, created1 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertTrue(created1)
        self.assertEqual(len(deals1), 3)

        deals2, created2 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertFalse(created2)
        self.assertEqual(len(deals2), 3)

        self.assertEqual([d.id for d in deals1], [d.id for d in deals2])
        self.assertEqual(Deal.objects.filter(award=award).count(), 3)

    def test_draft_award_rejected(self):
        """DRAFT Award cannot be materialized into deals; raises AwardNotFinalizedError."""
        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            draft_award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )

        with self.assertRaises(AwardNotFinalizedError):
            materialize_deals_from_award(draft_award.id, actor=self.buyer_owner)

        self.assertEqual(Deal.objects.filter(award=draft_award).count(), 0)

    def test_foreign_award_rejected(self):
        """Actor from another Buyer organization cannot materialize award deals."""
        award, _ = self.create_and_finalize_single_award()

        with self.assertRaises(DealPermissionDeniedError):
            materialize_deals_from_award(award.id, actor=self.foreign_buyer_user)

    def test_viewer_denied_materialization(self):
        """Buyer VIEWER is read-only and cannot materialize deals."""
        award, _ = self.create_and_finalize_single_award()

        with self.assertRaises(DealPermissionDeniedError):
            materialize_deals_from_award(award.id, actor=self.buyer_viewer)

    def test_seller_actors_denied_materialization(self):
        """Seller-side Supplier and Broker cannot materialize Buyer's Award."""
        award, _ = self.create_and_finalize_single_award()

        with self.assertRaises(DealPermissionDeniedError):
            materialize_deals_from_award(award.id, actor=self.supplier_user)

        with self.assertRaises(DealPermissionDeniedError):
            materialize_deals_from_award(award.id, actor=self.broker_user)

    def test_buyer_roles_and_platform_roles_authorized(self):
        """Buyer Owner, Manager, Member, and Platform Operator/Admin can materialize."""
        award, _ = self.create_and_finalize_single_award()

        # Buyer Manager
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_manager)
        self.assertEqual(len(deals), 1)

        # Buyer Member
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_member)
        self.assertEqual(len(deals), 1)

        # Platform Operator
        deals, _ = materialize_deals_from_award(award.id, actor=self.operator_user)
        self.assertEqual(len(deals), 1)

        # Platform Admin
        deals, _ = materialize_deals_from_award(award.id, actor=self.admin_user)
        self.assertEqual(len(deals), 1)

    def test_staff_superuser_without_system_role_denied(self):
        """Django staff/superuser without SystemRoleAssignment has no product authority."""
        award, _ = self.create_and_finalize_single_award()

        with self.assertRaises(DealPermissionDeniedError):
            materialize_deals_from_award(award.id, actor=self.staff_only_user)

    def test_buyer_derivation_from_rfq_organization(self):
        """Buyer is always derived strictly from RFQ owning Organization, never requester."""
        award, _ = self.create_and_finalize_single_award()

        # Materialize using Platform Operator
        deals, _ = materialize_deals_from_award(award.id, actor=self.operator_user)

        # Buyer organization must be RFQ owning Organization, NOT Operator's context
        self.assertEqual(deals[0].buyer_organization, self.rfq.organization)

    def test_seller_derivation_broker_not_reclassified(self):
        """Broker offer seller is Broker Organization; role is not reclassified."""
        award, allocs = self.create_and_finalize_multi_award()

        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)

        broker_deal = next(d for d in deals if d.award_allocation_id == allocs[1].id)
        self.assertEqual(broker_deal.seller_organization, self.broker_org)
        self.assertEqual(broker_deal.offer.offeror_role, "BROKER")

    def test_external_identity_regression_zero_delta(self):
        """ExternalCounterparty deal creation produces delta = 0 for User, Organization, and Membership."""
        award, allocs = self.create_and_finalize_multi_award()

        user_count_before = User.objects.count()
        org_count_before = Organization.objects.count()
        membership_count_before = OrganizationMembership.objects.count()

        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)

        ext_deal = next(d for d in deals if d.award_allocation_id == allocs[2].id)
        self.assertIsNotNone(ext_deal.seller_external_counterparty)

        user_count_after = User.objects.count()
        org_count_after = Organization.objects.count()
        membership_count_after = OrganizationMembership.objects.count()

        self.assertEqual(user_count_after - user_count_before, 0)
        self.assertEqual(org_count_after - org_count_before, 0)
        self.assertEqual(membership_count_after - membership_count_before, 0)

    def test_source_graph_integrity_mismatch_rejected(self):
        """Corrupted/mismatched source graph raises DealSourceIntegrityError."""
        award, allocs = self.create_and_finalize_multi_award()
        alloc = allocs[0]

        # Create another RFQ
        other_rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_owner,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("100.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.COLLECTING_OFFERS,
            visibility=RFQVisibility.PUBLIC,
        )
        alloc.offer.rfq = other_rfq
        alloc.offer.save(update_fields=["rfq"])

        with self.assertRaises(DealSourceIntegrityError):
            materialize_deals_from_award(award.id, actor=self.buyer_owner)

    def test_atomic_failure_rollback(self):
        """Failure midway rolls back all newly created deals, leaving prior successful deals untouched."""
        award, allocs = self.create_and_finalize_multi_award()

        # First, materialize Deal 1 alone
        deal1 = Deal.objects.create(
            award=award,
            award_allocation=allocs[0],
            rfq=self.rfq,
            offer=allocs[0].offer,
            offer_version=allocs[0].offer_version,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )

        original_deal_create = Deal.objects.create
        call_count = 0

        def failing_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("Simulated failure during deal materialization!")
            return original_deal_create(*args, **kwargs)

        with patch("deals.models.Deal.objects.create", side_effect=failing_create):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(award.id, actor=self.buyer_owner)

        # Deal 1 must still exist
        self.assertTrue(Deal.objects.filter(pk=deal1.pk).exists())
        # Total deals for award must still be exactly 1 (no partial set of deals 2 or 3)
        self.assertEqual(Deal.objects.filter(award=award).count(), 1)

    def test_optimistic_concurrency_expected_version(self):
        """Expected version validation: match succeeds, mismatch raises StaleVersionError."""
        award, _ = self.create_and_finalize_single_award()

        # Stale version raises 409 error
        with self.assertRaises(StaleVersionError):
            materialize_deals_from_award(
                award.id,
                actor=self.buyer_owner,
                expected_version=award.version + 99,
            )

        # Matching version succeeds
        deals, newly_created = materialize_deals_from_award(
            award.id,
            actor=self.buyer_owner,
            expected_version=award.version,
        )
        self.assertTrue(newly_created)
        self.assertEqual(len(deals), 1)

    def test_scope_audit_no_execution_or_terms_snapshot_fields(self):
        """Audit Deal model to verify absence of premature snapshot/attribution/execution fields."""
        deal_fields = [f.name for f in Deal._meta.get_fields()]

        # No premature execution statuses
        forbidden_keywords = [
            "status",
            "execution",
            "in_transit",
            "delivered",
            "payment",
            "inspection",
            "terms_snapshot",
            "party_snapshot",
            "attribution",
        ]
        for keyword in forbidden_keywords:
            self.assertNotIn(
                keyword,
                deal_fields,
                f"Deal model contains premature field '{keyword}' out of T0901 scope.",
            )
