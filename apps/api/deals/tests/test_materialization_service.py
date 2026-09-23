from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model

from commodities.models import CommodityAttributeDefinition, CommoditySchemaVersion
from commodities.services import publish_schema
from deals.exceptions import (
    AwardNotFinalizedError,
    DealPermissionDeniedError,
)
from deals.models import (
    Deal,
    DealPartySnapshot,
    DealTermsSnapshot,
    PartyRole,
    PartyType,
)
from deals.services import materialize_deals_from_award, project_deal_specifications
from deals.tests.base import BaseDealsTestCase
from offers.enums import CostComponentKind, LogisticsCostStatus
from offers.models import OfferCostComponent
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    finalize_award,
    submit_internal_offer_version,
)
from organizations.models import Organization, OrganizationMembership
from trade_hub.models import RFQ

User = get_user_model()


class DealMaterializationServiceTests(BaseDealsTestCase):
    """Domain tests for materialize_deals_from_award service (T0901, T0902)."""

    def test_single_allocation_creates_deal_and_all_snapshots(self):
        """Finalized Award with 1 allocation materializes into Deal with terms and party snapshots."""
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
        self.assertEqual(deal.buyer_organization, self.buyer_org)
        self.assertEqual(deal.seller_organization, self.supplier_org)

        # Snapshots present
        self.assertTrue(hasattr(deal, "terms_snapshot"))
        terms = deal.terms_snapshot
        self.assertEqual(terms.quantity, alloc.awarded_quantity)
        self.assertEqual(terms.unit_price, alloc.offer_version.unit_price)
        self.assertEqual(terms.currency, alloc.offer_version.currency)

        parties = list(deal.party_snapshots.all().order_by("role"))
        self.assertEqual(len(parties), 2)
        self.assertEqual(parties[0].role, PartyRole.BUYER)
        self.assertEqual(parties[0].organization, self.buyer_org)
        self.assertEqual(parties[1].role, PartyRole.SELLER)
        self.assertEqual(parties[1].organization, self.supplier_org)

    def test_multi_award_creates_n_separate_deals(self):
        """Multi-Award with N allocations creates N separate Deals with independent snapshots."""
        award, allocs = self.create_and_finalize_multi_award()
        self.assertEqual(len(allocs), 3)

        deals, newly_created = materialize_deals_from_award(
            award.id,
            actor=self.buyer_owner,
        )

        self.assertTrue(newly_created)
        self.assertEqual(len(deals), 3)
        self.assertEqual(Deal.objects.filter(award=award).count(), 3)

        for deal in deals:
            self.assertTrue(hasattr(deal, "terms_snapshot"))
            self.assertEqual(deal.party_snapshots.count(), 2)

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

        deals, _ = materialize_deals_from_award(award.id, actor=self.operator_user)

        self.assertEqual(deals[0].buyer_organization, self.rfq.organization)
        buyer_party = deals[0].party_snapshots.get(role=PartyRole.BUYER)
        self.assertEqual(buyer_party.organization, self.rfq.organization)
        self.assertEqual(buyer_party.name_snapshot, self.rfq.organization.name)

    def test_seller_derivation_broker_not_reclassified(self):
        """Broker offer seller is Broker Organization; role is not reclassified."""
        award, allocs = self.create_and_finalize_multi_award()

        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)

        broker_deal = next(d for d in deals if d.award_allocation_id == allocs[1].id)
        self.assertEqual(broker_deal.seller_organization, self.broker_org)
        self.assertEqual(broker_deal.offer.offeror_role, "BROKER")

        seller_party = broker_deal.party_snapshots.get(role=PartyRole.SELLER)
        self.assertEqual(seller_party.party_type, PartyType.ORGANIZATION)
        self.assertEqual(seller_party.organization, self.broker_org)

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

        # External party snapshot correctly populated
        ext_party = ext_deal.party_snapshots.get(role=PartyRole.SELLER)
        self.assertEqual(ext_party.party_type, PartyType.EXTERNAL_COUNTERPARTY)
        self.assertEqual(ext_party.external_counterparty, self.ext_counterparty)
        self.assertIsNone(ext_party.organization)
        self.assertEqual(ext_party.name_snapshot, self.ext_counterparty.company_name)

    # =========================================================================
    # Explicit T0902 Snapshot & Commercial Invariant Tests
    # =========================================================================

    def test_awarded_quantity_not_equal_offered_quantity(self):
        """
        CRITICAL REGRESSION TEST:
        Offer offered_quantity = 700 MT
        Award awarded_quantity = 400 MT
        -> Deal terms snapshot quantity MUST be 400 MT, NEVER 700 MT.
        """
        # Offer has offered_quantity = 500 MT, but Award allocates 400 MT
        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        alloc = add_award_allocation(
            draft_award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("400.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )

        draft_award.refresh_from_db()
        finalized_award = finalize_award(
            draft_award.id,
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )

        deals, created = materialize_deals_from_award(finalized_award.id, actor=self.buyer_owner)
        self.assertTrue(created)
        self.assertEqual(len(deals), 1)

        deal = deals[0]
        terms = deal.terms_snapshot
        # Authoritative assertions:
        self.assertEqual(terms.quantity, Decimal("400.000"))
        self.assertNotEqual(terms.quantity, self.supplier_v1.offered_quantity)
        self.assertEqual(terms.quantity, alloc.awarded_quantity)

    def test_price_currency_payment_delivery_exact(self):
        """Accepted commercial terms are copied exactly from OfferVersion and RFQ context."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        self.assertEqual(terms.unit_price, self.supplier_v1.unit_price)
        self.assertEqual(terms.currency, self.supplier_v1.currency)
        self.assertEqual(terms.payment_terms, self.supplier_v1.payment_terms)
        self.assertEqual(terms.delivery_terms, self.supplier_v1.delivery_terms)
        self.assertEqual(terms.incoterm, self.supplier_v1.incoterm)
        self.assertEqual(terms.delivery_start, self.supplier_v1.delivery_start)
        self.assertEqual(terms.delivery_end, self.supplier_v1.delivery_end)
        self.assertEqual(terms.origin, self.rfq.origin)
        self.assertEqual(terms.destination, self.rfq.destination)

    def test_product_cost_snapshot_decimal_exact(self):
        """Product cost snapshot is unit_price * awarded_quantity computed strictly in Decimal."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        expected_product_cost = (alloc.awarded_quantity * self.supplier_v1.unit_price).quantize(Decimal("0.01"))
        self.assertEqual(terms.product_cost_snapshot, expected_product_cost)
        self.assertIsInstance(terms.product_cost_snapshot, Decimal)

    def test_specifications_exact_deep_copy(self):
        """Dynamic specifications are a deep copy; later mutation of source dict does not affect Deal."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        self.assertEqual(terms.specifications, self.supplier_v1.specifications)

        # Mutate the source dictionary in python memory
        self.supplier_v1.specifications["penetration_grade"] = "MUTATED_VALUE"
        self.assertNotEqual(terms.specifications["penetration_grade"], "MUTATED_VALUE")

    def test_schema_version_exact_historical_version(self):
        """DealTermsSnapshot retains exact historical CommoditySchemaVersion from selected OfferVersion."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        self.assertEqual(terms.schema_version, self.supplier_v1.schema_version)
        self.assertEqual(terms.schema_version.version, 1)

    def test_unknown_logistics_cost_preserved(self):
        """LogisticsCostStatus.UNKNOWN is preserved without inventing zero dollars."""
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("355.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            logistics_cost_status=LogisticsCostStatus.UNKNOWN,
        )
        self.supplier_offer.refresh_from_db()
        v2 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v2.id,
            expected_version=self.supplier_offer.aggregate_version,
        )

        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            draft_award.id,
            offer_version_id=v2.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )
        draft_award.refresh_from_db()
        finalized_award = finalize_award(draft_award.id, actor=self.buyer_owner, expected_version=draft_award.version)

        deals, _ = materialize_deals_from_award(finalized_award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        self.assertEqual(terms.logistics_cost_status, LogisticsCostStatus.UNKNOWN)
        self.assertIsNone(terms.logistics_cost_amount)
        self.assertNotEqual(terms.logistics_cost_amount, Decimal("0.00"))

    def test_cost_snapshot_isolation(self):
        """OfferCostComponent creates independent DealCostSnapshot rows; deleting source rows does not alter Deal."""
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("355.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("8000.00"),
        )
        OfferCostComponent.objects.create(
            offer_version=v2,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("8000.00"),
            currency="USD",
            description="Freight charge",
        )
        OfferCostComponent.objects.create(
            offer_version=v2,
            kind=CostComponentKind.OTHER,
            amount=Decimal("1500.00"),
            currency="USD",
            description="Inspection fee",
        )
        self.supplier_offer.refresh_from_db()
        v2 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v2.id,
            expected_version=self.supplier_offer.aggregate_version,
        )

        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            draft_award.id,
            offer_version_id=v2.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )
        draft_award.refresh_from_db()
        finalized_award = finalize_award(draft_award.id, actor=self.buyer_owner, expected_version=draft_award.version)

        deals, _ = materialize_deals_from_award(finalized_award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        cost_snapshots = list(terms.cost_snapshots.all().order_by("amount"))
        self.assertEqual(len(cost_snapshots), 2)
        self.assertEqual(cost_snapshots[0].kind, CostComponentKind.OTHER)
        self.assertEqual(cost_snapshots[0].amount, Decimal("1500.00"))
        self.assertEqual(cost_snapshots[1].kind, CostComponentKind.LOGISTICS)
        self.assertEqual(cost_snapshots[1].amount, Decimal("8000.00"))

        # Delete the source rows directly
        OfferCostComponent.objects.filter(offer_version=v2).delete()

        # DealCostSnapshots must remain completely intact
        self.assertEqual(terms.cost_snapshots.count(), 2)

    def test_source_mutation_stability(self):
        """Mutating live source Organization, RFQ, or Offer does NOT mutate Deal snapshots."""
        award, _ = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        original_buyer_name = self.buyer_org.name
        original_supplier_name = self.supplier_org.name
        original_rfq_origin = self.rfq.origin

        # Mutate source records
        self.buyer_org.name = "Renamed Buyer Corp"
        self.buyer_org.save(update_fields=["name"])

        self.supplier_org.name = "Renamed Supplier Corp"
        self.supplier_org.save(update_fields=["name"])

        # Mutate RFQ allowed field
        self.rfq.notes = "Mutated RFQ operational notes"
        self.rfq.save(update_fields=["notes"])

        # Mutate RFQ origin via direct DB update to simulate an external mutation
        RFQ.objects.filter(pk=self.rfq.pk).update(origin="Completely Different Port")

        # Re-fetch snapshots from DB
        terms = DealTermsSnapshot.objects.get(deal=deal)
        buyer_party = DealPartySnapshot.objects.get(deal=deal, role=PartyRole.BUYER)
        seller_party = DealPartySnapshot.objects.get(deal=deal, role=PartyRole.SELLER)

        self.assertEqual(terms.origin, original_rfq_origin)
        self.assertEqual(buyer_party.name_snapshot, original_buyer_name)
        self.assertEqual(seller_party.name_snapshot, original_supplier_name)

    def test_active_schema_change_stability(self):
        """Advancing Commodity active schema does not mutate Deal snapshot or historical projection."""
        award, _ = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        terms = deals[0].terms_snapshot

        # Create schema v2 for the commodity and publish + activate it
        schema_v2 = CommoditySchemaVersion.objects.create(
            commodity=self.commodity,
            version=2,
            status=CommoditySchemaVersion.SchemaStatus.DRAFT,
        )
        CommodityAttributeDefinition.objects.create(
            schema_version=schema_v2,
            key="v2_special_spec",
            label_fa="ویژگی نسخه دو",
            label_en="V2 Special Spec",
            data_type=CommodityAttributeDefinition.DataType.STRING,
            is_required=True,
        )
        publish_schema(schema_v2, activate=True)

        self.commodity.refresh_from_db()
        self.assertEqual(self.commodity.active_schema_version_id, schema_v2.id)

        # Re-read DealTermsSnapshot: schema_version is STILL v1
        terms.refresh_from_db()
        self.assertEqual(terms.schema_version.version, 1)

        # Historical projection uses stored schema version v1, not v2
        projection = project_deal_specifications(terms)
        proj_keys = [p["key"] for p in projection]
        self.assertIn("penetration_grade", proj_keys)
        self.assertNotIn("v2_special_spec", proj_keys)

    def test_materialization_idempotency_does_not_refresh_snapshot(self):
        """Calling materialization a second time returns existing Deal and NEVER refreshes party snapshots."""
        award, _ = self.create_and_finalize_single_award()
        deals1, created1 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertTrue(created1)

        deal = deals1[0]
        seller_party = deal.party_snapshots.get(role=PartyRole.SELLER)
        self.assertEqual(seller_party.name_snapshot, self.supplier_org.name)

        # Mutate the source organization name
        self.supplier_org.name = "Mutated Global Supplier Corp"
        self.supplier_org.save(update_fields=["name"])

        # Call materialization again
        deals2, created2 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertFalse(created2)

        # Snapshot MUST still preserve the historical creation name
        refreshed_party = deals2[0].party_snapshots.get(role=PartyRole.SELLER)
        self.assertEqual(refreshed_party.name_snapshot, "Supplier Petro Corp")
        self.assertNotEqual(refreshed_party.name_snapshot, "Mutated Global Supplier Corp")

    def test_failure_rollback_during_terms_creation(self):
        """Failure midway during DealTermsSnapshot creation rolls back Deal completely."""
        award, _ = self.create_and_finalize_single_award()
        with patch("deals.models.DealTermsSnapshot.objects.create", side_effect=RuntimeError("Terms failure")):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertEqual(Deal.objects.filter(award=award).count(), 0)

    def test_failure_rollback_during_party_creation(self):
        """Failure midway during DealPartySnapshot creation rolls back Deal completely."""
        award, _ = self.create_and_finalize_single_award()
        with patch("deals.models.DealPartySnapshot.objects.create", side_effect=RuntimeError("Party failure")):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertEqual(Deal.objects.filter(award=award).count(), 0)

    def test_failure_rollback_during_cost_creation(self):
        """Failure midway during DealCostSnapshot creation rolls back Deal completely."""
        v2 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("355.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("5000.00"),
        )
        OfferCostComponent.objects.create(
            offer_version=v2,
            kind=CostComponentKind.LOGISTICS,
            amount=Decimal("5000.00"),
            currency="USD",
        )
        self.supplier_offer.refresh_from_db()
        v2 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=v2.id,
            expected_version=self.supplier_offer.aggregate_version,
        )
        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            draft_award.id,
            offer_version_id=v2.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )
        draft_award.refresh_from_db()
        award = finalize_award(draft_award.id, actor=self.buyer_owner, expected_version=draft_award.version)

        with patch("deals.models.DealCostSnapshot.objects.create", side_effect=RuntimeError("Cost failure")):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertEqual(Deal.objects.filter(award=award).count(), 0)

    def test_scope_audit_no_attribution_or_execution_fields(self):
        """Audit Deal and DealTermsSnapshot models to verify absence of Attribution (T0903) and Execution (Epic 10)."""
        deal_fields = [f.name for f in Deal._meta.get_fields()]
        terms_fields = [f.name for f in DealTermsSnapshot._meta.get_fields()]

        # Verified presence of approved T0902 snapshot relations, T0903 attribution, and T0904 broker/opportunity provenance
        self.assertIn("terms_snapshot", deal_fields)
        self.assertIn("party_snapshots", deal_fields)
        self.assertIn("attribution", deal_fields)
        self.assertIn("broker_attributions", deal_fields)
        self.assertIn("opportunity_attributions", deal_fields)

        # Forbidden premature Commission / Broker Economics fields
        forbidden_commission = [
            "commission",
            "commission_rate",
            "revenue_share",
            "fee_amount",
            "referral_fee",
            "payout",
        ]
        for keyword in forbidden_commission:
            self.assertNotIn(keyword, deal_fields)
            self.assertNotIn(keyword, terms_fields)


        # Forbidden premature Execution fields (Epic 10)
        forbidden_execution = [
            "status",
            "execution",
            "execution_status",
            "milestone",
            "shipment",
            "in_transit",
            "delivered",
            "payment_status",
            "inspection_status",
            "issues",
        ]
        for keyword in forbidden_execution:
            self.assertNotIn(keyword, deal_fields)
            self.assertNotIn(keyword, terms_fields)
