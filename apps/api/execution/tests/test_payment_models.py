from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from deals.models import Deal, DealCostSnapshot, DealPartySnapshot, DealTermsSnapshot
from execution.enums import PaymentStatus
from execution.models.payment import ExecutionPayment
from execution.seed import seed_bitumen_workflow_v1
from execution.services import (
    confirm_payment,
    create_or_get_execution_for_deal,
    report_payment,
)
from execution.tests.base import BaseExecutionTestCase
from offers.enums import LogisticsCostStatus


class ExecutionPaymentModelTests(BaseExecutionTestCase):
    """
    Unit tests for ExecutionPayment aggregate model invariants (Epic 10 Contract §50–§59, T1006).
    """

    def setUp(self):
        super().setUp()
        self.bitumen_v1 = seed_bitumen_workflow_v1(actor=self.operator_user)
        self.deal = self.create_sample_deal()
        self.execution = create_or_get_execution_for_deal(
            deal_id=self.deal.id,
            actor=self.operator_user,
        )
        self.payment = ExecutionPayment.objects.get(execution=self.execution)

    def test_exact_statuses(self):
        """Status choices must strictly match EXPECTED, REPORTED, CONFIRMED."""
        expected = {"EXPECTED", "REPORTED", "CONFIRMED"}
        actual = set(PaymentStatus.values)
        self.assertEqual(actual, expected)

    def test_single_payment_record_per_execution(self):
        """1 Execution -> exactly 1 ExecutionPayment (1:1 constraint)."""
        with self.assertRaises((IntegrityError, ValidationError)):
            ExecutionPayment.objects.create(
                execution=self.execution,
                status=PaymentStatus.EXPECTED,
                version=1,
            )

    def test_initial_state_and_commercial_derivation(self):
        """Initial payment monitoring state is idempotently derived from Deal commercial terms."""
        self.assertEqual(self.payment.status, PaymentStatus.EXPECTED)
        self.assertEqual(self.payment.version, 1)
        self.assertIsNone(self.payment.reported_at)
        self.assertIsNone(self.payment.reported_by)
        self.assertIsNone(self.payment.confirmed_at)
        self.assertIsNone(self.payment.confirmed_by)

        terms = self.deal.terms_snapshot
        self.assertEqual(self.payment.currency, terms.currency)
        self.assertEqual(self.payment.expected_amount, terms.product_cost_snapshot)
        self.assertIsInstance(self.payment.expected_amount, Decimal)
        # expected_at is None because payment_terms free text ('LC 90 days') is not parsed into fake dates
        self.assertIsNone(self.payment.expected_at)

    def test_expected_amount_with_known_separate_logistics(self):
        """When logistics cost is KNOWN_SEPARATE, expected_amount combines product and logistics."""
        deal = self.create_sample_deal(
            logistics_cost_status=LogisticsCostStatus.KNOWN_SEPARATE,
            logistics_cost_amount=Decimal("5000.00"),
        )
        terms = deal.terms_snapshot
        self.assertEqual(terms.logistics_cost_status, LogisticsCostStatus.KNOWN_SEPARATE)
        self.assertEqual(terms.logistics_cost_amount, Decimal("5000.00"))

        # Create execution
        execution = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        payment = ExecutionPayment.objects.get(execution=execution)
        expected_total = terms.product_cost_snapshot + Decimal("5000.00")
        self.assertEqual(payment.expected_amount, expected_total)
        self.assertIsInstance(payment.expected_amount, Decimal)

    def test_reject_inconsistent_expected_with_reported_or_confirmed_fields(self):
        """EXPECTED status with reported_at, reported_by, confirmed_at, or confirmed_by is rejected."""
        now = timezone.now()

        # 1. EXPECTED with reported_at
        self.payment.reported_at = now
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("reported_at", ctx.exception.message_dict)

        # 2. EXPECTED with reported_by
        self.payment.reported_at = None
        self.payment.reported_by = self.buyer_owner
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("reported_by", ctx.exception.message_dict)

        # 3. EXPECTED with confirmed_at
        self.payment.reported_by = None
        self.payment.confirmed_at = now
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("confirmed_at", ctx.exception.message_dict)

        # 4. EXPECTED with confirmed_by
        self.payment.confirmed_at = None
        self.payment.confirmed_by = self.operator_user
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("confirmed_by", ctx.exception.message_dict)

    def test_reject_inconsistent_reported_without_reported_metadata(self):
        """REPORTED status without reported_at or reported_by is rejected."""
        now = timezone.now()
        self.payment.status = PaymentStatus.REPORTED

        # Missing both
        with self.assertRaises(ValidationError):
            self.payment.save()

        # Only reported_at
        self.payment.reported_at = now
        self.payment.reported_by = None
        with self.assertRaises(ValidationError):
            self.payment.save()

        # Only reported_by
        self.payment.reported_at = None
        self.payment.reported_by = self.buyer_owner
        with self.assertRaises(ValidationError):
            self.payment.save()

        # REPORTED with confirmed_at
        self.payment.reported_at = now
        self.payment.reported_by = self.buyer_owner
        self.payment.confirmed_at = now
        with self.assertRaises(ValidationError):
            self.payment.save()

    def test_reject_inconsistent_confirmed_without_all_metadata(self):
        """CONFIRMED status requires both reported metadata and confirmed metadata."""
        now = timezone.now()
        self.payment.status = PaymentStatus.CONFIRMED

        # Missing reported metadata
        self.payment.confirmed_at = now
        self.payment.confirmed_by = self.operator_user
        with self.assertRaises(ValidationError):
            self.payment.save()

        # Missing confirmed_by
        self.payment.reported_at = now
        self.payment.reported_by = self.buyer_owner
        self.payment.confirmed_at = now
        self.payment.confirmed_by = None
        with self.assertRaises(ValidationError):
            self.payment.save()

    def test_reject_direct_jump_expected_to_confirmed(self):
        """Direct transition from EXPECTED to CONFIRMED is strictly forbidden."""
        now = timezone.now()
        self.payment.status = PaymentStatus.CONFIRMED
        self.payment.reported_at = now
        self.payment.reported_by = self.buyer_owner
        self.payment.confirmed_at = now
        self.payment.confirmed_by = self.operator_user
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("status", ctx.exception.message_dict)
        self.assertIn("Direct transition to CONFIRMED", str(ctx.exception))

    def test_reject_reverse_transitions(self):
        """Reverse transitions (REPORTED -> EXPECTED, CONFIRMED -> REPORTED, CONFIRMED -> EXPECTED) are forbidden."""
        # 1. Move to REPORTED
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.REPORTED)

        # Attempt REPORTED -> EXPECTED
        self.payment.status = PaymentStatus.EXPECTED
        self.payment.reported_at = None
        self.payment.reported_by = None
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("status", ctx.exception.message_dict)

        # 2. Move to CONFIRMED
        confirm_payment(self.execution.id, expected_version=2, actor=self.operator_user)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CONFIRMED)

        # Attempt CONFIRMED -> REPORTED
        self.payment.status = PaymentStatus.REPORTED
        self.payment.confirmed_at = None
        self.payment.confirmed_by = None
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("status", ctx.exception.message_dict)

        # Attempt CONFIRMED -> EXPECTED
        self.payment.status = PaymentStatus.EXPECTED
        self.payment.reported_at = None
        self.payment.reported_by = None
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("status", ctx.exception.message_dict)

    def test_historical_metadata_immutability(self):
        """Once reported/confirmed, actor and timestamp fields cannot be overwritten."""
        now = timezone.now()
        report_payment(self.execution.id, expected_version=1, actor=self.buyer_owner, reference="REF-1")
        self.payment.refresh_from_db()

        orig_reported_at = self.payment.reported_at
        orig_reported_by = self.payment.reported_by

        # Attempt to change reported_at
        self.payment.reported_at = now + timezone.timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("reported_at", ctx.exception.message_dict)

        # Attempt to change reported_by
        self.payment.reported_at = orig_reported_at
        self.payment.reported_by = self.supplier_user
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("reported_by", ctx.exception.message_dict)
        self.payment.reported_by = orig_reported_by

        # Now confirm payment
        confirm_payment(self.execution.id, expected_version=2, actor=self.operator_user, reference="CONF-1")
        self.payment.refresh_from_db()

        orig_confirmed_at = self.payment.confirmed_at
        orig_confirmed_by = self.payment.confirmed_by

        # Attempt to change confirmed_at
        self.payment.confirmed_at = now + timezone.timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("confirmed_at", ctx.exception.message_dict)

        # Attempt to change confirmed_by
        self.payment.confirmed_at = orig_confirmed_at
        self.payment.confirmed_by = self.buyer_owner
        with self.assertRaises(ValidationError) as ctx:
            self.payment.save()
        self.assertIn("confirmed_by", ctx.exception.message_dict)
        self.payment.confirmed_by = orig_confirmed_by

    def test_no_deal_mutation_across_payment_lifecycle(self):
        """
        Verify Deal, DealTermsSnapshot, DealPartySnapshot, and DealCostSnapshot
        remain 100% identical after initialize, report, and confirm.
        """
        deal = self.create_sample_deal()

        def snapshot_deal():
            d = Deal.objects.get(pk=deal.pk)
            terms = list(DealTermsSnapshot.objects.filter(deal=d).values())
            parties = list(DealPartySnapshot.objects.filter(deal=d).values())
            costs = list(DealCostSnapshot.objects.filter(deal_terms_snapshot__deal=d).values())
            return {
                "id": str(d.id),
                "award_id": str(d.award_id),
                "award_allocation_id": str(d.award_allocation_id),
                "rfq_id": str(d.rfq_id),
                "offer_id": str(d.offer_id),
                "offer_version_id": str(d.offer_version_id),
                "buyer_organization_id": str(d.buyer_organization_id),
                "seller_organization_id": str(d.seller_organization_id),
                "created_at": d.created_at,
                "terms": terms,
                "parties": parties,
                "costs": costs,
            }

        initial_snapshot = snapshot_deal()

        # 1. Initialize execution + payment
        exec_inst = create_or_get_execution_for_deal(deal_id=deal.id, actor=self.operator_user)
        self.assertEqual(snapshot_deal(), initial_snapshot)

        # 2. Report payment
        report_payment(exec_inst.id, expected_version=1, actor=self.buyer_owner, reference="TXN-999")
        self.assertEqual(snapshot_deal(), initial_snapshot)

        # 3. Confirm payment
        confirm_payment(exec_inst.id, expected_version=2, actor=self.operator_user, reference="BANK-OK")
        self.assertEqual(snapshot_deal(), initial_snapshot)
