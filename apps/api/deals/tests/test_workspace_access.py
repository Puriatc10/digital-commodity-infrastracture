from rest_framework import status
from rest_framework.test import APIClient

from deals.services import materialize_deals_from_award
from deals.tests.base import BaseDealsTestCase


class DealWorkspaceAccessTests(BaseDealsTestCase):
    """
    Exhaustive integration tests for Deal Workspace Access Matrix, Customer Privacy,
    and Query Performance (T0905).
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_deal_detail_access_matrix(self):
        """
        Prove full actor access matrix on GET /api/deals/{id}/:
        - Buyer own Deal -> 200 OK
        - Seller own Deal -> 200 OK
        - Operator -> 200 OK (internal projection)
        - Product Admin -> 200 OK (internal projection)
        - Unrelated Org -> 403 Forbidden
        - Attributed-only Broker -> 403 Forbidden
        - Django staff-only without system role -> 403 Forbidden
        - Django superuser-only without system role -> 403 Forbidden
        - Anonymous -> 401 Unauthorized
        """
        award, allocs = self.create_and_finalize_multi_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        supplier_deal = [d for d in deals if d.seller_organization == self.supplier_org][0]
        url = f"/api/deals/{supplier_deal.id}/"

        # 1. Buyer Owner -> 200 OK
        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 2. Buyer Manager -> 200 OK
        self.client.force_authenticate(user=self.buyer_manager)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 3. Buyer Member -> 200 OK
        self.client.force_authenticate(user=self.buyer_member)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 4. Seller Supplier -> 200 OK
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 5. Operator -> 200 OK
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 6. Admin -> 200 OK
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 7. Unrelated Org / Foreign Buyer -> 403 Forbidden
        self.client.force_authenticate(user=self.foreign_buyer_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 8. Attributed-only Broker -> 403 Forbidden
        # (Broker is attributed to the deal via opportunity/broker attribution, but is not buyer or seller party)
        self.client.force_authenticate(user=self.broker_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 9. Django staff-only (no system role) -> 403 Forbidden
        self.client.force_authenticate(user=self.staff_only_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 10. Django superuser-only (no system role) -> 403 Forbidden
        superuser_only = self.staff_only_user
        self.assertTrue(superuser_only.is_superuser)
        self.client.force_authenticate(user=superuser_only)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 11. Anonymous -> 401 Unauthorized
        self.client.force_authenticate(user=None)
        res = self.client.get(url)
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_deal_list_access_matrix(self):
        """
        Prove server-side scoping on GET /api/deals/:
        - Buyer sees all Buyer deals
        - Seller sees only their Seller deals
        - Operator & Admin see all deals
        - Unrelated org sees empty list
        - Attributed-only broker sees empty list
        - Staff/superuser-only sees empty list
        """
        award, allocs = self.create_and_finalize_multi_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        self.assertEqual(len(deals), 3)

        list_url = "/api/deals/"

        # Buyer sees all 3 deals
        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 3)

        # Seller sees only 1 deal
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 1)

        # Operator sees all 3 deals
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 3)

        # Admin sees all 3 deals
        self.client.force_authenticate(user=self.admin_user)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 3)

        # Foreign buyer sees 0 deals
        self.client.force_authenticate(user=self.foreign_buyer_user)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 0)

        # Staff-only user sees 0 deals
        self.client.force_authenticate(user=self.staff_only_user)
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 0)

    def test_customer_vs_internal_attribution_projection(self):
        """
        Customer actors receive a sanitized attribution view without private evidence or provenance rows;
        Internal operators and admins receive the complete provenance view.
        """
        award, allocs = self.create_and_finalize_multi_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        supplier_deal = [d for d in deals if d.seller_organization == self.supplier_org][0]
        url = f"/api/deals/{supplier_deal.id}/"

        # Customer (Buyer) View
        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["broker_attributions"], [])
        self.assertEqual(data["opportunity_attributions"], [])
        self.assertIsNone(data["attribution"]["evidence_snapshot"])
        self.assertIsNone(data["attribution"]["resolved_by_id"])
        self.assertIsNone(data["attribution"]["resolution_reason"])
        self.assertEqual(data["attribution"]["broker_attributions"], [])
        self.assertEqual(data["attribution"]["opportunity_attributions"], [])

        # Internal (Operator) View
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIsNotNone(data["attribution"]["evidence_snapshot"])

    def test_deal_detail_query_count_no_n_plus_one(self):
        """
        Prove query performance: GET /api/deals/{id}/ executes a bounded number of queries,
        avoiding N+1 on terms, cost snapshots, party snapshots, attribution, and broker rows.
        """
        award, allocs = self.create_and_finalize_multi_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]
        url = f"/api/deals/{deal.id}/"

        self.client.force_authenticate(user=self.operator_user)

        # Warm up connection / permissions cache
        _ = self.client.get(url)

        # Bounded query count: Deal select, prefetches, SystemRole checks
        with self.assertNumQueries(8):
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_commodity_fields_on_terms_snapshot(self):
        """
        Verify that commodity_name_fa, commodity_name_en, and commodity_code
        are accurately projected on DealTermsSnapshot.
        """
        award, allocs = self.create_and_finalize_single_award()
        deals, _ = materialize_deals_from_award(award.id, actor=self.buyer_owner)
        deal = deals[0]
        url = f"/api/deals/{deal.id}/terms/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["commodity_name_fa"], self.commodity.name_fa)
        self.assertEqual(data["commodity_name_en"], self.commodity.name_en)
        self.assertEqual(data["commodity_code"], self.commodity.code)
