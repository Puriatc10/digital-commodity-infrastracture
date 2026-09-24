from django.core.management.base import BaseCommand
from identity.reset_demo import reset_demo_environment


class Command(BaseCommand):
    help = "Resets the database to the canonical deterministic Demo seed state (T1308)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-input",
            action="store_true",
            default=True,
            help="Do not prompt for confirmation before executing the destructive reset.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting Demo environment reset (T1308)...")
        reset_demo_environment(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Successfully reset and restored canonical Demo environment."))
