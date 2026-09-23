import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from deals.services.materialization import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)

User = get_user_model()


class DealBrokerAttributionAPITests(BaseDealsTestCase):
    """
    API, authorization, and projection tests for Broker and Opportunity attribution (T0904).
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    # -------------------------------------------------------------------------
    # 1. Attributed-Only Broker ACL: Denied Access
    # -------------------------------------------------------------------------
    def test_attributed_only_broker_denied_access_to_deal(self):
        """
        An attributed Broker that is NOT the Deal seller has NO Deal access (Contract §58, §76).
        Must receive 403 Forbidden across all Deal endpoints.
        """
        # Demand Opportunity referred by self.broker_org
        Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
        )

        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        # Verify broker is attributed
        self.assertEqual(deal.broker_attributions.count(), 1)
        self.assertEqual(deal.broker_attributions.first().broker_organization, self.broker_org)

        # But broker is NOT seller (seller is supplier_org)
        self.assertEqual(deal.seller_organization, self.supplier_org)

        # Attributed broker attempts to access Deal
        self.client.force_authenticate(user=self.broker_user)

        # GET /api/deals/{id}/
        resp_deal = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(resp_deal.status_code, status.HTTP_403_FORBIDDEN)

        # GET /api/deals/{id}/terms/
        resp_terms = self.client.get(f"/api/deals/{deal.id}/terms/")
        self.assertEqual(resp_terms.status_code, status.HTTP_403_FORBIDDEN)

        # GET /api/deals/{id}/parties/
        resp_parties = self.client.get(f"/api/deals/{deal.id}/parties/")
        self.assertEqual(resp_parties.status_code, status.HTTP_403_FORBIDDEN)

        # GET /api/deals/{id}/attribution/
        resp_attr = self.client.get(f"/api/deals/{deal.id}/attribution/")
        self.assertEqual(resp_attr.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 2. Broker-as-Seller Access (Authorized via Seller Party, NOT attribution)
    # -------------------------------------------------------------------------
    def test_broker_as_seller_has_access(self):
        """When Broker is the actual Seller party, access is granted via SELLER role, not attribution."""
        award, allocs = self.create_and_finalize_multi_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        broker_deal = next(d for d in deals if d.seller_organization_id == self.broker_org.id)

        self.client.force_authenticate(user=self.broker_user)
        resp = self.client.get(f"/api/deals/{broker_deal.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], str(broker_deal.id))

    # -------------------------------------------------------------------------
    # 3. Projection: Internal vs Customer Privacy Boundary
    # -------------------------------------------------------------------------
    def test_operator_internal_projection_exposes_detailed_provenance(self):
        """Internal Operators receive full provenance: broker_attributions and opportunity_attributions."""
        demand_opp = Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
        )

        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        self.client.force_authenticate(user=self.operator_user)

        resp = self.client.get(f"/api/deals/{deal.id}/attribution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Detailed broker provenance is exposed
        self.assertIn("broker_attributions", resp.data)
        self.assertEqual(len(resp.data["broker_attributions"]), 1)
        brk_row = resp.data["broker_attributions"][0]
        self.assertEqual(brk_row["broker_organization_id"], str(self.broker_org.id))
        self.assertEqual(brk_row["role"], "DEMAND_ORIGINATOR")
        self.assertEqual(brk_row["related_opportunity_id"], str(demand_opp.id))

        # Detailed opportunity provenance is exposed
        self.assertIn("opportunity_attributions", resp.data)
        self.assertEqual(len(resp.data["opportunity_attributions"]), 1)
        opp_row = resp.data["opportunity_attributions"][0]
        self.assertEqual(opp_row["opportunity_id"], str(demand_opp.id))
        self.assertEqual(opp_row["role"], "DEMAND_ORIGIN")

        # Deal endpoint also includes them
        resp_deal = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(resp_deal.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_deal.data["broker_attributions"]), 1)
        self.assertEqual(len(resp_deal.data["opportunity_attributions"]), 1)

    def test_customer_safe_projection_withholds_internal_provenance(self):
        """Customer actors (Buyer/Seller) receive sanitized empty lists for detailed broker/opportunity provenance."""
        Opportunity.objects.create(
            identifier=f"OPP-DEMAND-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            commodity=self.commodity,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=self.broker_org,
            status=OpportunityStatus.CONVERTED,
            converted_rfq=self.rfq,
        )

        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        self.client.force_authenticate(user=self.buyer_owner)

        resp = self.client.get(f"/api/deals/{deal.id}/attribution/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Internal snapshot withheld
        self.assertIsNone(resp.data["evidence_snapshot"])

        # Detailed broker and opportunity rows sanitized to empty lists
        self.assertEqual(resp.data["broker_attributions"], [])
        self.assertEqual(resp.data["opportunity_attributions"], [])

        # In Deal response
        resp_deal = self.client.get(f"/api/deals/{deal.id}/")
        self.assertEqual(resp_deal.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_deal.data["broker_attributions"], [])
        self.assertEqual(resp_deal.data["opportunity_attributions"], [])

    # -------------------------------------------------------------------------
    # 4. No Mutation API
    # -------------------------------------------------------------------------
    def test_no_mutation_endpoints_for_broker_attribution(self):
        """No customer or operator mutation endpoints exist for broker attribution rows."""
        award, alloc = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]

        self.client.force_authenticate(user=self.operator_user)

        # POST /api/deals/{id}/broker-attributions/ -> 404
        resp = self.client.post(f"/api/deals/{deal.id}/broker-attributions/", {})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # PATCH /api/deals/{id}/ -> 405
        resp_patch = self.client.patch(f"/api/deals/{deal.id}/", {})
        self.assertIn(resp_patch.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED])
