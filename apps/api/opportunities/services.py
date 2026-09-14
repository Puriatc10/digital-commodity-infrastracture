import datetime
from decimal import Decimal
from typing import Any
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from opportunities.models import (
    Opportunity,
    OpportunityIdentifierSequence,
)


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
    created_by: Any = None,
    as_of: datetime.datetime | None = None,
) -> Opportunity:
    """
    Authoritative Opportunity creation service.

    Transaction semantics:
        BEGIN
        -> allocate unique year/sequence safely (PostgreSQL select_for_update)
        -> construct identifier (OPP-{YEAR}-{SEQUENCE})
        -> create Opportunity
        -> COMMIT

    Guarantees that identifier generation occurs inside the authoritative
    creation boundary and produces an immutable record.
    """
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
        created_by=created_by,
    )
    opportunity.full_clean()
    opportunity.save()
    return opportunity
