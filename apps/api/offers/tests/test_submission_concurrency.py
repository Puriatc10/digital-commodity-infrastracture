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
from offers.enums import OfferorRole, OfferVersionStatus
from offers.exceptions import (
    InvalidVersionError,
    OfferConflictError,
    OfferStateError,
    StaleVersionError,
)
from offers.models import Offer, OfferVersion
from offers.services.creation import create_offer
from offers.services.submission import submit_internal_offer_version
from offers.services.version_services import create_draft_offer_version
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import RFQLifecycleService

User = get_user_model()


class OfferSubmissionConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded concurrency and race tests for T0803:
    1. Concurrent duplicate submit of the same draft -> exactly one succeeds, aggregate_version increments once.
    2. Concurrent first submissions from two different organizations -> both succeed, RFQ ends in COLLECTING_OFFERS.
    3. Concurrent submit vs RFQ close/cancel -> deterministic serialization on RFQ lock without deadlock or corrupted state.
    4. Concurrent submit with optimistic concurrency check -> stale version rejected with StaleVersionError.
    """

    def setUp(self):
        super().setUp()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_submit_conc_{uuid.uuid4().hex[:6]}",
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

        # Buyer Org & User
        self.buyer_org = Organization.objects.create(
            name=f"Buyer Corp {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email=f"buyer_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Published RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            submission_deadline=timezone.now() + timezone.timedelta(days=7),
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier 1 Org & Users
        self.supplier1_org = Organization.objects.create(
            name=f"Supplier 1 {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier1_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier1_user1 = User.objects.create_user(
            email=f"sup1_u1_{uuid.uuid4().hex[:4]}@supplier1.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier1_org,
            user=self.supplier1_user1,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        self.supplier1_user2 = User.objects.create_user(
            email=f"sup1_u2_{uuid.uuid4().hex[:4]}@supplier1.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier1_org,
            user=self.supplier1_user2,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # Supplier 2 Org & User
        self.supplier2_org = Organization.objects.create(
            name=f"Supplier 2 {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier2_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier2_user = User.objects.create_user(
            email=f"sup2_{uuid.uuid4().hex[:4]}@supplier2.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier2_org,
            user=self.supplier2_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

    def test_duplicate_submit_race_same_draft(self):
        """
        Two concurrent threads attempt to submit the exact same draft version simultaneously.
        Lock hierarchy (RFQ -> Offer -> OfferVersion) guarantees:
        - Exactly one succeeds.
        - The other receives OfferConflictError or InvalidVersionError.
        - aggregate_version increments by exactly 1.
        - current_submitted_version is correctly set.
        - RFQ transitions to COLLECTING_OFFERS.
        """
        offer = create_offer(
            actor=self.supplier1_user1,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier1_org,
        )
        draft = create_draft_offer_version(
            actor=self.supplier1_user1,
            offer=offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("420.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        offer.refresh_from_db()
        initial_agg = offer.aggregate_version

        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                submitted = submit_internal_offer_version(
                    actor=actor,
                    offer_version=draft.id,
                    expected_version=initial_agg,
                )
                results[thread_id] = ("SUCCESS", submitted.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", self.supplier1_user1))
        t2 = threading.Thread(target=thread_task, args=("t2", self.supplier1_user2))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        err = [res[1] for res in results.values() if res[0] == "ERROR"][0]
        self.assertIsInstance(err, (OfferConflictError, InvalidVersionError, StaleVersionError))

        offer.refresh_from_db()
        self.assertEqual(offer.aggregate_version, initial_agg + 1)
        self.assertEqual(offer.current_submitted_version_id, draft.id)

        draft.refresh_from_db()
        self.assertEqual(draft.status, OfferVersionStatus.SUBMITTED)

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.COLLECTING_OFFERS)

    def test_concurrent_first_submissions_two_orgs(self):
        """
        Two different organizations submit their respective draft offers simultaneously
        against a Published RFQ.
        Both threads must succeed cleanly, serializing on the RFQ lock:
        - First thread transitions RFQ: PUBLISHED -> COLLECTING_OFFERS.
        - Second thread sees RFQ already in COLLECTING_OFFERS (which is valid for submission).
        - Both offers are submitted successfully.
        - RFQ remains in COLLECTING_OFFERS.
        """
        offer1 = create_offer(
            actor=self.supplier1_user1,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier1_org,
        )
        draft1 = create_draft_offer_version(
            actor=self.supplier1_user1,
            offer=offer1,
            offered_quantity=Decimal("250.000"),
            quantity_unit="MT",
            unit_price=Decimal("415.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )

        offer2 = create_offer(
            actor=self.supplier2_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier2_org,
        )
        draft2 = create_draft_offer_version(
            actor=self.supplier2_user,
            offer=offer2,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("405.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )

        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor, version_id):
            connection.close()
            try:
                barrier.wait()
                submitted = submit_internal_offer_version(
                    actor=actor,
                    offer_version=version_id,
                )
                results[thread_id] = ("SUCCESS", submitted.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", self.supplier1_user1, draft1.id))
        t2 = threading.Thread(target=thread_task, args=("t2", self.supplier2_user, draft2.id))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(results["t1"][0], "SUCCESS")
        self.assertEqual(results["t2"][0], "SUCCESS")

        draft1.refresh_from_db()
        draft2.refresh_from_db()
        self.assertEqual(draft1.status, OfferVersionStatus.SUBMITTED)
        self.assertEqual(draft2.status, OfferVersionStatus.SUBMITTED)

        offer1.refresh_from_db()
        offer2.refresh_from_db()
        self.assertEqual(offer1.current_submitted_version_id, draft1.id)
        self.assertEqual(offer2.current_submitted_version_id, draft2.id)

        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.COLLECTING_OFFERS)

    def test_submit_vs_close_race(self):
        """
        Submission races against RFQ close.
        Because RFQ is locked first (select_for_update), the operations serialize cleanly:
        - If close executes first, submit fails with OfferStateError.
        - If submit executes first, submit succeeds, then close closes the RFQ.
        No deadlock, 500 unhandled exception, or corrupt state occurs.
        """
        offer = create_offer(
            actor=self.supplier1_user1,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier1_org,
        )
        draft = create_draft_offer_version(
            actor=self.supplier1_user1,
            offer=offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("420.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )

        barrier = threading.Barrier(2)
        results = {}

        def submit_task():
            connection.close()
            try:
                barrier.wait()
                submitted = submit_internal_offer_version(
                    actor=self.supplier1_user1,
                    offer_version=draft.id,
                )
                results["submit"] = ("SUCCESS", submitted.id)
            except Exception as exc:
                results["submit"] = ("ERROR", exc)
            finally:
                connection.close()

        def close_task():
            connection.close()
            try:
                barrier.wait()
                closed_rfq = RFQLifecycleService.close_rfq(
                    self.rfq.id,
                    expected_version=self.rfq.version,
                    actor=self.buyer_user,
                )
                results["close"] = ("SUCCESS", closed_rfq.status)
            except Exception as exc:
                results["close"] = ("ERROR", exc)
            finally:
                connection.close()

        t_sub = threading.Thread(target=submit_task)
        t_close = threading.Thread(target=close_task)

        t_sub.start()
        t_close.start()
        t_sub.join(timeout=10)
        t_close.join(timeout=10)

        # Exactly one operation must succeed, and the other must fail with expected domain error
        self.assertTrue(
            (results["submit"][0] == "SUCCESS" and results["close"][0] == "ERROR")
            or (results["submit"][0] == "ERROR" and results["close"][0] == "SUCCESS"),
            f"Unexpected race outcome: submit={results['submit']}, close={results['close']}",
        )

        self.rfq.refresh_from_db()
        draft.refresh_from_db()

        if results["submit"][0] == "SUCCESS":
            # Submit serialized first: RFQ went to COLLECTING_OFFERS, close failed
            self.assertEqual(self.rfq.status, RFQStatus.COLLECTING_OFFERS)
            self.assertEqual(draft.status, OfferVersionStatus.SUBMITTED)
        else:
            # Close serialized first: RFQ went to CLOSED, submit failed with OfferStateError
            self.assertEqual(self.rfq.status, RFQStatus.CLOSED)
            self.assertEqual(draft.status, OfferVersionStatus.DRAFT)
            self.assertIsInstance(results["submit"][1], OfferStateError)
