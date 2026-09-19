from decimal import Decimal
import threading
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from commodities.models import (
    CommodityAttributeDefinition,
    CommodityDefinition,
    CommoditySchemaVersion,
)
from commodities.services import publish_schema
from identity.models import SystemRoleAssignment
from offers.enums import OfferorRole
from offers.exceptions import OfferConflictError
from offers.models import Offer
from offers.services import create_offer
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunityStatus,
)
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)
from trade_hub.models import RFQ, RFQStatus, RFQVisibility

User = get_user_model()


class OfferPostgreSQLConcurrencyTests(TransactionTestCase):
    """
    Real PostgreSQL multi-threaded concurrency tests verifying conditional uniqueness
    and race-condition conflict semantics (T0801).

    Verifies that simultaneous creation attempts on separate database connections
    result in exactly ONE persisted Offer, with the loser receiving OfferConflictError.
    """

    def setUp(self):
        super().setUp()

        # Commodity & Schema
        self.commodity = CommodityDefinition.objects.create(
            code=f"bitumen_conc_{uuid.uuid4().hex[:6]}",
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

        # External Counterparty & Operators
        self.external_cp = ExternalCounterparty.objects.create(
            company_name=f"External CP {uuid.uuid4().hex[:4]}",
        )
        self.operator1 = User.objects.create_user(
            email=f"op1_{uuid.uuid4().hex[:4]}@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator1,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )
        self.operator2 = User.objects.create_user(
            email=f"op2_{uuid.uuid4().hex[:4]}@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator2,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )
        self.opp_qualified = Opportunity.objects.create(
            identifier=f"OPP-{uuid.uuid4().hex[:6]}",
            direction=OpportunityDirection.SUPPLY,
            external_counterparty=self.external_cp,
            commodity=self.commodity,
            schema_version=self.schema_version,
            quantity=Decimal("500.000"),
            unit="MT",
            status=OpportunityStatus.QUALIFIED,
            created_by=self.operator1,
        )

    def test_concurrent_internal_offer_creation_exactly_one_succeeds(self):
        """
        Two concurrent threads on separate PostgreSQL connections attempt to create an Offer
        for the identical (rfq, offering_organization, SUPPLIER).
        Exactly one succeeds; the other raises OfferConflictError.
        Total persisted Offers must be exactly 1.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor):
            connection.close()  # Ensure separate thread connection
            try:
                barrier.wait()
                offer = create_offer(
                    actor=actor,
                    rfq=self.rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    offering_organization=self.supplier_org,
                )
                results[thread_id] = ("SUCCESS", offer.id)
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
        self.assertIn("SUCCESS", statuses)
        self.assertIn("ERROR", statuses)
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        error_res = [res[1] for res in results.values() if res[0] == "ERROR"][0]
        self.assertIsInstance(error_res, OfferConflictError)

        total_offers = Offer.objects.filter(
            rfq=self.rfq,
            offering_organization=self.supplier_org,
            offeror_role=OfferorRole.SUPPLIER,
        ).count()
        self.assertEqual(total_offers, 1)

    def test_concurrent_external_offer_creation_exactly_one_succeeds(self):
        """
        Two operators concurrently attempt to create an external offer
        for the identical (rfq, external_counterparty, SUPPLIER).
        Exactly one succeeds; the other raises OfferConflictError.
        Total persisted Offers must be exactly 1.
        """
        barrier = threading.Barrier(2)
        results = {}

        def thread_task(thread_id, actor):
            connection.close()
            try:
                barrier.wait()
                offer = create_offer(
                    actor=actor,
                    rfq=self.rfq,
                    offeror_role=OfferorRole.SUPPLIER,
                    external_counterparty=self.external_cp,
                    source_opportunity=self.opp_qualified,
                )
                results[thread_id] = ("SUCCESS", offer.id)
            except Exception as exc:
                results[thread_id] = ("ERROR", exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=thread_task, args=("t1", self.operator1))
        t2 = threading.Thread(target=thread_task, args=("t2", self.operator2))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = [res[0] for res in results.values()]
        self.assertIn("SUCCESS", statuses)
        self.assertIn("ERROR", statuses)
        self.assertEqual(statuses.count("SUCCESS"), 1)
        self.assertEqual(statuses.count("ERROR"), 1)

        error_res = [res[1] for res in results.values() if res[0] == "ERROR"][0]
        self.assertIsInstance(error_res, OfferConflictError)

        total_offers = Offer.objects.filter(
            rfq=self.rfq,
            external_counterparty=self.external_cp,
            offeror_role=OfferorRole.SUPPLIER,
        ).count()
        self.assertEqual(total_offers, 1)
