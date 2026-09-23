from decimal import Decimal
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from deals.exceptions import AttributionAlreadyResolvedError, StaleVersionError
from deals.models import (
    Deal,
    DealAttribution,
    DealAttributionChannel,
    DealAttributionResolutionMethod,
    DealAttributionStatus,
)
from deals.services import (
    manual_resolve_deal_attribution,
    materialize_deals_from_award,
)
from identity.models import SystemRoleAssignment
from offers.enums import LogisticsCostStatus, OfferorRole
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    create_offer,
    finalize_award,
    submit_internal_offer_version,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class DealAttributionPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Multi-threaded PostgreSQL concurrency tests for Deal attribution:
    1. Simultaneous manual resolution service race:
       Two operators resolve the same PENDING attribution concurrently;
       PostgreSQL row locking (select_for_update) and version/status checks guarantee
       exactly one succeeds and the other receives AttributionAlreadyResolvedError / StaleVersionError.
    2. Simultaneous manual resolution API race:
       Two operators post to /api/deals/{id}/attribution/resolve/ concurrently;
       guarantees exactly one 200 OK and one 409 Conflict, with zero 500 errors.
    3. Concurrent materialization attribution uniqueness:
       Two buyer actors materialize simultaneously; exactly one DealAttribution is created
       per Deal with zero duplicate attributions.
    """

    def setUp(self):
        super().setUp()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_attr_conc_{uuid.uuid4().hex[:6]}",
            name_fa="قیر همزمانی انتساب",
            name_en="Attribution Concurrency Bitumen",
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

        # Buyer Organization
        self.buyer_org = Organization.objects.create(
            name=f"Buyer Conc Org {uuid.uuid4().hex[:4]}",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user1 = User.objects.create_user(
            email=f"buyer1_{uuid.uuid4().hex[:4]}@attrconc.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user1,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )
        self.buyer_user2 = User.objects.create_user(
            email=f"buyer2_{uuid.uuid4().hex[:4]}@attrconc.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user2,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Supplier Organization
        self.supplier_org = Organization.objects.create(
            name=f"Supplier Conc Org {uuid.uuid4().hex[:4]}",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationVerification.objects.create(
            organization=self.supplier_org,
            status=VerificationStatus.VERIFIED,
            version=1,
        )
        self.supplier_user = User.objects.create_user(
            email=f"supplier_{uuid.uuid4().hex[:4]}@attrconc.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Platform Operators
        self.operator_user1 = User.objects.create_user(
            email=f"operator1_{uuid.uuid4().hex[:4]}@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user1,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        self.operator_user2 = User.objects.create_user(
            email=f"operator2_{uuid.uuid4().hex[:4]}@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user2,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        # RFQ and Offer
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user1,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("1000.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.COLLECTING_OFFERS,
            visibility=RFQVisibility.PUBLIC,
        )
        self.supplier_offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.supplier_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("1000.000"),
            quantity_unit="MT",
            unit_price=Decimal("350.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.supplier_offer.refresh_from_db()
        self.supplier_v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.supplier_v1.id,
            expected_version=self.supplier_offer.aggregate_version,
        )
        self.supplier_offer.refresh_from_db()

    def _create_deal_with_pending_attribution(self) -> Deal:
        """Create an Award, allocation, Deal, and PENDING DealAttribution for concurrency testing."""
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        alloc = add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("1000.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()
        finalized_award = finalize_award(
            award.id,
            expected_version=award.version,
            actor=self.buyer_user1,
        )
        deal = Deal.objects.create(
            award=finalized_award,
            award_allocation=alloc,
            rfq=self.rfq,
            offer=self.supplier_offer,
            offer_version=self.supplier_v1,
            buyer_organization=self.buyer_org,
            seller_organization=self.supplier_org,
            created_by=self.buyer_user1,
        )
        DealAttribution.objects.create(
            deal=deal,
            status=DealAttributionStatus.PENDING,
            primary_channel=None,
            version=1,
            evidence_snapshot={"initial": "pending_evidence"},
        )
        return deal

    def test_concurrent_manual_resolution_service_race(self):
        """
        Two operators attempt to manually resolve the same PENDING attribution concurrently.
        Row-locking ensures exactly one succeeds; the second receives AttributionAlreadyResolvedError or StaleVersionError.
        """
        deal = self._create_deal_with_pending_attribution()

        barrier = threading.Barrier(2)
        results = {}

        def thread_resolve(thread_id, actor, channel, reason):
            connection.close()
            try:
                barrier.wait()
                attr = manual_resolve_deal_attribution(
                    deal_id=deal.id,
                    actor=actor,
                    primary_channel=channel,
                    reason=reason,
                    expected_version=1,
                )
                results[thread_id] = ("SUCCESS", attr)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(
            target=thread_resolve,
            args=(
                1,
                self.operator_user1,
                DealAttributionChannel.BROKER,
                "Op1 verified broker introduction",
            ),
        )
        t2 = threading.Thread(
            target=thread_resolve,
            args=(
                2,
                self.operator_user2,
                DealAttributionChannel.OPPORTUNITY_DESK,
                "Op2 verified opportunity desk match",
            ),
        )

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Invariants: Exactly one SUCCESS, exactly one ERROR
        successes = [v for v in results.values() if v[0] == "SUCCESS"]
        errors = [v for v in results.values() if v[0] == "ERROR"]

        self.assertEqual(len(successes), 1, f"Expected 1 success, got: {results}")
        self.assertEqual(len(errors), 1, f"Expected 1 error, got: {results}")

        # The error must be an expected concurrency / already resolved conflict
        self.assertIsInstance(
            errors[0][1],
            (AttributionAlreadyResolvedError, StaleVersionError),
            f"Unexpected error type: {type(errors[0][1])}: {errors[0][1]}",
        )

        # Database verification: DealAttribution is RESOLVED, version is 2, resolution is MANUAL
        deal.attribution.refresh_from_db()
        attr = deal.attribution
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.version, 2)
        self.assertEqual(attr.resolution_method, DealAttributionResolutionMethod.MANUAL)
        self.assertIn(
            attr.primary_channel,
            [DealAttributionChannel.BROKER, DealAttributionChannel.OPPORTUNITY_DESK],
        )
        self.assertIn(attr.resolved_by, [self.operator_user1, self.operator_user2])
        self.assertTrue(attr.resolution_reason)

    def test_concurrent_manual_resolution_api_race(self):
        """
        Two operators post to /api/deals/{deal_id}/attribution/resolve/ concurrently.
        Guarantees:
        - exactly one 200 OK;
        - exactly one 409 Conflict;
        - zero 500 Internal Server Errors;
        - consistent database state.
        """
        deal = self._create_deal_with_pending_attribution()
        barrier = threading.Barrier(2)
        results = {}

        def thread_api_resolve(thread_id, actor, channel, reason):
            connection.close()
            try:
                client = APIClient()
                client.force_authenticate(user=actor)
                url = f"/api/deals/{deal.id}/attribution/resolve/"
                payload = {
                    "primary_channel": channel,
                    "reason": reason,
                    "expected_version": 1,
                }
                barrier.wait()
                resp = client.post(url, data=payload, format="json")
                results[thread_id] = ("STATUS", resp.status_code, resp.data)
            except Exception as exc:
                results[thread_id] = ("EXCEPTION", exc)
            finally:
                connection.close()

        t1 = threading.Thread(
            target=thread_api_resolve,
            args=(
                1,
                self.operator_user1,
                DealAttributionChannel.BROKER,
                "API Op1 resolution",
            ),
        )
        t2 = threading.Thread(
            target=thread_api_resolve,
            args=(
                2,
                self.operator_user2,
                DealAttributionChannel.PLATFORM_NETWORK,
                "API Op2 resolution",
            ),
        )

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Invariants: no unexpected exceptions thrown in thread execution
        exceptions = [v for v in results.values() if v[0] == "EXCEPTION"]
        self.assertEqual(len(exceptions), 0, f"Thread raised unexpected exception: {exceptions}")

        status_codes = [v[1] for v in results.values() if v[0] == "STATUS"]
        self.assertIn(status.HTTP_200_OK, status_codes)
        self.assertIn(status.HTTP_409_CONFLICT, status_codes)
        self.assertEqual(len(status_codes), 2)

        # Database state: DealAttribution is RESOLVED, version == 2
        deal.attribution.refresh_from_db()
        attr = deal.attribution
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.version, 2)
        self.assertEqual(attr.resolution_method, DealAttributionResolutionMethod.MANUAL)

    def test_concurrent_materialization_creates_single_attribution_per_deal(self):
        """
        Concurrent materialization of an award creates exactly one Deal and exactly one DealAttribution.
        Zero duplicate attribution rows are created.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("1000.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()
        finalized_award = finalize_award(
            award.id,
            expected_version=award.version,
            actor=self.buyer_user1,
        )

        barrier = threading.Barrier(2)
        results = {}

        def thread_materialize(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                deals, newly_created = materialize_deals_from_award(
                    finalized_award.id,
                    actor=actor,
                )
                results[thread_id] = ("SUCCESS", deals, newly_created)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_materialize, args=(1, self.buyer_user1))
        t2 = threading.Thread(target=thread_materialize, args=(2, self.buyer_user2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        errors = [v for v in results.values() if v[0] == "ERROR"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {results}")

        # Exactly 1 Deal exists
        deals_qs = Deal.objects.filter(award=finalized_award)
        self.assertEqual(deals_qs.count(), 1)
        deal = deals_qs.first()

        # Exactly 1 DealAttribution exists for this Deal
        attributions = DealAttribution.objects.filter(deal=deal)
        self.assertEqual(attributions.count(), 1)
        attr = attributions.first()
        self.assertEqual(attr.status, DealAttributionStatus.RESOLVED)
        self.assertEqual(attr.primary_channel, DealAttributionChannel.DIRECT_SUPPLIER)
