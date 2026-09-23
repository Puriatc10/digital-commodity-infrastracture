from decimal import Decimal
import uuid

from rest_framework import status
from rest_framework.test import APIClient

from deals.models import Deal
from deals.tests.base import BaseDealsTestCase
from offers.services import add_award_allocation, create_draft_award


class DealAPITests(BaseDealsTestCase):
    """Integration API tests for Deal materialization and read endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_materialize_deals_api_single_and_multi_success(self):
        """POST /awards/{award_id}/materialize-deals/ creates deals (201) and returns minimal aggregate."""
        award, allocs = self.create_and_finalize_multi_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url, {}, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(len(data), 3)

        deal = data[0]
        self.assertIn("id", deal)
        self.assertEqual(deal["award_id"], str(award.id))
        self.assertEqual(deal["rfq_id"], str(self.rfq.id))
        self.assertEqual(deal["buyer_organization_id"], str(self.buyer_org.id))
        self.assertIsNotNone(deal["created_by_id"])
        self.assertIsNotNone(deal["created_at"])

    def test_materialize_deals_api_idempotent_duplicate_call(self):
        """Repeated duplicate call returns 200 OK with exact same Deal identities and no duplicates."""
        award, _ = self.create_and_finalize_single_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)

        # Call 1: Newly materialized (201)
        res1 = self.client.post(url, {}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        data1 = res1.json()

        # Call 2: Idempotent return (200)
        res2 = self.client.post(url, {}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        data2 = res2.json()

        self.assertEqual(len(data1), len(data2))
        self.assertEqual(data1[0]["id"], data2[0]["id"])
        self.assertEqual(Deal.objects.filter(award=award).count(), 1)

    def test_materialize_deals_api_draft_award_rejected(self):
        """Materializing a DRAFT award returns 400 Bad Request; zero deals created."""
        draft_award = create_draft_award(self.rfq.id, actor=self.buyer_owner)
        add_award_allocation(
            draft_award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("500.000"),
            quantity_unit="MT",
            expected_version=draft_award.version,
            actor=self.buyer_owner,
        )
        url = f"/api/awards/{draft_award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url, {}, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Deal.objects.filter(award=draft_award).count(), 0)

    def test_materialize_deals_api_authorization_matrix(self):
        """Verify actor permissions: Buyer Owner/Manager/Member, Operator, Admin allowed; others denied."""
        award, _ = self.create_and_finalize_single_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        # 1. Anonymous -> 401 or 403
        self.client.force_authenticate(user=None)
        res = self.client.post(url, {}, format="json")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # 2. Seller Supplier -> 403
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Seller Broker -> 403
        self.client.force_authenticate(user=self.broker_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Foreign Buyer -> 403
        self.client.force_authenticate(user=self.foreign_buyer_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 5. Buyer Viewer -> 403
        self.client.force_authenticate(user=self.buyer_viewer)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 6. Django Staff/Superuser without system role -> 403
        self.client.force_authenticate(user=self.staff_only_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 7. Buyer Member -> 201
        self.client.force_authenticate(user=self.buyer_member)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_materialize_deals_api_operator_and_admin_authorized(self):
        """Platform Operators and Product Admins can materialize deals."""
        award, _ = self.create_and_finalize_single_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.operator_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.admin_user)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_materialize_deals_api_nonexistent_award_returns_404(self):
        """Nonexistent award UUID returns 404 Not Found."""
        url = f"/api/awards/{uuid.uuid4()}/materialize-deals/"
        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url, {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_materialize_deals_api_stale_expected_version_returns_409(self):
        """Stale expected_version returns 409 Conflict."""
        award, _ = self.create_and_finalize_single_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url, {"expected_version": award.version + 99}, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_materialize_deals_api_client_cannot_forge_terms_or_parties(self):
        """Client payload spoofing commercial terms or party IDs is rejected or ignored."""
        award, alloc = self.create_and_finalize_single_award()
        url = f"/api/awards/{award.id}/materialize-deals/"

        # Attempt to spoof buyer, seller, quantity, price in request body
        spoofed_payload = {
            "buyer_organization_id": str(self.foreign_buyer_org.id),
            "seller_organization_id": str(self.broker_org.id),
            "quantity": 999999,
            "unit_price": "1.00",
            "expected_version": award.version,
        }

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url, spoofed_payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        deal_data = res.json()[0]

        # Authoritative derivation must be preserved
        self.assertEqual(deal_data["buyer_organization_id"], str(self.buyer_org.id))
        self.assertEqual(deal_data["seller_organization_id"], str(self.supplier_org.id))

    def test_deal_read_foundation_list_and_detail(self):
        """GET /deals/ and GET /deals/{id}/ server-side scoping."""
        award, allocs = self.create_and_finalize_multi_award()
        url_mat = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url_mat, {}, format="json")
        deals = res.json()
        supplier_deal_id = deals[0]["id"]

        # 1. Buyer sees all their Buyer Deals
        self.client.force_authenticate(user=self.buyer_member)
        res = self.client.get("/api/deals/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 3)

        res_detail = self.client.get(f"/api/deals/{supplier_deal_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)

        # 2. Supplier sees only their own Seller Deal
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get("/api/deals/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 1)
        self.assertEqual(res.json()[0]["id"], supplier_deal_id)

        res_detail = self.client.get(f"/api/deals/{supplier_deal_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)

        # 3. Foreign Buyer sees empty list and cannot access deal detail (403)
        self.client.force_authenticate(user=self.foreign_buyer_user)
        res = self.client.get("/api/deals/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 0)

        res_detail = self.client.get(f"/api/deals/{supplier_deal_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Operator sees all deals
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get("/api/deals/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.json()), 3)

    def test_deal_mutation_and_deletion_endpoints_unavailable(self):
        """Normal product APIs expose NO PATCH, PUT, DELETE, or arbitrary POST on /deals/."""
        award, _ = self.create_and_finalize_single_award()
        url_mat = f"/api/awards/{award.id}/materialize-deals/"

        self.client.force_authenticate(user=self.buyer_owner)
        res = self.client.post(url_mat, {}, format="json")
        deal_id = res.json()[0]["id"]

        # PATCH /deals/{id}/ -> 405 Method Not Allowed
        res_patch = self.client.patch(f"/api/deals/{deal_id}/", {"quantity": 100}, format="json")
        self.assertEqual(res_patch.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # PUT /deals/{id}/ -> 405 Method Not Allowed
        res_put = self.client.put(f"/api/deals/{deal_id}/", {"quantity": 100}, format="json")
        self.assertEqual(res_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # DELETE /deals/{id}/ -> 405 Method Not Allowed
        res_del = self.client.delete(f"/api/deals/{deal_id}/")
        self.assertEqual(res_del.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # POST /deals/ -> 405 Method Not Allowed
        res_post = self.client.post("/api/deals/", {"award_id": str(award.id)}, format="json")
        self.assertEqual(res_post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
