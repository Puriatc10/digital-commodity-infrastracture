from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from execution.enums import ExecutionStatus, TransportMode
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionPermissionDeniedError,
)
from execution.models.logistics import ExecutionLogistics
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    create_or_get_execution_for_deal,
    record_delivery,
    record_loading,
    schedule_loading,
    update_eta,
    update_logistics_cost,
    update_transport,
)
from execution.tests.base import BaseExecutionTestCase


class LogisticsAuthorizationTests(BaseExecutionTestCase):
    """
    Tests for side-authority, role permissions, external seller paths, and IDOR protection (Epic 10 Contract §77–§82, T1004).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.client = APIClient()

    def test_seller_authority_allowed_actions(self):
        """Seller organization non-viewer can perform all seller operational logistics actions."""
        # 1. Update transport
        update_transport(
            self.execution.id,
            expected_version=1,
            actor=self.supplier_user,
            carrier_name="FastFreight Inc",
            transport_mode=TransportMode.ROAD,
        )

        # 2. Schedule loading
        now = timezone.now()
        schedule_loading(
            self.execution.id,
            expected_version=2,
            actor=self.supplier_user,
            scheduled_loading_at=now + timezone.timedelta(days=1),
        )

        # 3. Update ETA
        update_eta(
            self.execution.id,
            expected_version=3,
            actor=self.supplier_user,
            eta=now + timezone.timedelta(days=5),
        )

        # 4. Record loading
        record_loading(
            self.execution.id,
            expected_version=4,
            actor=self.supplier_user,
            actual_loading_at=now,
        )

        # 5. Update logistics cost
        update_logistics_cost(
            self.execution.id,
            expected_version=5,
            actor=self.supplier_user,
            logistics_cost=Decimal("3200.00"),
            currency="USD",
        )

        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 6)
        self.assertEqual(logistics.carrier_name, "FastFreight Inc")

    def test_seller_denied_buyer_delivery_recording(self):
        """Seller is strictly denied from recording buyer delivery receipt."""
        now = timezone.now()
        with self.assertRaises(ExecutionPermissionDeniedError):
            record_delivery(
                self.execution.id,
                expected_version=1,
                actor=self.supplier_user,
                actual_delivery_at=now,
            )

        # Test via API
        self.client.force_authenticate(user=self.supplier_user)
        url = f"/api/execution/{self.execution.id}/logistics/record-delivery/"
        resp = self.client.post(
            url,
            {"expected_version": 1, "actual_delivery_at": now.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_buyer_authority_allowed_actions(self):
        """Buyer organization non-viewer can record actual delivery receipt."""
        now = timezone.now()
        record_delivery(
            self.execution.id,
            expected_version=1,
            actor=self.buyer_owner,
            actual_delivery_at=now,
        )

        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 2)
        self.assertEqual(logistics.actual_delivery_at, now)

    def test_buyer_denied_seller_operational_actions(self):
        """Buyer is strictly denied from seller operational logistics actions."""
        now = timezone.now()

        # Buyer cannot update transport
        with self.assertRaises(ExecutionPermissionDeniedError):
            update_transport(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                carrier_name="Unauthorized Carrier",
            )

        # Buyer cannot schedule loading
        with self.assertRaises(ExecutionPermissionDeniedError):
            schedule_loading(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                scheduled_loading_at=now,
            )

        # Buyer cannot record loading
        with self.assertRaises(ExecutionPermissionDeniedError):
            record_loading(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                actual_loading_at=now,
            )

        # Buyer cannot update ETA
        with self.assertRaises(ExecutionPermissionDeniedError):
            update_eta(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                eta=now,
            )

        # Buyer cannot update logistics cost
        with self.assertRaises(ExecutionPermissionDeniedError):
            update_logistics_cost(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                logistics_cost=Decimal("1000.00"),
                currency="USD",
            )

    def test_viewer_role_strictly_read_only(self):
        """Viewer role in buyer or seller organization is strictly read-only."""
        # Supplier viewer cannot mutate
        with self.assertRaises(ExecutionPermissionDeniedError):
            update_transport(
                self.execution.id,
                expected_version=1,
                actor=self.supplier_viewer,
                carrier_name="Viewer Carrier",
            )

        # Supplier viewer can read
        self.client.force_authenticate(user=self.supplier_viewer)
        url = f"/api/execution/{self.execution.id}/logistics/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Supplier viewer mutation via PATCH returns 403
        resp_patch = self.client.patch(
            url,
            {"expected_version": 1, "carrier_name": "Viewer Hack"},
            format="json",
        )
        self.assertEqual(resp_patch.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_and_admin_global_authority(self):
        """Platform Operator / Admin has global operational authority."""
        now = timezone.now()

        # Operator can perform seller action
        update_transport(
            self.execution.id,
            expected_version=1,
            actor=self.operator_user,
            carrier_name="Operator Carrier",
            transport_mode=TransportMode.SEA,
        )

        # Operator can perform buyer action
        record_delivery(
            self.execution.id,
            expected_version=2,
            actor=self.operator_user,
            actual_delivery_at=now,
        )

        logistics = ExecutionLogistics.objects.get(execution=self.execution)
        self.assertEqual(logistics.version, 3)

    def test_external_counterparty_seller_operator_managed(self):
        """When seller is an ExternalCounterparty, seller actions are Operator-managed; no fake account needed."""
        ext_deal = self.create_sample_deal(external_seller=True)
        ext_exec = create_or_get_execution_for_deal(
            deal_id=ext_deal.id,
            actor=self.operator_user,
        )

        now = timezone.now()

        # Regular buyer cannot update seller operational details
        with self.assertRaises(ExecutionPermissionDeniedError):
            schedule_loading(
                ext_exec.id,
                expected_version=1,
                actor=self.buyer_owner,
                scheduled_loading_at=now,
            )

        # Operator successfully manages external seller's operational logistics
        schedule_loading(
            ext_exec.id,
            expected_version=1,
            actor=self.operator_user,
            scheduled_loading_at=now,
            pickup_location="External Refinery",
        )
        ext_log = ExecutionLogistics.objects.get(execution=ext_exec)
        self.assertEqual(ext_log.version, 2)
        self.assertEqual(ext_log.pickup_location, "External Refinery")

    def test_attributed_broker_denied_read_and_mutation(self):
        """Attributed-only broker has NO operational execution authority (attribution is provenance, not permission)."""
        now = timezone.now()

        # Broker read denied
        self.client.force_authenticate(user=self.broker_user)
        url = f"/api/execution/{self.execution.id}/logistics/"
        resp_get = self.client.get(url)
        self.assertEqual(resp_get.status_code, status.HTTP_403_FORBIDDEN)

        # Broker mutation denied
        resp_post = self.client.post(
            f"/api/execution/{self.execution.id}/logistics/record-delivery/",
            {"expected_version": 1, "actual_delivery_at": now.isoformat()},
            format="json",
        )
        self.assertEqual(resp_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_execution_denial(self):
        """Cross-execution and cross-deal attacks are strictly rejected."""
        other_deal = self.create_sample_deal()
        other_exec = create_or_get_execution_for_deal(
            deal_id=other_deal.id,
            actor=self.operator_user,
        )

        # Passing mismatched deal_id raises CrossObjectIntegrityError
        with self.assertRaises(CrossObjectIntegrityError):
            update_transport(
                execution_id=self.execution.id,
                expected_version=1,
                actor=self.operator_user,
                carrier_name="Cross Attack",
                deal_id=other_deal.id,
            )

        with self.assertRaises(CrossObjectIntegrityError):
            update_transport(
                execution_id=other_exec.id,
                expected_version=1,
                actor=self.operator_user,
                carrier_name="Cross Attack 2",
                deal_id=self.deal.id,
            )

    def test_closed_execution_rejects_mutations(self):
        """Once Execution reaches CLOSED status, further logistics mutations are rejected."""
        self.execution.status = ExecutionStatus.CLOSED
        self.execution.closed_at = timezone.now()
        self.execution.save(update_fields=["status", "closed_at"])

        now = timezone.now()
        with self.assertRaises(ExecutionClosedError):
            update_transport(
                self.execution.id,
                expected_version=1,
                actor=self.operator_user,
                carrier_name="Post-close Carrier",
            )

        with self.assertRaises(ExecutionClosedError):
            record_delivery(
                self.execution.id,
                expected_version=1,
                actor=self.buyer_owner,
                actual_delivery_at=now,
            )
