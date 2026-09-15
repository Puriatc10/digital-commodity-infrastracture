import datetime
from decimal import Decimal
from typing import Any
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from opportunities.models import (
    Opportunity,
    OpportunityIdentifierSequence,
    OpportunitySource,
)
from opportunities.services_lifecycle import (
    TERMINAL_STATUSES,
    OpportunityLifecycleService,
    convert_opportunity,
    expire_opportunity,
    mark_opportunity_contacted,
    mark_opportunity_lost,
    put_opportunity_on_hold,
    qualify_opportunity,
    reject_opportunity,
    resume_opportunity,
    start_opportunity_matching,
)
from organizations.models import Organization, OrganizationCapability

__all__ = [
    "OpportunityLifecycleService",
    "convert_opportunity",
    "expire_opportunity",
    "mark_opportunity_contacted",
    "mark_opportunity_lost",
    "put_opportunity_on_hold",
    "qualify_opportunity",
    "reject_opportunity",
    "resume_opportunity",
    "start_opportunity_matching",
    "format_opportunity_identifier",
    "allocate_opportunity_sequence",
    "allocate_opportunity_identifier",
    "validate_opportunity_source_and_broker",
    "check_opportunity_mutation_allowed",
    "create_opportunity",
    "update_opportunity",
]


def format_opportunity_identifier(year: int, sequence: int) -> str:
    """
    Constructs the canonical human-readable Opportunity reference.

    Format:
        OPP-{YEAR}-{SEQUENCE}

    Rules:
        - Exact 'OPP' prefix
        - Four-digit calendar year
        - Minimum six-digit zero-padded sequence (e.g. OPP-2026-000001, OPP-2026-000124)
        - Sequences exceeding six digits are NOT truncated (e.g. OPP-2026-1000000)
    """
    return f"OPP-{year:04d}-{sequence:06d}"


def allocate_opportunity_sequence(year: int) -> int:
    """
    Allocates the next sequence integer for the specified calendar year.

    Guarantees concurrency safety across multiple processes and threads
    using PostgreSQL row-level locking (`select_for_update`) on
    `OpportunityIdentifierSequence`.

    Sequence Semantics:
        - Separate sequence per calendar year (2026 -> 1, 2, 3...; 2027 -> 1, 2, 3...).
        - Resets to 1 at the beginning of each calendar year.

    Gap Semantics:
        If an allocated sequence number is rolled back due to subsequent
        transaction failure, that sequence integer is not reclaimed.
        Sequence gaps are normal and acceptable in transactional database systems
        to preserve high concurrency and prevent blocking bottlenecks.
    """
    while True:
        try:
            with transaction.atomic():
                seq_record = (
                    OpportunityIdentifierSequence.objects
                    .select_for_update()
                    .filter(year=year)
                    .first()
                )
                if seq_record is None:
                    # Initialize sequence record for this calendar year.
                    # next_value is initialized to 2 since 1 is returned to the caller.
                    OpportunityIdentifierSequence.objects.create(
                        year=year,
                        next_value=2,
                    )
                    return 1

                allocated = seq_record.next_value
                seq_record.next_value = allocated + 1
                seq_record.save(update_fields=["next_value", "updated_at"])
                return allocated
        except IntegrityError:
            # Concurrent initial row insertion collision on the primary key (year).
            # The inner atomic savepoint rolls back cleanly without corrupting
            # the outer transaction. The loop retries and acquires the committed row lock.
            continue


def allocate_opportunity_identifier(
    as_of: datetime.datetime | None = None,
    year: int | None = None,
) -> str:
    """
    Allocates and formats a unique Opportunity identifier.

    Year resolution:
        If `year` is not explicitly provided, it is extracted from `as_of`
        or server-side `timezone.now()`. Client-supplied years are never trusted.
    """
    if year is None:
        ref_time = as_of or timezone.now()
        year = ref_time.year

    seq = allocate_opportunity_sequence(year)
    return format_opportunity_identifier(year, seq)


def validate_opportunity_source_and_broker(
    *,
    source: str,
    broker_id: uuid.UUID | str | None = None,
) -> None:
    """
    Centralized domain validation for Opportunity source and Broker attribution.

    Invariants:
    1. Source must be one of the six approved enum values.
    2. When source == BROKER_REFERRAL:
       - broker_id is mandatory.
       - Referenced Organization must exist.
       - Referenced Organization must possess the Broker capability.
    3. When source != BROKER_REFERRAL:
       - broker_id must be None (stale broker attribution is strictly prohibited).
    """
    errors: dict[str, str] = {}

    if source not in OpportunitySource.values:
        errors["source"] = f"Source must be one of: {', '.join(OpportunitySource.values)}."
        raise ValidationError(errors)

    if source == OpportunitySource.BROKER_REFERRAL:
        if not broker_id:
            errors["broker"] = "Broker organization is required when source is Broker Referral."
        else:
            if not Organization.objects.filter(id=broker_id).exists():
                errors["broker"] = "Attributed broker organization does not exist."
            elif not OrganizationCapability.objects.filter(
                organization_id=broker_id,
                capability=OrganizationCapability.CapabilityType.BROKER,
            ).exists():
                errors["broker"] = "Attributed organization must possess Broker capability."
    else:
        if broker_id:
            errors["broker"] = "Broker organization must not be set when source is not Broker Referral."

    if errors:
        raise ValidationError(errors)


def check_opportunity_mutation_allowed(
    opportunity: Opportunity,
    field_name: str,
) -> None:
    """
    Guards Opportunity field mutation based on lifecycle state and immutability invariants.
    """
    # Immutable identifier invariant
    if field_name == "identifier":
        raise ValidationError({"identifier": "Opportunity identifier is immutable once created."})

    # Status and version are managed strictly through explicit lifecycle actions
    if field_name == "status":
        raise ValidationError({"status": "Lifecycle status cannot be modified via generic update. Use explicit lifecycle actions."})
    if field_name == "version":
        raise ValidationError({"version": "Version is managed by optimistic concurrency and cannot be directly modified."})

    # Terminal state protection: terminal opportunities cannot be generically modified
    if opportunity.status in TERMINAL_STATUSES:
        raise ValidationError({"status": f"Cannot modify Opportunity in terminal status '{opportunity.status}'."})


@transaction.atomic
def create_opportunity(
    *,
    direction: str,
    organization_id: uuid.UUID | str | None = None,
    external_counterparty_id: uuid.UUID | str | None = None,
    commodity_id: uuid.UUID | str | None = None,
    quantity: Decimal | None = None,
    unit: str = "MT",
    indicative_price: Decimal | None = None,
    currency: str = "USD",
    delivery_window_start: datetime.date | None = None,
    delivery_window_end: datetime.date | None = None,
    payment_terms: str = "",
    geography: str = "",
    notes: str = "",
    source: str = OpportunitySource.OPERATOR_SOURCING,
    broker_id: uuid.UUID | str | None = None,
    created_by: Any = None,
    as_of: datetime.datetime | None = None,
) -> Opportunity:
    """
    Authoritative Opportunity creation service.

    Transaction semantics:
        BEGIN
        -> validate source and broker attribution consistency
        -> allocate unique year/sequence safely (PostgreSQL select_for_update)
        -> construct identifier (OPP-{YEAR}-{SEQUENCE})
        -> create Opportunity
        -> full_clean & save
        -> COMMIT

    Guarantees that identifier generation occurs inside the authoritative
    creation boundary and produces an immutable record.
    """
    validate_opportunity_source_and_broker(source=source, broker_id=broker_id)

    identifier = allocate_opportunity_identifier(as_of=as_of)

    opportunity = Opportunity(
        identifier=identifier,
        direction=direction,
        organization_id=organization_id,
        external_counterparty_id=external_counterparty_id,
        commodity_id=commodity_id,
        quantity=quantity,
        unit=unit,
        indicative_price=indicative_price,
        currency=currency,
        delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end,
        payment_terms=payment_terms,
        geography=geography,
        notes=notes,
        source=source,
        broker_id=broker_id,
        created_by=created_by,
    )
    opportunity.full_clean()
    opportunity.save()
    return opportunity


@transaction.atomic
def update_opportunity(
    opportunity: Opportunity,
    *,
    data: dict[str, Any],
    expected_version: Any = None,
) -> Opportunity:
    """
    Authoritative Opportunity mutation service.

    Centralizes field-level mutation policy, source/broker validation,
    concurrency control, and lifecycle checks.
    """
    opp = Opportunity.objects.select_for_update().get(pk=opportunity.pk)

    exp_ver = expected_version
    if exp_ver is None and "expected_version" in data:
        exp_ver = data["expected_version"]

    if exp_ver is not None:
        from opportunities.services_lifecycle import _validate_expected_version

        _validate_expected_version(opp, exp_ver)

    clean_data = {k: v for k, v in data.items() if k != "expected_version"}

    for field in clean_data.keys():
        check_opportunity_mutation_allowed(opp, field)

    new_source = clean_data.get("source", opp.source)
    if "broker_id" in clean_data:
        new_broker_id = clean_data["broker_id"]
    elif "broker" in clean_data:
        broker_val = clean_data["broker"]
        new_broker_id = broker_val.id if hasattr(broker_val, "id") else broker_val
    else:
        new_broker_id = opp.broker_id

    validate_opportunity_source_and_broker(source=new_source, broker_id=new_broker_id)

    for field, value in clean_data.items():
        if field == "broker_id":
            opp.broker_id = value
        elif field == "organization_id":
            opp.organization_id = value
        elif field == "external_counterparty_id":
            opp.external_counterparty_id = value
        elif field == "commodity_id":
            opp.commodity_id = value
        else:
            setattr(opp, field, value)

    opp.version += 1
    opp.full_clean()
    opp.save()
    return opp
