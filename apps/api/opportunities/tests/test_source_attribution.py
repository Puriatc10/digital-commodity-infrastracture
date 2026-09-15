from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from commodities.models import CommodityDefinition
from identity.models import SystemRoleAssignment
from opportunities.models import (
    ExternalCounterparty,
    Opportunity,
    OpportunityDirection,
    OpportunitySource,
    OpportunityStatus,
)
from opportunities.services import create_opportunity, update_opportunity
from organizations.models import (
    Organization,
    OrganizationCapability,
    OrganizationMembership,
)

User = get_user_model()


class OpportunitySourceAndBrokerTests(TestCase):
    """
    Canonical domain, constraint, referential integrity, and API test suite
    for T0605 — Opportunity Source & Broker Attribution.
    """

    def setUp(self):
        self.client = APIClient()

        # Product System Roles
        self.operator_user = User.objects.create_user(
            email="operator@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.operator_user,
            role=SystemRoleAssignment.SystemRole.OPERATOR,
        )

        self.admin_user = User.objects.create_user(
            email="admin@platform.local",
            password="testpassword123",
        )
        SystemRoleAssignment.objects.create(
            user=self.admin_user,
            role=SystemRoleAssignment.SystemRole.ADMIN,
        )

        # Buyer Organization & User
        self.buyer_org = Organization.objects.create(name="Global Buyer LLC", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        self.buyer_user = User.objects.create_user(
            email="buyer@globalbuyer.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.buyer_org,
            user=self.buyer_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        # Supplier Organization & User
        self.supplier_org = Organization.objects.create(name="Apex Refineries Co", country="IR")
        OrganizationCapability.objects.create(
            organization=self.supplier_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        self.supplier_user = User.objects.create_user(
            email="supplier@apex.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.supplier_org,
            user=self.supplier_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        # Dedicated Broker Organization & User
        self.broker_org = Organization.objects.create(name="Bosphorus Trade Brokers", country="TR")
        OrganizationCapability.objects.create(
            organization=self.broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )
        self.broker_user = User.objects.create_user(
            email="broker@bosphorus.com",
            password="testpassword123",
        )
        OrganizationMembership.objects.create(
            organization=self.broker_org,
            user=self.broker_user,
            role=OrganizationMembership.OrganizationRole.MANAGER,
        )

        # Multi-Capability Organizations
        self.buyer_and_broker_org = Organization.objects.create(name="Dual Buyer-Broker Corp", country="AE")
        OrganizationCapability.objects.create(
            organization=self.buyer_and_broker_org,
            capability=OrganizationCapability.CapabilityType.BUYER,
        )
        OrganizationCapability.objects.create(
            organization=self.buyer_and_broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        self.supplier_and_broker_org = Organization.objects.create(name="Dual Supplier-Broker Corp", country="OM")
        OrganizationCapability.objects.create(
            organization=self.supplier_and_broker_org,
            capability=OrganizationCapability.CapabilityType.SUPPLIER,
        )
        OrganizationCapability.objects.create(
            organization=self.supplier_and_broker_org,
            capability=OrganizationCapability.CapabilityType.BROKER,
        )

        # External Counterparty (off-platform)
        self.external_cp = ExternalCounterparty.objects.create(
            company_name="Gulf Trading FZE",
            contact_name="Tariq Mansour",
            email="tariq@gulftrading.ae",
            geography="Jebel Ali, UAE",
        )

        # Commodity
        self.commodity = CommodityDefinition.objects.create(
            code="bitumen_vg30",
            name_en="Bitumen VG-30",
            name_fa="قیر VG-30",
        )

        # Django Staff & Superuser without Product System Role
        self.staff_only_user = User.objects.create_user(
            email="staff@platform.local",
            password="testpassword123",
            is_staff=True,
        )
        self.superuser_only_user = User.objects.create_superuser(
            email="superuser@platform.local",
            password="testpassword123",
        )

        self._seq = 0

    def _next_identifier(self) -> str:
        self._seq += 1
        return f"OPP-2026-{self._seq:06d}"

    # =========================================================================
    # 1. Sources Validation (All 6 valid, invalid rejected)
    # =========================================================================

    def test_all_six_approved_sources_accepted(self):
        """Verify all six approved sources persist cleanly."""
        sources = [
            (OpportunitySource.BROKER_REFERRAL, self.broker_org),
            (OpportunitySource.OPERATOR_SOURCING, None),
            (OpportunitySource.BUYER_REFERRAL, None),
            (OpportunitySource.SUPPLIER_REFERRAL, None),
            (OpportunitySource.EXISTING_RELATIONSHIP, None),
            (OpportunitySource.INBOUND_LEAD, None),
        ]

        for src, broker in sources:
            with self.subTest(source=src):
                opp = Opportunity(
                    identifier=self._next_identifier(),
                    direction=OpportunityDirection.SUPPLY,
                    organization=self.supplier_org,
                    source=src,
                    broker=broker,
                )
                opp.clean()
                opp.save()
                self.assertEqual(opp.source, src)
                if broker:
                    self.assertEqual(opp.broker, broker)
                else:
                    self.assertIsNone(opp.broker)

    def test_invalid_source_rejected_in_model_clean(self):
        """Confirm that unapproved source value raises ValidationError."""
        opp = Opportunity(
            identifier=self._next_identifier(),
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            source="unapproved_source",
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("source", ctx.exception.message_dict)

    def test_invalid_source_rejected_by_db_check_constraint(self):
        """Confirm that unapproved source violates PostgreSQL CheckConstraint."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier=self._next_identifier(),
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.supplier_org,
                        source="forbidden_source_value",
                    )
                ])

    # =========================================================================
    # 2. Broker Capability Invariants
    # =========================================================================

    def test_broker_referral_with_valid_broker_accepted(self):
        """Broker Referral with valid Broker Organization succeeds."""
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        self.assertEqual(opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(opp.broker_id, self.broker_org.id)

    def test_broker_referral_missing_broker_rejected_in_model(self):
        """Broker Referral without a broker raises ValidationError in clean()."""
        opp = Opportunity(
            identifier=self._next_identifier(),
            direction=OpportunityDirection.DEMAND,
            organization=self.buyer_org,
            source=OpportunitySource.BROKER_REFERRAL,
            broker=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("broker", ctx.exception.message_dict)

    def test_broker_referral_missing_broker_rejected_by_db_check_constraint(self):
        """Broker Referral with NULL broker violates check_opportunity_broker_source_consistency."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier=self._next_identifier(),
                        direction=OpportunityDirection.DEMAND,
                        organization=self.buyer_org,
                        source=OpportunitySource.BROKER_REFERRAL,
                        broker=None,
                    )
                ])

    def test_buyer_only_organization_rejected_as_broker(self):
        """Organization possessing only Buyer capability cannot be attributed as Broker."""
        with self.assertRaises(ValidationError) as ctx:
            create_opportunity(
                direction=OpportunityDirection.SUPPLY,
                organization_id=self.supplier_org.id,
                source=OpportunitySource.BROKER_REFERRAL,
                broker_id=self.buyer_org.id,
            )
        self.assertIn("broker", str(ctx.exception))

    def test_supplier_only_organization_rejected_as_broker(self):
        """Organization possessing only Supplier capability cannot be attributed as Broker."""
        with self.assertRaises(ValidationError) as ctx:
            create_opportunity(
                direction=OpportunityDirection.DEMAND,
                organization_id=self.buyer_org.id,
                source=OpportunitySource.BROKER_REFERRAL,
                broker_id=self.supplier_org.id,
            )
        self.assertIn("broker", str(ctx.exception))

    def test_buyer_and_broker_organization_accepted(self):
        """Organization with Buyer and Broker capabilities is accepted as Broker."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.buyer_and_broker_org.id,
        )
        self.assertEqual(opp.broker_id, self.buyer_and_broker_org.id)

    def test_supplier_and_broker_organization_accepted(self):
        """Organization with Supplier and Broker capabilities is accepted as Broker."""
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.supplier_and_broker_org.id,
        )
        self.assertEqual(opp.broker_id, self.supplier_and_broker_org.id)

    # =========================================================================
    # 3. Trade Direction Genericity
    # =========================================================================

    def test_supply_opportunity_with_broker_referral(self):
        """Supply Opportunity + Broker Referral is valid."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        self.assertEqual(opp.direction, OpportunityDirection.SUPPLY)
        self.assertEqual(opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(opp.broker, self.broker_org)

    def test_demand_opportunity_with_broker_referral(self):
        """Demand Opportunity + Broker Referral is valid."""
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        self.assertEqual(opp.direction, OpportunityDirection.DEMAND)
        self.assertEqual(opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(opp.broker, self.broker_org)

    # =========================================================================
    # 4. External Counterparty Scenario
    # =========================================================================

    def test_external_supply_lead_with_broker_referral(self):
        """
        ExternalCounterparty + Direction Supply + Broker Referral + Internal Broker Org.
        No external counterparty onboarding or user account creation is required.
        """
        initial_user_count = User.objects.count()
        initial_org_count = Organization.objects.count()

        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            external_counterparty_id=self.external_cp.id,
            commodity_id=self.commodity.id,
            quantity=Decimal("1500.000"),
            unit="MT",
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        self.assertEqual(opp.direction, OpportunityDirection.SUPPLY)
        self.assertEqual(opp.external_counterparty_id, self.external_cp.id)
        self.assertIsNone(opp.organization)
        self.assertEqual(opp.source, OpportunitySource.BROKER_REFERRAL)
        self.assertEqual(opp.broker_id, self.broker_org.id)

        # Regression: absolutely zero user accounts or organizations created
        self.assertEqual(User.objects.count(), initial_user_count)
        self.assertEqual(Organization.objects.count(), initial_org_count)

    # =========================================================================
    # 5. Non-Broker Source Consistency & Stale Attribution Prevention
    # =========================================================================

    def test_non_broker_source_with_broker_rejected_in_model(self):
        """Non-Broker source with broker attribution raises ValidationError."""
        opp = Opportunity(
            identifier=self._next_identifier(),
            direction=OpportunityDirection.SUPPLY,
            organization=self.supplier_org,
            source=OpportunitySource.OPERATOR_SOURCING,
            broker=self.broker_org,
        )
        with self.assertRaises(ValidationError) as ctx:
            opp.clean()
        self.assertIn("broker", ctx.exception.message_dict)

    def test_non_broker_source_with_broker_rejected_by_db_check_constraint(self):
        """Non-Broker source with broker attribution violates check_opportunity_broker_source_consistency."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.bulk_create([
                    Opportunity(
                        identifier=self._next_identifier(),
                        direction=OpportunityDirection.SUPPLY,
                        organization=self.supplier_org,
                        source=OpportunitySource.OPERATOR_SOURCING,
                        broker=self.broker_org,
                    )
                ])

    def test_update_from_broker_referral_to_non_broker_prevents_stale_broker(self):
        """Changing source to non-broker source without clearing broker is rejected."""
        opp = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        # Attempt to change source to Inbound Lead while retaining existing broker
        with self.assertRaises(ValidationError) as ctx:
            update_opportunity(
                opp,
                data={"source": OpportunitySource.INBOUND_LEAD},
            )
        self.assertIn("broker", str(ctx.exception))

        # Explicitly clearing broker_id alongside source succeeds
        updated_opp = update_opportunity(
            opp,
            data={
                "source": OpportunitySource.INBOUND_LEAD,
                "broker_id": None,
            },
        )
        self.assertEqual(updated_opp.source, OpportunitySource.INBOUND_LEAD)
        self.assertIsNone(updated_opp.broker_id)

    # =========================================================================
    # 6. Referential Integrity (Historical-safe FK with models.PROTECT)
    # =========================================================================

    def test_attributed_broker_deletion_blocked_by_protect(self):
        """Deleting an attributed Broker Organization raises ProtectedError."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        with self.assertRaises(ProtectedError):
            self.broker_org.delete()

        # Verify opportunity and attribution remain completely intact
        opp.refresh_from_db()
        self.assertEqual(opp.broker_id, self.broker_org.id)

    # =========================================================================
    # 7. Authorization Matrix
    # =========================================================================

    def test_operator_authorized_to_create_update_read(self):
        """Operator has full Opportunity Desk mutation and read authority."""
        self.client.force_authenticate(user=self.operator_user)

        # Create
        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Supply",
                "organization_id": str(self.supplier_org.id),
                "source": "broker_referral",
                "broker_id": str(self.broker_org.id),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        opp_id = res.data["id"]

        # Read
        res = self.client.get(f"/api/opportunities/opportunities/{opp_id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["source"], "broker_referral")
        self.assertEqual(res.data["broker"]["id"], str(self.broker_org.id))

        # Update
        res = self.client.patch(
            f"/api/opportunities/opportunities/{opp_id}/",
            {"source": "operator_sourcing", "broker_id": None},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["source"], "operator_sourcing")
        self.assertIsNone(res.data["broker"])

    def test_product_admin_authorized(self):
        """Product Admin has Opportunity Desk create, read, and update authority."""
        self.client.force_authenticate(user=self.admin_user)

        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Demand",
                "organization_id": str(self.buyer_org.id),
                "source": "inbound_lead",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_buyer_user_denied(self):
        """Buyer user is denied access (403 Forbidden)."""
        self.client.force_authenticate(user=self.buyer_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post("/api/opportunities/opportunities/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_supplier_user_denied(self):
        """Supplier user is denied access (403 Forbidden)."""
        self.client.force_authenticate(user=self.supplier_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post("/api/opportunities/opportunities/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_broker_user_denied(self):
        """Broker user is denied Opportunity Desk access (403 Forbidden)."""
        self.client.force_authenticate(user=self.broker_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post("/api/opportunities/opportunities/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_referenced_broker_user_denied_write_and_read(self):
        """
        Referenced Broker organization user does NOT receive Opportunity Desk permissions.
        Attribution grants zero mutation or desk read rights.
        """
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        self.client.force_authenticate(user=self.broker_user)

        # Denied read
        res = self.client.get(f"/api/opportunities/opportunities/{opp.id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Denied update
        res = self.client.patch(
            f"/api/opportunities/opportunities/{opp.id}/",
            {"notes": "Broker attempt to edit"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_staff_only_denied(self):
        """Django staff=True alone without Product System Role is denied (403 Forbidden)."""
        self.client.force_authenticate(user=self.staff_only_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_django_superuser_only_denied(self):
        """Django superuser=True alone without Product System Role is denied (403 Forbidden)."""
        self.client.force_authenticate(user=self.superuser_only_user)
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_denied(self):
        """Unauthenticated user is denied (401 or 403)."""
        res = self.client.get("/api/opportunities/opportunities/")
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # =========================================================================
    # 8. API Serializers, Normalization, Projections & Mass-Assignment
    # =========================================================================

    def test_api_source_normalization_and_display_labels(self):
        """
        API accepts canonical enum values, display labels, or uppercase representations,
        normalizing safely to persisted enum values.
        """
        self.client.force_authenticate(user=self.operator_user)

        cases = [
            ("Broker Referral", self.broker_org.id, "broker_referral"),
            ("BROKER_REFERRAL", self.broker_org.id, "broker_referral"),
            ("Operator Sourcing", None, "operator_sourcing"),
            ("OPERATOR_SOURCING", None, "operator_sourcing"),
            ("buyer_referral", None, "buyer_referral"),
            ("Supplier Referral", None, "supplier_referral"),
            ("Existing Relationship", None, "existing_relationship"),
            ("Inbound Lead", None, "inbound_lead"),
        ]

        for input_source, broker_id, expected_source in cases:
            with self.subTest(input_source=input_source):
                payload = {
                    "direction": "Supply",
                    "organization_id": str(self.supplier_org.id),
                    "source": input_source,
                }
                if broker_id:
                    payload["broker_id"] = str(broker_id)

                res = self.client.post("/api/opportunities/opportunities/", payload, format="json")
                self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
                self.assertEqual(res.data["source"], expected_source)
                if broker_id:
                    self.assertEqual(res.data["broker"]["id"], str(broker_id))
                    self.assertEqual(res.data["broker"]["name"], self.broker_org.name)
                    self.assertEqual(res.data["broker"]["country"], self.broker_org.country)
                else:
                    self.assertIsNone(res.data["broker"])

    def test_api_invalid_source_rejected(self):
        """API rejects invalid source choice with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Supply",
                "organization_id": str(self.supplier_org.id),
                "source": "fabricated_source",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("source", res.data)

    def test_api_missing_broker_for_broker_referral_rejected(self):
        """API rejects Broker Referral without broker_id with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Supply",
                "organization_id": str(self.supplier_org.id),
                "source": "broker_referral",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("broker_id", res.data)

    def test_api_non_broker_source_with_broker_rejected(self):
        """API rejects non-broker source with broker_id with 400 Bad Request."""
        self.client.force_authenticate(user=self.operator_user)
        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Supply",
                "organization_id": str(self.supplier_org.id),
                "source": "operator_sourcing",
                "broker_id": str(self.broker_org.id),
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("broker_id", res.data)

    def test_api_safe_broker_projection_shape(self):
        """API read projection returns only safe Broker identity (id, name, country)."""
        opp = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )

        self.client.force_authenticate(user=self.operator_user)
        res = self.client.get(f"/api/opportunities/opportunities/{opp.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        broker_data = res.data["broker"]
        self.assertIsNotNone(broker_data)
        self.assertEqual(broker_data["id"], str(self.broker_org.id))
        self.assertEqual(broker_data["name"], "Bosphorus Trade Brokers")
        self.assertEqual(broker_data["country"], "TR")
        # Ensure sensitive / internal org details are not projected
        self.assertNotIn("memberships", broker_data)
        self.assertNotIn("created_at", broker_data)

    def test_api_mass_assignment_guards(self):
        """Clients cannot tamper with status, identifier, or timestamps via create/update."""
        self.client.force_authenticate(user=self.operator_user)

        res = self.client.post(
            "/api/opportunities/opportunities/",
            {
                "direction": "Supply",
                "organization_id": str(self.supplier_org.id),
                "source": "operator_sourcing",
                "status": "Qualified",
                "identifier": "OPP-9999-999999",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], OpportunityStatus.CAPTURED)
        self.assertNotEqual(res.data["identifier"], "OPP-9999-999999")
        opp_id = res.data["id"]

        # Attempt to alter identifier and status via PATCH
        res = self.client.patch(
            f"/api/opportunities/opportunities/{opp_id}/",
            {
                "status": "Qualified",
                "identifier": "OPP-8888-888888",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], OpportunityStatus.CAPTURED)
        self.assertNotEqual(res.data["identifier"], "OPP-8888-888888")

    def test_api_filter_by_source_and_broker(self):
        """API supports filtering opportunity list by source and broker."""
        self.client.force_authenticate(user=self.operator_user)

        opp_broker = create_opportunity(
            direction=OpportunityDirection.SUPPLY,
            organization_id=self.supplier_org.id,
            source=OpportunitySource.BROKER_REFERRAL,
            broker_id=self.broker_org.id,
        )
        opp_operator = create_opportunity(
            direction=OpportunityDirection.DEMAND,
            organization_id=self.buyer_org.id,
            source=OpportunitySource.OPERATOR_SOURCING,
        )

        # Filter by source=broker_referral
        res = self.client.get("/api/opportunities/opportunities/?source=broker_referral")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in res.data["results"]]
        self.assertIn(str(opp_broker.id), ids)
        self.assertNotIn(str(opp_operator.id), ids)

        # Filter by broker UUID
        res = self.client.get(f"/api/opportunities/opportunities/?broker={self.broker_org.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in res.data["results"]]
        self.assertIn(str(opp_broker.id), ids)
        self.assertNotIn(str(opp_operator.id), ids)
