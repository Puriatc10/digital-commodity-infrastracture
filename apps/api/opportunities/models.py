import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ExternalCounterparty(models.Model):
    """
    Represents an off-platform real-world commercial counterparty recorded by an Operator.

    Critical Invariant:
        ExternalCounterparty != User
        ExternalCounterparty != Organization

    This entity does NOT create or require a platform User, Organization,
    OrganizationMembership, or OrganizationCapability row.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core commercial & contact fields (Product Specification §21)
    company_name = models.CharField(
        max_length=255,
        help_text="Display or legal entity name of the external counterparty.",
    )
    contact_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the individual representative or contact person.",
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone number for operational contact.",
    )
    email = models.EmailField(
        max_length=254,
        blank=True,
        help_text="Email address for operational contact.",
    )
    geography = models.CharField(
        max_length=255,
        blank=True,
        help_text="Country, port, or regional jurisdiction.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Free-form operational notes by the Operator.",
    )

    # Internal actor tracking (nullable: can exist without platform user)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_external_counterparties",
        help_text="Operator who recorded this external counterparty (null if unassigned/system).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "External Counterparty"
        verbose_name_plural = "External Counterparties"
        indexes = [
            models.Index(fields=["company_name"], name="idx_ext_cp_company_name"),
            models.Index(fields=["-created_at"], name="idx_ext_cp_created_at_desc"),
        ]

    def __str__(self):
        if self.contact_name:
            return f"{self.company_name} ({self.contact_name})"
        return self.company_name


class OpportunityIdentifierSequence(models.Model):
    """
    Authoritative sequence tracker for annual human-readable Opportunity references.

    Guarantees concurrency-safe sequence allocation scoped per calendar year:
    - OPP-{YEAR}-{SEQUENCE} (e.g. OPP-2026-000001, OPP-2026-000124)
    - Safe under multi-threaded and multi-process execution via row-level locks.
    - Resets to 1 each calendar year (2026 -> 1, 2, 3...; 2027 -> 1, 2, 3...).
    """

    year = models.PositiveIntegerField(
        primary_key=True,
        help_text="Calendar year for which sequence numbers are allocated.",
    )
    next_value = models.PositiveBigIntegerField(
        default=1,
        help_text="The next available sequence number for this calendar year.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Opportunity Identifier Sequence"
        verbose_name_plural = "Opportunity Identifier Sequences"

    def __str__(self):
        return f"Year {self.year}: next={self.next_value}"


class OpportunityDirection(models.TextChoices):
    SUPPLY = "Supply", "Supply"
    DEMAND = "Demand", "Demand"


class OpportunityStatus(models.TextChoices):
    CAPTURED = "Captured", "Captured"
    CONTACTED = "Contacted", "Contacted"
    QUALIFIED = "Qualified", "Qualified"
    MATCHING = "Matching", "Matching"
    CONVERTED = "Converted", "Converted"
    ON_HOLD = "On Hold", "On Hold"
    REJECTED = "Rejected", "Rejected"
    LOST = "Lost", "Lost"
    EXPIRED = "Expired", "Expired"


class OpportunitySource(models.TextChoices):
    BROKER_REFERRAL = "broker_referral", "Broker Referral"
    OPERATOR_SOURCING = "operator_sourcing", "Operator Sourcing"
    BUYER_REFERRAL = "buyer_referral", "Buyer Referral"
    SUPPLIER_REFERRAL = "supplier_referral", "Supplier Referral"
    EXISTING_RELATIONSHIP = "existing_relationship", "Existing Relationship"
    INBOUND_LEAD = "inbound_lead", "Inbound Lead"


class Opportunity(models.Model):
    """
    Foundational Opportunity aggregate for Market Discovery / Opportunity Desk.

    Represents a trade lead with a concrete trade direction (Supply or Demand)
    and a mutually exclusive counterparty (internal Organization or off-platform
    ExternalCounterparty).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable immutable reference (Spec §17: OPP-2026-000124)
    identifier = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        help_text="Human-readable immutable opportunity identifier (e.g. OPP-2026-000124).",
    )

    # Direction (Spec §17: Supply or Demand)
    direction = models.CharField(
        max_length=10,
        choices=OpportunityDirection.choices,
        help_text="Trade direction: Supply or Demand.",
    )

    # Counterparty Relationship (mutually exclusive: exactly one required)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Internal registered platform organization (mutually exclusive with external_counterparty).",
    )
    external_counterparty = models.ForeignKey(
        ExternalCounterparty,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Off-platform external counterparty (mutually exclusive with organization).",
    )

    # Commodity (generic reference, no commodity-specific branches)
    commodity = models.ForeignKey(
        "commodities.CommodityDefinition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Referenced commodity definition.",
    )
    schema_version = models.ForeignKey(
        "commodities.CommoditySchemaVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opportunities",
        help_text="Optional exact commodity schema version if dynamic specifications were recorded.",
    )
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dynamic technical specifications validated against the referenced schema version.",
    )

    # Conversion Target Links (Spec §19, Roadmap T0609)
    converted_rfq = models.OneToOneField(
        "trade_hub.RFQ",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_opportunity",
        help_text="Authoritative RFQ created from this Opportunity upon conversion.",
    )

    # Commercial & Quantity Terms
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Lead quantity (must be positive if specified).",
    )
    unit = models.CharField(
        max_length=20,
        default="MT",
        blank=True,
        help_text="Unit of measurement.",
    )
    indicative_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Indicative or target unit price.",
    )
    currency = models.CharField(
        max_length=3,
        default="USD",
        blank=True,
        help_text="ISO 4217 currency code.",
    )

    # Delivery & Geography
    delivery_window_start = models.DateField(
        null=True,
        blank=True,
        help_text="Earliest expected delivery date.",
    )
    delivery_window_end = models.DateField(
        null=True,
        blank=True,
        help_text="Latest expected delivery date.",
    )
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="Indicative payment terms.",
    )
    geography = models.CharField(
        max_length=255,
        blank=True,
        help_text="Origin/destination region, country, or port.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal operational notes.",
    )

    # Source Provenance & Broker Attribution (Spec §18, Roadmap T0605)
    source = models.CharField(
        max_length=32,
        choices=OpportunitySource.choices,
        default=OpportunitySource.OPERATOR_SOURCING,
        help_text="Authoritative origin source of the opportunity lead.",
    )
    broker = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="brokered_opportunities",
        help_text="Attributed broker organization for broker referrals.",
    )

    # Foundational Lifecycle State (T0603 owns transitions; default Captured)
    status = models.CharField(
        max_length=30,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.CAPTURED,
        help_text="Foundational lifecycle state.",
    )

    # Optimistic Concurrency Foundation
    version = models.IntegerField(
        default=1,
        help_text="Optimistic concurrency aggregate version counter.",
    )

    # Lifecycle Timestamps & Reasons
    contacted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was marked as contacted.",
    )
    qualified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was qualified.",
    )
    converted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was converted.",
    )
    held_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was put on hold.",
    )
    hold_reason = models.TextField(
        blank=True,
        help_text="Operational reason provided when putting the opportunity on hold.",
    )
    status_before_hold = models.CharField(
        max_length=30,
        blank=True,
        help_text="Persisted status prior to entering On Hold.",
    )
    rejected_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was rejected.",
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason provided when rejecting the opportunity.",
    )
    lost_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity was marked lost.",
    )
    lost_reason = models.TextField(
        blank=True,
        help_text="Reason provided when marking the opportunity as lost.",
    )
    expired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the opportunity expired.",
    )
    expiration_reason = models.TextField(
        blank=True,
        help_text="Operational reason or notes regarding expiration.",
    )

    # Internal Actor Tracking & Timestamps
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_opportunities",
        help_text="Operator who recorded this opportunity.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Opportunity"
        verbose_name_plural = "Opportunities"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(direction__in=["Supply", "Demand"]),
                name="check_valid_opportunity_direction",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(organization__isnull=False) & models.Q(external_counterparty__isnull=True))
                    | (models.Q(organization__isnull=True) & models.Q(external_counterparty__isnull=False))
                ),
                name="check_opportunity_counterparty_exclusive",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) | models.Q(quantity__isnull=True),
                name="check_positive_opportunity_quantity",
            ),
            models.CheckConstraint(
                condition=models.Q(indicative_price__gte=0) | models.Q(indicative_price__isnull=True),
                name="check_non_negative_opportunity_indicative_price",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=[c[0] for c in OpportunityStatus.choices]),
                name="check_valid_opportunity_status",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_positive_opportunity_version",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(delivery_window_end__gte=models.F("delivery_window_start"))
                    | models.Q(delivery_window_start__isnull=True)
                    | models.Q(delivery_window_end__isnull=True)
                ),
                name="check_valid_opportunity_delivery_window",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=OpportunitySource.values),
                name="check_valid_opportunity_source",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(source=OpportunitySource.BROKER_REFERRAL) & models.Q(broker__isnull=False))
                    | (~models.Q(source=OpportunitySource.BROKER_REFERRAL) & models.Q(broker__isnull=True))
                ),
                name="check_opportunity_broker_source_consistency",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(converted_rfq__isnull=True)
                    | models.Q(status=OpportunityStatus.CONVERTED)
                ),
                name="check_rfq_only_when_converted",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(direction=OpportunityDirection.DEMAND, status=OpportunityStatus.CONVERTED)
                    | models.Q(converted_rfq__isnull=False)
                ),
                name="check_demand_converted_has_rfq",
            ),
        ]
        indexes = [
            models.Index(fields=["direction"], name="idx_opp_direction"),
            models.Index(fields=["status"], name="idx_opp_status"),
            models.Index(fields=["source"], name="idx_opp_source"),
            models.Index(fields=["broker"], name="idx_opp_broker"),
            models.Index(fields=["organization"], name="idx_opp_organization"),
            models.Index(fields=["external_counterparty"], name="idx_opp_ext_counterparty"),
            models.Index(fields=["commodity"], name="idx_opp_commodity"),
            models.Index(fields=["converted_rfq"], name="idx_opp_converted_rfq"),
            models.Index(fields=["schema_version"], name="idx_opp_schema_version"),
            models.Index(fields=["-created_at"], name="idx_opp_created_at_desc"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.version is not None and self.version < 1:
            errors["version"] = "Version must be at least 1."

        if not self.identifier:
            errors["identifier"] = "Opportunity identifier is required."
        elif not self._state.adding and self.pk:
            original = Opportunity.objects.filter(pk=self.pk).values("identifier").first()
            if original and original["identifier"] and original["identifier"] != self.identifier:
                errors["identifier"] = "Opportunity identifier is immutable once created."

        if self.direction not in [OpportunityDirection.SUPPLY, OpportunityDirection.DEMAND]:
            errors["direction"] = "Direction must be either 'Supply' or 'Demand'."

        if self.source not in OpportunitySource.values:
            errors["source"] = f"Source must be one of: {', '.join(OpportunitySource.values)}."
        elif self.source == OpportunitySource.BROKER_REFERRAL:
            if not self.broker_id:
                errors["broker"] = "Broker organization is required when source is Broker Referral."
            else:
                from organizations.models import OrganizationCapability

                if not OrganizationCapability.objects.filter(
                    organization_id=self.broker_id,
                    capability=OrganizationCapability.CapabilityType.BROKER,
                ).exists():
                    errors["broker"] = "Attributed organization must possess Broker capability."
        else:
            if self.broker_id:
                errors["broker"] = "Broker organization must not be set when source is not Broker Referral."

        if self.organization_id and self.external_counterparty_id:
            errors["counterparty"] = "Opportunity cannot reference both an internal Organization and an ExternalCounterparty."
        elif not self.organization_id and not self.external_counterparty_id:
            errors["counterparty"] = "Opportunity must reference either an internal Organization or an ExternalCounterparty."

        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        if self.indicative_price is not None and self.indicative_price < 0:
            errors["indicative_price"] = "Indicative price must be non-negative."

        if self.delivery_window_start and self.delivery_window_end:
            if self.delivery_window_end < self.delivery_window_start:
                errors["delivery_window_end"] = "Delivery window end must be on or after delivery window start."

        # Converted RFQ immutability and state consistency
        if not self._state.adding and self.pk:
            orig = Opportunity.objects.filter(pk=self.pk).values("converted_rfq_id").first()
            if orig and orig["converted_rfq_id"] and self.converted_rfq_id != orig["converted_rfq_id"]:
                errors["converted_rfq"] = "Converted RFQ link is immutable once set."

        if self.converted_rfq_id and self.status != OpportunityStatus.CONVERTED:
            errors["converted_rfq"] = "Opportunity cannot reference a converted RFQ unless in Converted status."

        if self.status == OpportunityStatus.CONVERTED and self.direction == OpportunityDirection.DEMAND:
            if not self.converted_rfq_id:
                errors["converted_rfq"] = "Converted demand opportunity must reference a converted RFQ."

        # Schema version commodity consistency
        if self.schema_version_id and self.commodity_id:
            if self.schema_version.commodity_id != self.commodity_id:
                errors["schema_version"] = "Schema version does not belong to the referenced commodity."

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        if self.converted_rfq_id is not None:
            from django.db.models import ProtectedError

            raise ProtectedError(
                "Cannot delete an Opportunity that has been converted to an RFQ.",
                [self.converted_rfq],
            )
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        counterparty = self.organization.name if self.organization else str(self.external_counterparty)
        ref = self.identifier or str(self.id)
        return f"Opportunity {ref} [{self.direction}] - {counterparty}"


class ContactAttemptType(models.TextChoices):
    CALL = "CALL", "Call"
    MESSAGE = "MESSAGE", "Message"
    EMAIL = "EMAIL", "Email"
    MEETING = "MEETING", "Meeting"
    NOTE = "NOTE", "Note"


class OpportunityContactAttempt(models.Model):
    """
    Append-only interaction log for an Opportunity (Spec §22, Roadmap T0606).

    Records individual contact attempts or operational notes:
    - CALL
    - MESSAGE
    - EMAIL
    - MEETING
    - NOTE

    Invariants:
    - Strictly append-only: no updates or deletions are exposed.
    - Server-derived recorder: `recorded_by` originates from the authenticated actor.
    - Historical past interactions are permitted; future timestamps are constrained.
    - Does NOT mutate parent Opportunity lifecycle status or version.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="contact_attempts",
        help_text="Parent opportunity for this contact attempt.",
    )
    type = models.CharField(
        max_length=20,
        choices=ContactAttemptType.choices,
        help_text="Type of contact attempt: CALL, MESSAGE, EMAIL, MEETING, NOTE.",
    )
    occurred_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when the interaction took place (supports past interactions).",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_contact_attempts",
        help_text="Operator who recorded this contact attempt.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Operational notes or details regarding the interaction.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-created_at", "-id"]
        verbose_name = "Opportunity Contact Attempt"
        verbose_name_plural = "Opportunity Contact Attempts"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type__in=ContactAttemptType.values),
                name="check_valid_contact_attempt_type",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "-occurred_at", "-created_at"], name="idx_opp_cnt_opp_occ_desc"),
            models.Index(fields=["type"], name="idx_opp_cnt_type"),
            models.Index(fields=["-created_at"], name="idx_opp_cnt_created_at_desc"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.type not in ContactAttemptType.values:
            errors["type"] = f"Type must be one of: {', '.join(ContactAttemptType.values)}."

        if self.occurred_at and self.occurred_at > timezone.now() + timezone.timedelta(minutes=5):
            errors["occurred_at"] = "occurred_at cannot be in the future."

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type} on Opportunity {self.opportunity_id} at {self.occurred_at}"


class OpportunityTaskStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class OpportunityTask(models.Model):
    """
    Opportunity-specific operational follow-up task (Spec §22, Roadmap T0607).

    Represents an actionable operational task scoped to a single Opportunity:
    - Due date/time
    - Optional assignment to an internal Operator or Admin
    - Strict lifecycle: OPEN -> COMPLETED or OPEN -> CANCELLED
    - Server-derived creator and completion timestamp
    - Overdue status computed dynamically (status == OPEN and due_at < now)
    - Concurrency-safe via row-level locking during transitions
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="tasks",
        help_text="Parent opportunity for this task.",
    )
    title = models.CharField(
        max_length=255,
        help_text="Brief summary or action required for the follow-up task.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Detailed instructions or operational context for the follow-up task.",
    )
    due_at = models.DateTimeField(
        help_text="Due date and time for the follow-up task.",
    )
    status = models.CharField(
        max_length=20,
        choices=OpportunityTaskStatus.choices,
        default=OpportunityTaskStatus.OPEN,
        help_text="Current lifecycle state of the task.",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_opportunity_tasks",
        help_text="Assigned internal Operator or Product Admin.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_opportunity_tasks",
        help_text="Operator who created this task.",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the task was marked as completed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "created_at", "id"]
        verbose_name = "Opportunity Task"
        verbose_name_plural = "Opportunity Tasks"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=OpportunityTaskStatus.values),
                name="check_valid_opportunity_task_status",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(status=OpportunityTaskStatus.COMPLETED) & models.Q(completed_at__isnull=False))
                    | (~models.Q(status=OpportunityTaskStatus.COMPLETED) & models.Q(completed_at__isnull=True))
                ),
                name="check_opportunity_task_completed_at_consistency",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "due_at", "created_at"], name="idx_opp_tsk_opp_due_cr"),
            models.Index(fields=["status"], name="idx_opp_tsk_status"),
            models.Index(fields=["assigned_to"], name="idx_opp_tsk_assigned"),
            models.Index(fields=["due_at"], name="idx_opp_tsk_due_at"),
        ]

    @property
    def is_overdue(self) -> bool:
        """
        Dynamically computes whether the task is open and overdue.
        Never persisted as a stale database column.
        """
        return bool(self.status == OpportunityTaskStatus.OPEN and self.due_at and self.due_at < timezone.now())

    def clean(self):
        super().clean()
        errors = {}

        if not self.title or not self.title.strip():
            errors["title"] = "Title is required."

        if not self.due_at:
            errors["due_at"] = "Due date and time is required."

        if self.status not in OpportunityTaskStatus.values:
            errors["status"] = f"Status must be one of: {', '.join(OpportunityTaskStatus.values)}."

        if self.status == OpportunityTaskStatus.COMPLETED and not self.completed_at:
            errors["completed_at"] = "Completed task must have a completed_at timestamp."
        elif self.status != OpportunityTaskStatus.COMPLETED and self.completed_at is not None:
            errors["completed_at"] = "Non-completed task must not have a completed_at timestamp."

        if self.assigned_to_id:
            from identity.models import SystemRoleAssignment

            is_eligible = SystemRoleAssignment.objects.filter(
                user_id=self.assigned_to_id,
                role__in=[
                    SystemRoleAssignment.SystemRole.OPERATOR,
                    SystemRoleAssignment.SystemRole.ADMIN,
                ],
            ).exists()
            if not is_eligible:
                errors["assigned_to"] = "Assigned user must be an active internal Operator or Admin."

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Task '{self.title}' [{self.status}] on Opportunity {self.opportunity_id}"
