import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from execution.enums import PaymentStatus


class ExecutionPayment(models.Model):
    """
    Execution Payment Monitoring Aggregate (Epic 10 Contract §50–§59, T1006).

    Represents authoritative operational payment facts for an Execution instance.

    Invariants:
    - 1 Execution -> exactly 1 ExecutionPayment record (OneToOneField & unique DB constraint).
    - Commercial truth separation: DealTermsSnapshot and Deal are NEVER mutated.
      ExecutionPayment monitors payment operations around the Deal; discrepancies are historically valid.
    - Exact state machine:
        EXPECTED -> REPORTED -> CONFIRMED
      No additional payment statuses. No reverse transitions. No direct EXPECTED -> CONFIRMED.
    - Initialization: idempotent. Expected amount and currency are derived solely from reliable
      persisted Deal commercial truth (DealTermsSnapshot).
    - Free text payment terms are never parsed into fake due dates; expected_at remains null unless deterministically known.
    - Money representation: Decimal only (no float, no FX conversions).
    - Report action: server derives reported_by and reported_at. Client cannot forge them.
    - Confirm action: server derives confirmed_by and confirmed_at. Client cannot forge them.
    - Historical immutability:
      Once REPORTED: reported_by and reported_at cannot silently change.
      Once CONFIRMED: confirmed_by and confirmed_at cannot silently change.
      CONFIRMED is terminal in T1006 (no correction/reopen workflow).
    - State integrity: DB CheckConstraints and service guards strictly reject inconsistent rows:
        * EXPECTED with reported_at/by or confirmed_at/by
        * REPORTED without reported_by/at or with confirmed_at/by
        * CONFIRMED without reported metadata or confirmed metadata
    - Optimistic concurrency: mutations increment version and require expected_version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.OneToOneField(
        "execution.Execution",
        on_delete=models.CASCADE,
        related_name="payment",
        help_text="Parent execution instance (1 Execution -> max 1 ExecutionPayment).",
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.EXPECTED,
        db_index=True,
        help_text="Runtime status of this payment monitoring record (EXPECTED, REPORTED, CONFIRMED).",
    )
    expected_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Authoritative expected payment amount derived from immutable Deal commercial truth.",
    )
    currency = models.CharField(
        max_length=3,
        blank=True,
        default="",
        help_text="ISO 4217 3-letter currency code from Deal commercial snapshot.",
    )
    expected_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected payment due date/time if deterministically supported.",
    )
    reported_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when payment was reported.",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Platform user who reported the payment fact.",
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Authoritative server timestamp when payment was confirmed by Operator/Admin.",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Platform Operator/Admin user who authoritatively confirmed the payment.",
    )
    reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Operational transaction/banking reference. Operational metadata only; never stores secrets.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Operational notes. Notes do not determine payment status.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Execution Payment"
        verbose_name_plural = "Execution Payments"
        constraints = [
            models.UniqueConstraint(
                fields=["execution"],
                name="unique_execution_payment",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=PaymentStatus.values),
                name="check_valid_payment_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_payment_version",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_amount__gte=0) | models.Q(expected_amount__isnull=True),
                name="check_positive_payment_expected_amount",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=PaymentStatus.EXPECTED,
                        reported_at__isnull=True,
                        reported_by__isnull=True,
                        confirmed_at__isnull=True,
                        confirmed_by__isnull=True,
                    )
                    | models.Q(
                        status=PaymentStatus.REPORTED,
                        reported_at__isnull=False,
                        reported_by__isnull=False,
                        confirmed_at__isnull=True,
                        confirmed_by__isnull=True,
                    )
                    | models.Q(
                        status=PaymentStatus.CONFIRMED,
                        reported_at__isnull=False,
                        reported_by__isnull=False,
                        confirmed_at__isnull=False,
                        confirmed_by__isnull=False,
                    )
                ),
                name="check_payment_status_metadata_integrity",
            ),
        ]
        indexes = [
            models.Index(fields=["execution", "-created_at"], name="idx_exec_payment_created"),
            models.Index(fields=["execution", "status"], name="idx_exec_payment_status"),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        if self.expected_amount is not None and self.expected_amount < Decimal("0"):
            errors["expected_amount"] = "expected_amount cannot be negative."

        if self.currency and len(self.currency) != 3:
            errors["currency"] = "currency must be a valid 3-letter ISO-4217 code."

        # Immutability & transition rules on update
        if not self._state.adding:
            orig = ExecutionPayment.objects.filter(pk=self.pk).first()
            if orig:
                if orig.execution_id != self.execution_id:
                    errors["execution"] = "Execution payment execution reference is immutable."

                # Status transition machine (Epic 10 Contract §56, T1006)
                if orig.status == PaymentStatus.EXPECTED:
                    if self.status not in (PaymentStatus.EXPECTED, PaymentStatus.REPORTED):
                        errors["status"] = (
                            f"Invalid transition from EXPECTED to '{self.status}'. "
                            "Direct transition to CONFIRMED or other statuses is forbidden."
                        )
                elif orig.status == PaymentStatus.REPORTED:
                    if self.status not in (PaymentStatus.REPORTED, PaymentStatus.CONFIRMED):
                        errors["status"] = (
                            f"Invalid transition from REPORTED to '{self.status}'. "
                            "Reverting to EXPECTED or transitioning to other statuses is forbidden."
                        )
                elif orig.status == PaymentStatus.CONFIRMED:
                    if self.status != PaymentStatus.CONFIRMED:
                        errors["status"] = (
                            f"Invalid transition from CONFIRMED to '{self.status}'. "
                            "CONFIRMED is a terminal state and cannot be modified or reversed."
                        )

                # Historical metadata immutability (Contract §54, §55, T1006)
                if orig.status in (PaymentStatus.REPORTED, PaymentStatus.CONFIRMED):
                    if orig.reported_at != self.reported_at:
                        errors["reported_at"] = (
                            "Reported payment timestamp (reported_at) is immutable once reported."
                        )
                    if orig.reported_by_id != self.reported_by_id:
                        errors["reported_by"] = (
                            "Reported payment user (reported_by) is immutable once reported."
                        )

                if orig.status == PaymentStatus.CONFIRMED:
                    if orig.confirmed_at != self.confirmed_at:
                        errors["confirmed_at"] = (
                            "Confirmed payment timestamp (confirmed_at) is immutable once confirmed."
                        )
                    if orig.confirmed_by_id != self.confirmed_by_id:
                        errors["confirmed_by"] = (
                            "Confirmed payment user (confirmed_by) is immutable once confirmed."
                        )

        # Status and metadata integrity
        if self.status not in PaymentStatus.values:
            errors["status"] = f"Invalid payment status '{self.status}'."

        if self.status == PaymentStatus.EXPECTED:
            if self.reported_at is not None:
                errors["reported_at"] = "reported_at must be null when status is EXPECTED."
            if self.reported_by_id is not None:
                errors["reported_by"] = "reported_by must be null when status is EXPECTED."
            if self.confirmed_at is not None:
                errors["confirmed_at"] = "confirmed_at must be null when status is EXPECTED."
            if self.confirmed_by_id is not None:
                errors["confirmed_by"] = "confirmed_by must be null when status is EXPECTED."

        elif self.status == PaymentStatus.REPORTED:
            if self.reported_at is None:
                errors["reported_at"] = "reported_at is mandatory when status is REPORTED."
            if self.reported_by_id is None:
                errors["reported_by"] = "reported_by is mandatory when status is REPORTED."
            if self.confirmed_at is not None:
                errors["confirmed_at"] = "confirmed_at must be null when status is REPORTED."
            if self.confirmed_by_id is not None:
                errors["confirmed_by"] = "confirmed_by must be null when status is REPORTED."

        elif self.status == PaymentStatus.CONFIRMED:
            if self.reported_at is None:
                errors["reported_at"] = "reported_at is mandatory when status is CONFIRMED."
            if self.reported_by_id is None:
                errors["reported_by"] = "reported_by is mandatory when status is CONFIRMED."
            if self.confirmed_at is None:
                errors["confirmed_at"] = "confirmed_at is mandatory when status is CONFIRMED."
            if self.confirmed_by_id is None:
                errors["confirmed_by"] = "confirmed_by is mandatory when status is CONFIRMED."

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"Payment for Execution {self.execution_id} "
            f"(status={self.status}, amount={self.expected_amount} {self.currency}, v={self.version})"
        )
