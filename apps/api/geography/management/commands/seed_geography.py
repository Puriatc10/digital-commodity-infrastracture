from django.core.management.base import BaseCommand
from geography.seed import seed_iran_geography


class Command(BaseCommand):
    help = "Seeds deterministic Iran hierarchical geography (Country, 31 Provinces, Pilot Cities)."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Iran hierarchical geography...")
        created_map = seed_iran_geography()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully verified/seeded {len(created_map)} geographic areas."
            )
        )
