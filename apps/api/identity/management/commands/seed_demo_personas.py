from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from organizations.models import Organization, OrganizationMembership, OrganizationCapability
from identity.models import SystemRoleAssignment

User = get_user_model()

class Command(BaseCommand):
    help = "Seeds the database with deterministic demo personas for the switcher."

    def handle(self, *args, **kwargs):
        if not settings.DEMO_PERSONA_SWITCHER_ENABLED:
            raise CommandError("Enable DEMO_PERSONA_SWITCHER_ENABLED in a demo environment before seeding.")
        personas = [
            {
                "email": "buyer@demo.local",
                "org_name": "Demo Buyer Corp",
                "capability": "buyer",
                "org_role": "manager",
            },
            {
                "email": "supplier@demo.local",
                "org_name": "Demo Supplier LLC",
                "capability": "supplier",
                "org_role": "owner",
            },
            {
                "email": "broker@demo.local",
                "org_name": "Demo Brokerage",
                "capability": "broker",
                "org_role": "member",
            },
            {
                "email": "operator@demo.local",
                "system_role": "operator",
            },
            {
                "email": "admin@demo.local",
                "system_role": "admin",
            },
        ]

        with transaction.atomic():
            for p in personas:
                user, created = User.objects.get_or_create(
                    email=p["email"],
                    defaults={"is_active": True}
                )
                if created:
                    user.set_unusable_password()
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f"Created user: {p['email']}"))

                if "org_name" in p:
                    org, org_created = Organization.objects.get_or_create(
                        name=p["org_name"],
                        defaults={"is_active": True}
                    )
                    if org_created:
                        self.stdout.write(self.style.SUCCESS(f"Created organization: {p['org_name']}"))

                    OrganizationCapability.objects.get_or_create(
                        organization=org,
                        capability=p["capability"]
                    )

                    OrganizationMembership.objects.get_or_create(
                        user=user,
                        organization=org,
                        defaults={"role": p["org_role"]}
                    )

                if "system_role" in p:
                    SystemRoleAssignment.objects.get_or_create(
                        user=user,
                        role=p["system_role"]
                    )

        self.stdout.write(self.style.SUCCESS("Successfully seeded demo personas."))
