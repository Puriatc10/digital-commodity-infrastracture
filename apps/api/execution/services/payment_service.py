from typing import Any, Optional, Union
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from execution.enums import ExecutionStatus, PaymentStatus
from execution.exceptions import (
    CrossObjectIntegrityError,
    ExecutionClosedError,
    ExecutionNotFoundError,
    ExecutionValidationError,
    InvalidPaymentTransitionError,
    StaleVersionError,
)
from execution.models.execution import Execution
from execution.models.payment import ExecutionPayment
from execution.permissions import (
    check_execution_read_access,
    check_payment_mutation_authority,
)
from offers.enums import LogisticsCostStatus


def _validate_expected_version(current: int, expected: Any) -> None:
    """Validate optimistic concurrency expected_version."""
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ExecutionValidationError("expected_version must be a positive integer.")
    if current != expected:
        raise StaleVersionError(
            f"Optimistic concurrency conflict: expected_version={expected}, current version={current}."
        )


@transaction.atomic
def get_or_create_execution_payment(
    execution_id: Union[UUID, str],
    *,
    actor: Any = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionPayment:
    """
    Idempotently retrieve or initialize the ExecutionPayment record for an Execution.

    Invariants (Epic 10 Contract §50–§59, T1006):
    - Exactly 1 ExecutionPayment per Execution.
    - Idempotent: repeated calls return existing instance.
    - Expected amount and currency are derived strictly from immutable Deal commercial truth (DealTermsSnapshot).
    - Free text payment terms are NEVER parsed into fake due dates; expected_at remains null unless deterministically known.
    - Preserves honest unknown semantics.
    - Checks read authorization if actor is provided.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if actor is not None:
        check_execution_read_access(actor, execution)

    deal = execution.deal
    terms = getattr(deal, "terms_snapshot", None)

    expected_amount = None
    currency = ""
    if terms:
        currency = terms.currency or ""
        if terms.logistics_cost_status in (
            LogisticsCostStatus.INCLUDED_IN_PRICE,
            LogisticsCostStatus.NOT_APPLICABLE,
        ):
            expected_amount = terms.product_cost_snapshot
        elif terms.logistics_cost_status == LogisticsCostStatus.KNOWN_SEPARATE:
            if terms.logistics_cost_amount is not None:
                expected_amount = terms.product_cost_snapshot + terms.logistics_cost_amount
            else:
                expected_amount = terms.product_cost_snapshot
        else:
            # When logistics cost is UNKNOWN, total commercial payable amount is not deterministically known
            expected_amount = None

    payment, _ = ExecutionPayment.objects.select_for_update().get_or_create(
        execution=execution,
        defaults={
            "status": PaymentStatus.EXPECTED,
            "expected_amount": expected_amount,
            "currency": currency,
            "expected_at": None,
            "version": 1,
        },
    )
    return payment


@transaction.atomic
def report_payment(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionPayment:
    """
    Buyer/Seller/Operator operational action: report payment progress (Epic 10 Contract §54, §56, §57, T1006).

    Invariants:
    - Preconditions checked under select_for_update row lock:
        1. Execution must be OPEN.
        2. Expected version matches current payment version (raises StaleVersionError).
        3. Cross-object references belong to the same Execution and Deal.
        4. Actor has verified operational mutation authority (Buyer, Seller, or Operator/Admin).
        5. Current status must be EXPECTED.
    - Transitions status: EXPECTED -> REPORTED only.
    - Server derives reported_by = actor and reported_at = server now. Client cannot forge them.
    - Once REPORTED, reported_by and reported_at are historically immutable.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot report payment on an execution that is already CLOSED.")

    check_payment_mutation_authority(actor, execution, "REPORT")

    payment = get_or_create_execution_payment(execution.id, deal_id=deal_id)
    payment = ExecutionPayment.objects.select_for_update().get(pk=payment.pk)

    _validate_expected_version(payment.version, expected_version)

    if payment.status == PaymentStatus.REPORTED:
        raise InvalidPaymentTransitionError("Payment is already in REPORTED status.")
    if payment.status == PaymentStatus.CONFIRMED:
        raise InvalidPaymentTransitionError("Payment is already CONFIRMED.")
    if payment.status != PaymentStatus.EXPECTED:
        raise InvalidPaymentTransitionError(
            f"Cannot report payment from status '{payment.status}'. Only EXPECTED status can be reported."
        )

    now = timezone.now()
    payment.status = PaymentStatus.REPORTED
    payment.reported_at = now
    payment.reported_by = actor
    if reference is not None:
        payment.reference = reference.strip()
    if notes is not None:
        payment.notes = notes
    payment.version += 1
    payment.save()

    return payment


@transaction.atomic
def confirm_payment(
    execution_id: Union[UUID, str],
    *,
    expected_version: int,
    actor: Any,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    deal_id: Optional[Union[UUID, str]] = None,
) -> ExecutionPayment:
    """
    Operator/Admin operational action: authoritatively confirm payment (Epic 10 Contract §55, §56, §57, T1006).

    Invariants:
    - Preconditions checked under select_for_update row lock:
        1. Execution must be OPEN.
        2. Expected version matches current payment version (raises StaleVersionError).
        3. Cross-object references belong to the same Execution and Deal.
        4. Actor has verified operational mutation authority (Operator or Admin ONLY).
        5. Current status must be REPORTED. Direct EXPECTED -> CONFIRMED is forbidden.
    - Transitions status: REPORTED -> CONFIRMED only.
    - Server derives confirmed_by = actor and confirmed_at = server now. Client cannot forge them.
    - Once CONFIRMED, confirmed_by and confirmed_at are historically immutable.
    - Terminal state: CONFIRMED cannot be reversed or reopened.
    """
    try:
        execution = (
            Execution.objects.select_for_update()
            .get(pk=execution_id)
        )
    except Execution.DoesNotExist:
        raise ExecutionNotFoundError(f"Execution '{execution_id}' does not exist.")

    if deal_id is not None and execution.deal_id != deal_id:
        raise CrossObjectIntegrityError("Execution does not belong to the referenced Deal.")

    if execution.status == ExecutionStatus.CLOSED:
        raise ExecutionClosedError("Cannot confirm payment on an execution that is already CLOSED.")

    check_payment_mutation_authority(actor, execution, "CONFIRM")

    payment = get_or_create_execution_payment(execution.id, deal_id=deal_id)
    payment = ExecutionPayment.objects.select_for_update().get(pk=payment.pk)

    _validate_expected_version(payment.version, expected_version)

    if payment.status == PaymentStatus.EXPECTED:
        raise InvalidPaymentTransitionError(
            "Payment must be in REPORTED status to confirm. Direct transition from EXPECTED to CONFIRMED is forbidden."
        )
    if payment.status == PaymentStatus.CONFIRMED:
        raise InvalidPaymentTransitionError("Payment is already CONFIRMED.")
    if payment.status != PaymentStatus.REPORTED:
        raise InvalidPaymentTransitionError(
            f"Cannot confirm payment from status '{payment.status}'. Only REPORTED status can be confirmed."
        )

    now = timezone.now()
    payment.status = PaymentStatus.CONFIRMED
    payment.confirmed_at = now
    payment.confirmed_by = actor
    if reference is not None:
        payment.reference = reference.strip()
    if notes is not None:
        payment.notes = notes
    payment.version += 1
    payment.save()

    return payment
