from decimal import Decimal
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from offers.enums import OfferorRole, OfferVersionStatus
from offers.exceptions import OfferConflictError, StaleVersionError
from offers.models import OfferVersion
from offers.services import (
    create_draft_offer_version,
    create_offer,
    submit_offer_version,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class OfferVersionPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded concurrency tests for OfferVersion:
    1. Concurrent draft creation race: exactly one draft succeeds, second gets OfferConflictError.
    2. Concurrent duplicate submit race: exactly one succeeds, second gets OfferConflictError or StaleVersionError.
    3. Version allocation race: two concurrent creates cannot get the same version number.
    4. Direct DB concurrent draft insert: conditional UniqueConstraint guarantees at most one draft.
    5. Direct DB concurrent duplicate version number insert: UniqueConstraint guarantees uniqueness.
    """

    def setUp(self):
        super().setUp()

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_vconc_{uuid.uuid4().hex[:6]}",
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

        # Buyer & Published RFQ
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
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("1000.000"),
            unit="MT",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier Org & Two Users in same Org
        self.supplier_org = Organization.objects.create(
            name=f"Supplier Co {uuid.uuid4().hex[:4]}",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user1 = User.objects.create_user(
            email=f"worker1_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user1,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        self.supplier_user2 = User.objects.create_user(
            email=f"worker2_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user2,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # Base Offer
        self.offer = create_offer(
            actor=self.supplier_user1,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )

    def test_concurrent_draft_creation_exactly_one_succeeds(self):
        """
        Two concurrent threads on separate PostgreSQL connections attempt to create a draft
        for the same Offer simultaneously.
        Row-level locking and conditional unique constraint guarantee:
        - Exactly one succeeds (creates V1 draft).
        - The second receives OfferConflictError.
        - Total persisted drafts in DB is strictly 1.
        - aggregate_version is incremented exactly once.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                draft = create_draft_offer_version(
                    actor=actor,
                    offer=self.offer.id,
                    offered_quantity=Decimal("200.000"),
                    quantity_unit="MT",
                    unit_price=Decimal("410.00"),
                    currency="USD",
                    specifications={"penetration_grade": "60/70"},
                )
                results[thread_id] = ("SUCCESS", draft.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", self.supplier_user1))
        t2 = threading.Thread(target=thread_task, args=("t2", self.supplier_user2))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        error_res = [res[1] for res in results.values() if res[0] == "ERROR"][0]
        self.assertIsInstance(error_res, (OfferConflictError, StaleVersionError))

        total_drafts = OfferVersion.objects.filter(
            offer=self.offer,
            status=OfferVersionStatus.DRAFT,
        ).count()
        self.assertEqual(total_drafts, 1)

        self.offer.refresh_from_db()
        self.assertEqual(self.offer.aggregate_version, 2)

    def test_duplicate_submit_race_exactly_one_succeeds(self):
        """
        Two concurrent threads on separate PostgreSQL connections attempt to submit
        the exact same DRAFT version simultaneously.
        Locking and status verification guarantee:
        - Exactly one succeeds (transitions status to SUBMITTED).
        - The second receives controlled OfferConflictError or StaleVersionError.
        - aggregate_version is incremented by exactly 1 (not double incremented).
        - current_submitted_version pointer is not corrupted.
        """
        # Create initial draft
        draft = create_draft_offer_version(
            actor=self.supplier_user1,
            offer=self.offer,
            offered_quantity=Decimal("300.000"),
            quantity_unit="MT",
            unit_price=Decimal("390.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
        )
        self.offer.refresh_from_db()
        agg_version_before_submit = self.offer.aggregate_version  # 2

        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                submitted = submit_offer_version(
                    actor=actor,
                    offer_version=draft.id,
                )
                results[thread_id] = ("SUCCESS", submitted.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", self.supplier_user1))
        t2 = threading.Thread(target=thread_task, args=("t2", self.supplier_user2))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        error_res = [res[1] for res in results.values() if res[0] == "ERROR"][0]
        self.assertIsInstance(error_res, (OfferConflictError, StaleVersionError))

        self.offer.refresh_from_db()
        # Verify aggregate_version was incremented by exactly 1
        self.assertEqual(self.offer.aggregate_version, agg_version_before_submit + 1)
        # Verify pointer is valid
        self.assertEqual(self.offer.current_submitted_version_id, draft.id)

        # Verify exactly one submitted version in DB
        draft.refresh_from_db()
        self.assertEqual(draft.status, OfferVersionStatus.SUBMITTED)

    def test_direct_db_concurrent_draft_insert_violates_conditional_unique(self):
        """
        Even if two raw DB inserts attempt to create DRAFT versions directly for the same Offer,
        PostgreSQL conditional UniqueConstraint prevents both from committing.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, v_num):
            connection.close()
            try:
                barrier.wait()
                with transaction.atomic():
                    v = OfferVersion.objects.create(
                        offer=self.offer,
                        version_number=v_num,
                        status=OfferVersionStatus.DRAFT,
                        schema_version=self.schema_version,
                        specifications={"penetration_grade": "60/70"},
                        offered_quantity=Decimal("100.000"),
                        quantity_unit="MT",
                        unit_price=Decimal("400.00"),
                        currency="USD",
                        created_by=self.supplier_user1,
                    )
                results[thread_id] = ("SUCCESS", v.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", 10))
        t2 = threading.Thread(target=thread_task, args=("t2", 11))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        total_drafts = OfferVersion.objects.filter(
            offer=self.offer,
            status=OfferVersionStatus.DRAFT,
        ).count()
        self.assertEqual(total_drafts, 1)

    def test_direct_db_concurrent_duplicate_version_number_insert(self):
        """
        Two raw DB inserts attempting to create versions with the identical version_number
        for the same Offer fail PostgreSQL UniqueConstraint (offer, version_number).
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, status_val):
            connection.close()
            try:
                barrier.wait()
                with transaction.atomic():
                    v = OfferVersion.objects.create(
                        offer=self.offer,
                        version_number=99,  # identical version number!
                        status=status_val,
                        schema_version=self.schema_version,
                        specifications={"penetration_grade": "60/70"},
                        offered_quantity=Decimal("100.000"),
                        quantity_unit="MT",
                        unit_price=Decimal("400.00"),
                        currency="USD",
                        created_by=self.supplier_user1,
                        submitted_by=self.supplier_user1 if status_val == OfferVersionStatus.SUBMITTED else None,
                        submitted_at=timezone.now() if status_val == OfferVersionStatus.SUBMITTED else None,
                    )
                results[thread_id] = ("SUCCESS", v.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        # Both use SUBMITTED to avoid triggering the one-draft constraint first
        t1 = threading.Thread(target=thread_task, args=("t1", OfferVersionStatus.SUBMITTED))
        t2 = threading.Thread(target=thread_task, args=("t2", OfferVersionStatus.SUBMITTED))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)


        total_v99 = OfferVersion.objects.filter(
            offer=self.offer,
            version_number=99,
        ).count()
        self.assertEqual(total_v99, 1)
