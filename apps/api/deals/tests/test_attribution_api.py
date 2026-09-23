from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealAttributionResolutionMethod,
    DealAttributionStatus,
    DealPartySnapshot,
    DealTermsSnapshot,
)
from deals.services import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase

User = get_user_model()


class DealAttributionApiTests(BaseDealsTestCase):
    """
    Integration tests for Deal attribution materialization, API endpoints, authorization,
    customer privacy, immutability, and ACL separation (T0903).
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_materialization_creates_attribution_aggregate(self):
        """Materializing a single award creates a linked DealAttribution aggregate."""
        award, alloc = self.create_and_finalize_single_award()

        deals, created = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertTrue(created)
        self.assertEqual(len(deals), 1)

        deal = deals[0]
        self.assertTrue(hasattr(deal, "attribution"))
        attr = deal.attribution
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.primary_channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertEqual(attr.resolution_method, DealAttributionResolutionMethod.AUTOMATIC)
        self.assertIsNotNone(attr.resolved_at)

    def test_materialization_multi_award_creates_independent_attributions(self):
        """Multi-Award materialization creates distinct DealAttribution rows for each Deal."""
        award, allocs = self.create_and_finalize_multi_award()

        deals, created = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertTrue(created)
        self.assertEqual(len(deals), 3)

        supplier_deal = [d for d in deals if d.seller_organization == self.supplier_org][0]
        broker_deal = [d for d in deals if d.seller_organization == self.broker_org][0]
        ext_deal = [d for d in deals if d.seller_external_counterparty == self.ext_counterparty][0]

        self.assertEqual(supplier_deal.attribution.primary_channel, DealAttributionChannel.DIRECT_SUPPLIER)
        self.assertEqual(broker_deal.attribution.primary_channel, DealAttributionChannel.BROKER)
        self.assertEqual(ext_deal.attribution.primary_channel, DealAttributionChannel.OPPORTUNITY_DESK)

    def test_materialization_idempotent_preserves_attribution(self):
        """Repeated materialization returns existing Deal set and preserves original attribution."""
        award, alloc = self.create_and_finalize_single_award()

        deals1, created1 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertTrue(created1)
        original_attr_id = deals1[0].attribution.id

        deals2, created2 = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertFalse(created2)
        self.assertEqual(deals2[0].attribution.id, original_attr_id)

    def test_materialization_atomicity_attribution_failure_rolls_back(self):
        """Failure during DealAttribution creation completely rolls back newly materialized Deals."""
        award, alloc = self.create_and_finalize_single_award()

        with patch("deals.services.materialization.create_initial_deal_attribution", side_effect=RuntimeError("Attribution DB error")):
            with self.assertRaises(RuntimeError):
                materialize_deals_from_award(award.id, actor=self.buyer_owner)

        # Invariant: No orphaned Deals, TermsSnapshots, or PartySnapshots
        self.assertEqual(Deal.objects.filter(award=award).count(), 0)
        self.assertEqual(DealTermsSnapshot.objects.count(), 0)
        self.assertEqual(DealPartySnapshot.objects.count(), 0)
        self.assertEqual(DealAttribution.objects.count(), 0)

    def test_get_deal_attribution_detail_customer_privacy(self):
        """Customer actors (Buyer/Seller) receive privacy-preserving projection without internal evidence."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        # Authenticate as Buyer Owner
        self.client.force_authenticate(user=self.buyer_owner)
        url = f"/api/deals/{deal.id}/attribution/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], DealAttributionStatus.RESOLVED)
        self.assertEqual(data["primary_channel"], DealAttributionChannel.DIRECT_SUPPLIER)
        # Privacy check: internal evidence is strictly withheld (null)
        self.assertIsNone(data["evidence_snapshot"])
        self.assertIsNone(data["resolved_by_id"])
        self.assertIsNone(data["resolution_reason"])

    def test_get_deal_attribution_detail_operator_full_projection(self):
        """Platform Operator receives complete internal provenance projection including evidence snapshot."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        # Authenticate as Platform Operator
        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{deal.id}/attribution/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsNotNone(data["evidence_snapshot"])
        self.assertIn("deal_id", data["evidence_snapshot"])
        self.assertEqual(data["evidence_snapshot"]["deal_id"], str(deal.id))

    def test_acl_separation_attributed_broker_has_no_access(self):
        """Attributed Broker that is not a commercial seller is denied access to Deal and Attribution."""
        # Create a Deal where broker is attributed via opportunity referral, but seller is external
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        # Ensure broker_org is in attribution evidence
        deal.attribution.evidence_snapshot["source_supply_opportunity_broker_id"] = str(self.broker_org.id)
        deal.attribution.save(update_fields=["evidence_snapshot"])

        # Authenticate as Broker user (Broker is NOT buyer or seller on this deal)
        self.client.force_authenticate(user=self.broker_user)

        # GET /deals/{id}/ -> 403 Forbidden
        deal_resp = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(deal_resp.status_code, status.HTTP_403_FORBIDDEN)

        # GET /deals/{id}/attribution/ -> 403 Forbidden
        attr_resp = self.client.get(f"/api/deals/{deal.id}/attribution/")
        self.assertEqual(attr_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_manual_resolution_operator_success(self):
        """Operator can manually resolve a PENDING attribution with reason and channel."""
        award, (supplier_alloc, broker_alloc, ext_alloc) = self.create_and_finalize_multi_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=ext_alloc,
            rfq=self.rfq,
            offer=self.ext_offer,
            offer_version=self.ext_v1,
            buyer_organization=self.buyer_org,
            seller_external_counterparty=self.ext_counterparty,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            version=1,
        )

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.PLATFORM_NETWORK,
            "reason": "Verified network directory discovery audit log.",
            "expected_version": 1,
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], DealAttributionStatus.RESOLVED)
        self.assertEqual(data["primary_channel"], DealAttributionChannel.PLATFORM_NETWORK)
        self.assertEqual(data["resolution_method"], DealAttributionResolutionMethod.MANUAL)
        self.assertEqual(data["resolved_by_id"], str(self.operator_user.id))
        self.assertEqual(data["resolution_reason"], "Verified network directory discovery audit log.")
        self.assertEqual(data["version"], 2)

    def test_manual_resolution_denied_to_buyer_and_supplier(self):
        """Buyer and Supplier actors are denied manual resolution authority."""
        award, alloc = self.create_and_finalize_single_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
        )

        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.BUYER_EXISTING_SUPPLIER,
            "reason": "Buyer self-claiming existing supplier.",
        }

        # Buyer Owner -> 403 Forbidden
        self.client.force_authenticate(user=self.buyer_owner)
        resp_buyer = self.client.post(url, payload, format="json")
        self.assertEqual(resp_buyer.status_code, status.HTTP_403_FORBIDDEN)

        # Supplier User -> 403 Forbidden
        self.client.force_authenticate(user=self.supplier_user)
        resp_supplier = self.client.post(url, payload, format="json")
        self.assertEqual(resp_supplier.status_code, status.HTTP_403_FORBIDDEN)

    def test_manual_resolution_denied_to_staff_only_without_system_role(self):
        """Django staff/superuser alone without SystemRoleAssignment are denied manual resolution."""
        staff_user = User.objects.create_user(
            email=f"staff_{uuid.uuid4().hex[:4]}@platform.local",
            password="testpassword123",
            is_staff=True,
            is_superuser=True,
        )
        award, alloc = self.create_and_finalize_single_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
        )

        self.client.force_authenticate(user=staff_user)
        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.DIRECT_SUPPLIER,
            "reason": "Staff attempt.",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manual_resolution_resolved_immutability_returns_409(self):
        """Attempting to resolve an already RESOLVED attribution returns 409 Conflict."""
        award, alloc = self.create_and_finalize_single_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.RESOLVED,
            primary_channel=DealAttributionChannel.DIRECT_SUPPLIER,
            resolution_method=DealAttributionResolutionMethod.AUTOMATIC,
            resolved_at=deal.created_at,
        )

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.BROKER,
            "reason": "Operator trying to rewrite resolved attribution.",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already been resolved", response.json()["detail"])

    def test_manual_resolution_stale_expected_version_returns_409(self):
        """Stale expected_version returns 409 Conflict."""
        award, alloc = self.create_and_finalize_single_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            version=5,
        )

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.DIRECT_SUPPLIER,
            "reason": "Valid reason.",
            "expected_version": 4,  # Stale version
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Stale version error", response.json()["detail"])

    def test_client_evidence_spoofing_rejected(self):
        """Client supplying extra fields (evidence_snapshot, resolved_by) cannot forge them."""
        award, alloc = self.create_and_finalize_single_award()
        deal = Deal.objects.create(
            award=award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_owner,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            evidence_snapshot={"authentic": "fact"},
        )

        self.client.force_authenticate(user=self.operator_user)
        url = f"/api/deals/{deal.id}/attribution/resolve/"
        payload = {
            "primary_channel": DealAttributionChannel.DIRECT_SUPPLIER,
            "reason": "Operator verification.",
            "evidence_snapshot": {"forged": "spoofed_evidence"},
            "resolved_by": str(uuid.uuid4()),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        deal.attribution.refresh_from_db()
        # Invariant: Server preserved original evidence and derived resolved_by
        self.assertEqual(deal.attribution.evidence_snapshot, {"authentic": "fact"})
        self.assertEqual(deal.attribution.resolved_by, self.operator_user)

    def test_no_commission_or_revenue_share_fields(self):
        """Verify absence of commission, fee percentage, or revenue share in API responses."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        self.client.force_authenticate(user=self.operator_user)
        deal_resp = self.client.get(f"/api/deals/{deal.id}/")
        attr_resp = self.client.get(f"/api/deals/{deal.id}/attribution/")

        deal_json = str(deal_resp.json())
        attr_json = str(attr_resp.json())

        forbidden_economic_terms = ["commission", "revenue_share", "referral_fee", "broker_fee"]
        for term in forbidden_economic_terms:
            self.assertNotIn(term, deal_json)
            self.assertNotIn(term, attr_json)
