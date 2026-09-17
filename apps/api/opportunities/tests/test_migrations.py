from datetime import datetime, timezone as dt_timezone
import importlib

from django.apps import apps
from django.db import connection
from django.test import TransactionTestCase

from opportunities.models import (
    Opportunity,
    OpportunityDirection,
    OpportunityIdentifierSequence,
)
from organizations.models import Organization

migration_0003 = importlib.import_module("opportunities.migrations.0003_opportunity_identifier")
backfill_opportunity_identifiers = migration_0003.backfill_opportunity_identifiers


class OpportunityMigrationBackfillTests(TransactionTestCase):
    """
    Tests data migration and safe backfill of existing Opportunities
    created prior to T0602.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Migration Org", country="AE")

    def test_backfill_assigns_sequential_identifiers_per_year_in_stable_order(self):
        """
        Existing rows with null/empty identifier must receive valid OPP-{YEAR}-{SEQUENCE}
        references ordered by (created_at, id).
        """
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE opportunities_opportunity ALTER COLUMN identifier DROP NOT NULL")

        try:
            # Create un-identified opportunities using raw SQL / update to simulate pre-migration state
            opp1 = Opportunity.objects.create(
                identifier="TEMP_1",
                direction=OpportunityDirection.SUPPLY,
                organization=self.org,
            )
            opp2 = Opportunity.objects.create(
                identifier="TEMP_2",
                direction=OpportunityDirection.DEMAND,
                organization=self.org,
            )
            opp3 = Opportunity.objects.create(
                identifier="TEMP_3",
                direction=OpportunityDirection.SUPPLY,
                organization=self.org,
            )

            # Explicitly set creation timestamps across different years and simulated null identifier
            Opportunity.objects.filter(id=opp1.id).update(
                identifier=None,
                created_at=datetime(2025, 5, 10, 10, 0, 0, tzinfo=dt_timezone.utc),
            )
            Opportunity.objects.filter(id=opp2.id).update(
                identifier=None,
                created_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=dt_timezone.utc),
            )
            Opportunity.objects.filter(id=opp3.id).update(
                identifier=None,
                created_at=datetime(2026, 2, 20, 8, 0, 0, tzinfo=dt_timezone.utc),
            )

            # Clear any existing sequence records for clean test
            OpportunityIdentifierSequence.objects.filter(year__in=[2025, 2026]).delete()

            # Execute migration backfill
            backfill_opportunity_identifiers(apps, None)

            opp1.refresh_from_db()
            opp2.refresh_from_db()
            opp3.refresh_from_db()

            self.assertEqual(opp1.identifier, "OPP-2025-000001")
            self.assertEqual(opp2.identifier, "OPP-2025-000002")
            self.assertEqual(opp3.identifier, "OPP-2026-000001")

            # Verify allocator sequence tables
            seq_2025 = OpportunityIdentifierSequence.objects.get(year=2025)
            seq_2026 = OpportunityIdentifierSequence.objects.get(year=2026)
            self.assertEqual(seq_2025.next_value, 3)
            self.assertEqual(seq_2026.next_value, 2)

            # Idempotence: running backfill again leaves identifiers intact
            backfill_opportunity_identifiers(apps, None)
            opp1.refresh_from_db()
            opp2.refresh_from_db()
            opp3.refresh_from_db()
            self.assertEqual(opp1.identifier, "OPP-2025-000001")
            self.assertEqual(opp2.identifier, "OPP-2025-000002")
            self.assertEqual(opp3.identifier, "OPP-2026-000001")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE opportunities_opportunity ALTER COLUMN identifier SET NOT NULL")
