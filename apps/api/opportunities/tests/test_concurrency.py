from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
import threading

from django.db import connection
from django.test import TransactionTestCase

from identity.models import SystemRoleAssignment, User
from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityIdentifierSequence,
)
from opportunities.services import (
    allocate_opportunity_sequence,
    create_opportunity,
)
from organizations.models import Organization


class OpportunityIdentifierConcurrencyTests(TransactionTestCase):
    """
    Mandatory real PostgreSQL concurrency tests for Opportunity identifier allocation.

    Tests multi-threaded / multi-worker execution against real PostgreSQL
    using threading.Barrier to force overlapping allocator execution.
    """

    def setUp(self):
        self.operator = User.objects.create_user(email="op_conc@test.com", password="password")
        SystemRoleAssignment.objects.create(user=self.operator, role=SystemRoleAssignment.SystemRole.OPERATOR)
        self.organization = Organization.objects.create(name="Concurrency Org", country="IR")

    def test_concurrent_opportunity_creation_allocates_unique_contiguous_identifiers(self):
        """
        N threads concurrently call `create_opportunity` for the same calendar year.
        Assert:
        - exactly N successfully persisted Opportunities
        - N unique identifiers
        - no duplicate sequence numbers
        - sequence values contiguous from 1 to N
        - allocator table next_value == N + 1
        """
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads
        errors = [None] * num_threads
        test_year = 2030  # Isolated future year

        def worker(thread_idx: int):
            try:
                # Synchronize all threads right before calling the creation service
                barrier.wait()
                opp = create_opportunity(
                    direction=OpportunityDirection.SUPPLY,
                    organization_id=self.organization.id,
                    quantity=Decimal("100.000"),
                    created_by=self.operator,
                    as_of=datetime(test_year, 6, 1, tzinfo=dt_timezone.utc),
                )
                results[thread_idx] = opp.identifier
            except Exception as exc:
                errors[thread_idx] = exc
            finally:
                connection.close()

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        # Assert no errors occurred in any thread
        for i, err in enumerate(errors):
            self.assertIsNone(err, f"Thread {i} encountered error: {err}")

        # Assert all threads completed and produced an identifier
        identifiers = [res for res in results if res is not None]
        self.assertEqual(len(identifiers), num_threads)

        # Assert all identifiers are unique
        unique_identifiers = set(identifiers)
        self.assertEqual(len(unique_identifiers), num_threads)

        # Assert all identifiers match format OPP-2030-XXXXXX
        for ident in identifiers:
            self.assertTrue(ident.startswith(f"OPP-{test_year}-"))

        # Extract sequence numbers and assert contiguous 1..num_threads
        seq_numbers = sorted([int(ident.split("-")[2]) for ident in identifiers])
        expected_seqs = list(range(1, num_threads + 1))
        self.assertEqual(seq_numbers, expected_seqs)

        # Verify database persisted state
        db_count = Opportunity.objects.filter(identifier__startswith=f"OPP-{test_year}-").count()
        self.assertEqual(db_count, num_threads)

        seq_record = OpportunityIdentifierSequence.objects.get(year=test_year)
        self.assertEqual(seq_record.next_value, num_threads + 1)

    def test_concurrent_initial_row_creation_race(self):
        """
        N threads concurrently call `allocate_opportunity_sequence` on an uninitialized year.
        Validates that the initial row insertion race condition is handled cleanly
        without duplicate key errors or deadlocks.
        """
        num_threads = 8
        barrier = threading.Barrier(num_threads)
        allocated_seqs = [None] * num_threads
        errors = [None] * num_threads
        test_year = 2035  # Uninitialized year

        def worker(thread_idx: int):
            try:
                barrier.wait()
                seq = allocate_opportunity_sequence(test_year)
                allocated_seqs[thread_idx] = seq
            except Exception as exc:
                errors[thread_idx] = exc
            finally:
                connection.close()

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        for i, err in enumerate(errors):
            self.assertIsNone(err, f"Thread {i} encountered error during initial race: {err}")

        valid_seqs = [s for s in allocated_seqs if s is not None]
        self.assertEqual(len(valid_seqs), num_threads)
        self.assertEqual(len(set(valid_seqs)), num_threads)
        self.assertEqual(sorted(valid_seqs), list(range(1, num_threads + 1)))

        seq_record = OpportunityIdentifierSequence.objects.get(year=test_year)
        self.assertEqual(seq_record.next_value, num_threads + 1)
