from django.core.management.base import BaseCommand
from identity.seed_hero import seed_hero_scenario


class Command(BaseCommand):
    help = "Seeds the database with deterministic Hero Scenario context (T1302)."

    def handle(self, *args, **options):
        self.stdout.write("Starting Hero Scenario seed (T1302)...")
        seed_hero_scenario(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Successfully completed Hero Scenario seed (T1302)."))
