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
from offers.enums import (
    AwardStatus,
    LogisticsCostStatus,
    OfferorRole,
)
from offers.exceptions import (
    AwardConflictError,
    AwardEligibilityError,
    AwardImmutableError,
    StaleVersionError,
)
from offers.models import AwardAllocation
from offers.services import (
    add_award_allocation,
    create_draft_award,
    create_draft_offer_version,
    create_offer,
    create_revised_draft_offer_version,
    create_revision_request,
    finalize_award,
    submit_internal_offer_version,
    submit_revised_offer_version,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from organizations.verification.models import OrganizationVerification, VerificationStatus
from trade_hub.models import RFQ, RFQStatus, RFQVisibility
from trade_hub.services.rfq_lifecycle import cancel_rfq

User = get_user_model()


class AwardPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Multi-threaded PostgreSQL concurrency tests for Award domain logic:
    1. Race: Finalize vs Finalize (exactly one succeeds, second fails with AwardConflictError or AwardImmutableError).
    2. Race: Finalize vs Revision Submission (RFQ lock orders them; whichever wins commits validly, no deadlock).
    3. Race: Finalize vs RFQ Cancellation (RFQ lock orders them; exactly one terminal status achieved).
    4. Race: Concurrent Duplicate Allocation Add (UniqueConstraint guarantees at most one succeeds).
    """

    def setUp(self):
        super().setUp()

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_awconc_{uuid.uuid4().hex[:6]}",
            name_fa="قیر صنعتی",
            name_en="Industrial Bitumen",
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
            name=f"Buyer Org {uuid.uuid4().hex[:4]}",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user1 = User.objects.create_user(
            email=f"buyer1_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user1,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )
        self.buyer_user2 = User.objects.create_user(
            email=f"buyer2_{uuid.uuid4().hex[:4]}@buyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user2,
            role=OrganizationMembership.OrganizationRole.MEMBER,
            is_active=True,
        )

        # Supplier Organization & Verification
        self.supplier_org = Organization.objects.create(
            name=f"Supplier Org {uuid.uuid4().hex[:4]}",
            country="IR",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationVerification.objects.update_or_create(
            organization=self.supplier_org,
            defaults={
                "status": VerificationStatus.VERIFIED,
                "version": 1,
            },
        )
        self.supplier_user = User.objects.create_user(
            email=f"supplier_{uuid.uuid4().hex[:4]}@supplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Published RFQ
        self.rfq = RFQ.objects.create(
            organization=self.buyer_org,
            created_by=self.buyer_user1,
            commodity=self.commodity,
            schema_version=self.schema_version,
            specifications={"penetration_grade": "60/70"},
            quantity=Decimal("500.000"),
            unit="MT",
            currency="USD",
            status=RFQStatus.PUBLISHED,
            visibility=RFQVisibility.PUBLIC,
        )

        # Supplier Offer with submitted V1
        self.offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.offer.id,
            offered_quantity=Decimal("500.000"),
            quantity_unit="MT",
            unit_price=Decimal("340.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="LC 90 days",
            delivery_terms="FOB",
            incoterm="FOB",
            valid_until=timezone.now() + timezone.timedelta(days=7),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.offer.refresh_from_db()
        self.v1 = submit_internal_offer_version(
            actor=self.supplier_user,
            offer_version=self.v1.id,
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()

    def test_concurrent_finalize_vs_finalize_race(self):
        """
        Two buyer actors attempt to finalize the same draft award concurrently.
        Row-level locking guarantees:
        - Exactly one thread succeeds.
        - The losing thread receives AwardConflictError or AwardImmutableError.
        - Award ends in FINALIZED state.
        - RFQ ends in AWARDED state.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1.id,
            awarded_quantity=Decimal("500.000"),
            expected_version=1,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def thread_finalize(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                finalized = finalize_award(
                    award.id,
                    expected_version=award.version,
                    actor=actor,
                )
                results[thread_id] = ("SUCCESS", finalized)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_finalize, args=(1, self.buyer_user1))
        t2 = threading.Thread(target=thread_finalize, args=(2, self.buyer_user2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [k for k, v in results.items() if v[0] == "SUCCESS"]
        errors = [k for k, v in results.items() if v[0] == "ERROR"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got results: {results}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 error, got results: {results}")

        losing_error = results[errors[0]][1]
        self.assertTrue(
            isinstance(losing_error, (AwardConflictError, AwardImmutableError, StaleVersionError)),
            f"Expected conflict, immutable or stale version error, got: {type(losing_error)}: {losing_error}",
        )

        award.refresh_from_db()
        self.assertEqual(award.status, AwardStatus.FINALIZED)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.status, RFQStatus.AWARDED)

    def test_concurrent_finalize_vs_revision_submission_race(self):
        """
        Race between finalize_award (allocating V1) and submit_revised_offer_version (submitting V2).
        Because both lock the RFQ first, operations serialize without deadlocks.
        - If finalize wins: RFQ becomes AWARDED; revision submit fails because RFQ is no longer PUBLISHED.
        - If revision submit wins: Offer submitted version becomes V2; finalize fails because V1 is stale.
        In neither case do we have inconsistent state or deadlock.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1.id,
            awarded_quantity=Decimal("500.000"),
            expected_version=1,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()

        # Prepare revision request and draft V2 ahead of time
        self.offer.refresh_from_db()
        rev_req = create_revision_request(
            actor=self.buyer_user1,
            offer=self.offer,
            base_offer_version=self.v1,
            requested_fields=["unit_price"],
            message="Please reduce price",
            expected_version=self.offer.aggregate_version,
        )
        self.offer.refresh_from_db()
        v2_draft = create_revised_draft_offer_version(
            actor=self.supplier_user,
            revision_request=rev_req,
            expected_version=self.offer.aggregate_version,
        )
        v2_draft.unit_price = Decimal("330.00")
        v2_draft.save()
        self.offer.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def thread_finalize():
            connection.close()
            try:
                barrier.wait()
                fin = finalize_award(
                    award.id,
                    expected_version=award.version,
                    actor=self.buyer_user1,
                )
                results["FINALIZE"] = ("SUCCESS", fin)
            except Exception as exc:
                results["FINALIZE"] = ("ERROR", exc)
            finally:
                connection.close()

        def thread_submit_revised():
            connection.close()
            try:
                barrier.wait()
                v2_sub, _ = submit_revised_offer_version(
                    actor=self.supplier_user,
                    revision_request=rev_req,
                    expected_version=self.offer.aggregate_version,
                    draft_version=v2_draft,
                )
                results["SUBMIT_REVISED"] = ("SUCCESS", v2_sub)
            except Exception as exc:
                results["SUBMIT_REVISED"] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_finalize)
        t2 = threading.Thread(target=thread_submit_revised)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verify no deadlock occurred and both completed
        self.assertIn("FINALIZE", results)
        self.assertIn("SUBMIT_REVISED", results)

        fin_res = results["FINALIZE"]
        rev_res = results["SUBMIT_REVISED"]

        if fin_res[0] == "SUCCESS":
            # Finalize won: RFQ is AWARDED, and revision submission should have failed
            self.assertEqual(rev_res[0], "ERROR")
            self.rfq.refresh_from_db()
            self.assertEqual(self.rfq.status, RFQStatus.AWARDED)
        else:
            # Revision submission won: V2 submitted, finalize should fail due to stale V1
            self.assertEqual(rev_res[0], "SUCCESS")
            self.assertTrue(isinstance(fin_res[1], AwardEligibilityError))
            self.assertIn("not the current submitted version", str(fin_res[1]))

    def test_concurrent_finalize_vs_cancel_rfq_race(self):
        """
        Race between finalize_award and cancel_rfq.
        Both lock RFQ first.
        - Exactly one succeeds.
        - RFQ ends in either AWARDED or CANCELLED, never an invalid state.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.v1.id,
            awarded_quantity=Decimal("500.000"),
            expected_version=1,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()

        barrier = threading.Barrier(2)
        results = {}

        def thread_finalize():
            connection.close()
            try:
                barrier.wait()
                fin = finalize_award(
                    award.id,
                    expected_version=award.version,
                    actor=self.buyer_user1,
                )
                results["FINALIZE"] = ("SUCCESS", fin)
            except Exception as exc:
                results["FINALIZE"] = ("ERROR", exc)
            finally:
                connection.close()

        def thread_cancel():
            connection.close()
            try:
                barrier.wait()
                cancelled = cancel_rfq(
                    self.rfq,
                    actor=self.buyer_user1,
                    reason="Buyer cancelling RFQ",
                )
                results["CANCEL"] = ("SUCCESS", cancelled)
            except Exception as exc:
                results["CANCEL"] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_finalize)
        t2 = threading.Thread(target=thread_cancel)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn("FINALIZE", results)
        self.assertIn("CANCEL", results)

        fin_res = results["FINALIZE"]
        can_res = results["CANCEL"]

        self.rfq.refresh_from_db()
        if fin_res[0] == "SUCCESS":
            self.assertEqual(can_res[0], "ERROR")
            self.assertEqual(self.rfq.status, RFQStatus.AWARDED)
        else:
            self.assertEqual(can_res[0], "SUCCESS")
            self.assertEqual(self.rfq.status, RFQStatus.CANCELLED)

    def test_concurrent_duplicate_allocation_insert_race(self):
        """
        Two concurrent threads attempt to allocate the exact same OfferVersion to an Award.
        UniqueConstraint guarantees at most one succeeds.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)

        barrier = threading.Barrier(2)
        results = {}

        def thread_add(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                alloc = add_award_allocation(
                    award.id,
                    offer_version_id=self.v1.id,
                    awarded_quantity=Decimal("250.000"),
                    expected_version=award.version,
                    actor=actor,
                )
                results[thread_id] = ("SUCCESS", alloc)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_add, args=(1, self.buyer_user1))
        t2 = threading.Thread(target=thread_add, args=(2, self.buyer_user2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [k for k, v in results.items() if v[0] == "SUCCESS"]
        errors = [k for k, v in results.items() if v[0] == "ERROR"]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(AwardAllocation.objects.filter(award=award).count(), 1)
