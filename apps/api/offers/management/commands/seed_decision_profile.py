from django.core.management.base import BaseCommand

from offers.services.policy_seed import seed_decision_profile_v1


class Command(BaseCommand):
    help = "Seeds deterministic platform default Published procurement decision profile v1 (T0808)."

    def handle(self, *args, **options):
        self.stdout.write("Seeding default Published procurement decision profile v1...")
        profile_version = seed_decision_profile_v1()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully verified/seeded decision profile version: {profile_version}"
            )
        )
