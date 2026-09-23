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
from deals.models import Deal
from deals.services import materialize_deals_from_award
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


class DealMaterializationPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Multi-threaded PostgreSQL concurrency tests for Deal materialization:
    Proves that concurrent materialization requests on the same finalized Award:
    - produce exactly one Deal per AwardAllocation;
    - produce zero duplicate deals;
    - avoid leaking IntegrityError or 500 exceptions;
    - return coherent, identical Deal sets to all callers.
    """

    def setUp(self):
        super().setUp()

        # Commodity & Published Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_conc_{uuid.uuid4().hex[:6]}",
            name_fa="قیر همزمانی",
            name_en="Concurrency Bitumen",
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
            email=f"buyer1_{uuid.uuid4().hex[:4]}@concbuyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user1,
            role=OrganizationMembership.OrganizationRole.OWNER,
            is_active=True,
        )

        self.buyer_user2 = User.objects.create_user(
            email=f"buyer2_{uuid.uuid4().hex[:4]}@concbuyer.com",
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
            email=f"supplier_{uuid.uuid4().hex[:4]}@concsupplier.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # Broker Organization
        self.broker_org = Organization.objects.create(
            name=f"Broker Conc Org {uuid.uuid4().hex[:4]}",
            country="AE",
            is_active=True,
        )
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        OrganizationVerification.objects.create(
            organization=self.broker_org,
            status=VerificationStatus.VERIFIED,
            version=1,
        )
        self.broker_user = User.objects.create_user(
            email=f"broker_{uuid.uuid4().hex[:4]}@concbroker.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
            is_active=True,
        )

        # RFQ
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

        # Supplier Offer
        self.supplier_offer = create_offer(
            actor=self.supplier_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.SUPPLIER,
            offering_organization=self.supplier_org,
        )
        self.supplier_v1 = create_draft_offer_version(
            actor=self.supplier_user,
            offer=self.supplier_offer.id,
            offered_quantity=Decimal("600.000"),
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

        # Broker Offer
        self.broker_offer = create_offer(
            actor=self.broker_user,
            rfq=self.rfq,
            offeror_role=OfferorRole.BROKER,
            offering_organization=self.broker_org,
        )
        self.broker_v1 = create_draft_offer_version(
            actor=self.broker_user,
            offer=self.broker_offer.id,
            offered_quantity=Decimal("400.000"),
            quantity_unit="MT",
            unit_price=Decimal("345.00"),
            currency="USD",
            specifications={"penetration_grade": "60/70"},
            payment_terms="TT 30 days",
            delivery_terms="CIF",
            incoterm="CIF",
            valid_until=timezone.now() + timezone.timedelta(days=14),
            logistics_cost_status=LogisticsCostStatus.INCLUDED_IN_PRICE,
        )
        self.broker_offer.refresh_from_db()
        self.broker_v1 = submit_internal_offer_version(
            actor=self.broker_user,
            offer_version=self.broker_v1.id,
            expected_version=self.broker_offer.aggregate_version,
        )
        self.broker_offer.refresh_from_db()

    def test_concurrent_materialization_single_award_race(self):
        """
        Two buyer actors simultaneously materialize the same finalized single-allocation Award.
        PostgreSQL row locking and OneToOne DB constraint guarantee:
        - exactly one Deal is created;
        - zero duplicate deals;
        - both callers receive coherent results without 500 error.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("600.000"),
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

        # Both threads should succeed without IntegrityError
        errors = [v for v in results.values() if v[0] == "ERROR"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {results}")

        successes = [v for v in results.values() if v[0] == "SUCCESS"]
        self.assertEqual(len(successes), 2)

        # Database state: exactly 1 Deal exists for this award
        self.assertEqual(Deal.objects.filter(award=finalized_award).count(), 1)

        deals_t1 = successes[0][1]
        deals_t2 = successes[1][1]

        self.assertEqual(len(deals_t1), 1)
        self.assertEqual(len(deals_t2), 1)
        self.assertEqual(deals_t1[0].id, deals_t2[0].id)

    def test_concurrent_materialization_multi_award_race(self):
        """
        Two actors concurrently materialize a multi-allocation Award (2 allocations).
        Guarantees:
        - exactly 2 Deals exist in DB;
        - zero duplicates;
        - both callers receive the exact same 2 Deals.
        """
        award = create_draft_award(self.rfq.id, actor=self.buyer_user1)
        add_award_allocation(
            award.id,
            offer_version_id=self.supplier_v1.id,
            awarded_quantity=Decimal("600.000"),
            quantity_unit="MT",
            expected_version=award.version,
            actor=self.buyer_user1,
        )
        award.refresh_from_db()
        add_award_allocation(
            award.id,
            offer_version_id=self.broker_v1.id,
            awarded_quantity=Decimal("400.000"),
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

        self.assertEqual(Deal.objects.filter(award=finalized_award).count(), 2)

        deals_t1 = results[1][1]
        deals_t2 = results[2][1]
        self.assertEqual([d.id for d in deals_t1], [d.id for d in deals_t2])
