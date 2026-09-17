from django.core.management.base import BaseCommand

from matching.seed import seed_matching_policy_v1


class Command(BaseCommand):
    help = "Seeds deterministic platform default Published matching policy v1."

    def handle(self, *args, **options):
        self.stdout.write("Seeding default Published matching policy v1...")
        policy_version = seed_matching_policy_v1()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully verified/seeded matching policy: {policy_version}"
            )
        )
