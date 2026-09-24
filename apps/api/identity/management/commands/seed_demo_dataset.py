from django.core.management.base import BaseCommand
from identity.seed_dataset import seed_demo_dataset


class Command(BaseCommand):
    help = "Seeds the database with a realistic, deterministic, and idempotent Demo dataset (T1301)."

    def handle(self, *args, **options):
        self.stdout.write("Starting realistic demo dataset seed (T1301)...")
        seed_demo_dataset(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Successfully completed realistic demo dataset seed."))
