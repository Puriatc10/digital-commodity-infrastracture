from django.core.management.base import BaseCommand
from django.db import transaction
from commodities.models import (
    CommodityDefinition,
    CommoditySchemaVersion,
    CommodityAttributeDefinition,
    CommodityAttributeSemanticIdentity,
)
from commodities.services import publish_schema

BASE_OIL_SEMANTIC_IDENTITIES = {
    "base_oil_group": {
        "id": "20000000-0000-0000-0000-000000000001",
        "code": "base_oil_group",
        "name_fa": "گروه روغن پایه",
        "name_en": "Base Oil Group",
        "description": "API Base Oil classification group (Group I, II, III)",
    },
    "viscosity_grade": {
        "id": "20000000-0000-0000-0000-000000000002",
        "code": "viscosity_grade",
        "name_fa": "گرید گرانروی",
        "name_en": "Viscosity Grade",
        "description": "Commercial viscosity grade designation (e.g. SN150, SN500)",
    },
    "viscosity_at_40c": {
        "id": "20000000-0000-0000-0000-000000000003",
        "code": "viscosity_at_40c",
        "name_fa": "گرانروی در ۴۰ درجه",
        "name_en": "Viscosity at 40°C",
        "description": "Kinematic viscosity at 40°C measured in cSt",
    },
    "viscosity_index": {
        "id": "20000000-0000-0000-0000-000000000004",
        "code": "viscosity_index",
        "name_fa": "شاخص گرانروی",
        "name_en": "Viscosity Index",
        "description": "Viscosity index indicating change in viscosity with temperature",
    },
    "flash_point": {
        "id": "20000000-0000-0000-0000-000000000005",
        "code": "flash_point",
        "name_fa": "نقطه اشتعال",
        "name_en": "Flash Point",
        "description": "Lowest temperature at which base oil vapor flashes on ignition",
    },
    "pour_point": {
        "id": "20000000-0000-0000-0000-000000000006",
        "code": "pour_point",
        "name_fa": "نقطه ریزش",
        "name_en": "Pour Point",
        "description": "Lowest temperature at which oil continues to flow under test conditions",
    },
}

class Command(BaseCommand):
    help = "Seeds the initial deterministic Base Oil v1 definition."

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Create or get Commodity
        commodity, created = CommodityDefinition.objects.get_or_create(
            code="base_oil",
            defaults={
                "name_fa": "روغن پایه",
                "name_en": "Base Oil",
                "is_active": True,
            }
        )

        # 2. Ensure deterministic semantic identities exist
        for key, sdata in BASE_OIL_SEMANTIC_IDENTITIES.items():
            CommodityAttributeSemanticIdentity.objects.get_or_create(
                id=sdata["id"],
                commodity=commodity,
                defaults={
                    "code": sdata["code"],
                    "name_fa": sdata["name_fa"],
                    "name_en": sdata["name_en"],
                    "description": sdata["description"],
                }
            )

        # 3. Check if a published v1 already exists
        existing_v1 = CommoditySchemaVersion.objects.filter(
            commodity=commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
        ).first()

        if existing_v1:
            self.stdout.write(self.style.WARNING("Published Base Oil v1 already exists. Skipping mutation to preserve historical semantics."))

            # Ensure attributes have semantic identity attached if missing
            for attr in existing_v1.attributes.filter(semantic_identity__isnull=True):
                if attr.key in BASE_OIL_SEMANTIC_IDENTITIES:
                    sem_id = BASE_OIL_SEMANTIC_IDENTITIES[attr.key]["id"]
                    CommodityAttributeDefinition.objects.filter(pk=attr.pk).update(semantic_identity_id=sem_id)

            # Ensure it is active if no active schema is set
            if not commodity.active_schema_version:
                commodity.active_schema_version = existing_v1
                commodity.save()
                self.stdout.write(self.style.SUCCESS("Activated existing Published Base Oil v1."))

            return

        # Check for draft v1 to reuse or create new draft v1
        draft_v1, draft_created = CommoditySchemaVersion.objects.get_or_create(
            commodity=commodity,
            version=1,
            defaults={
                "status": CommoditySchemaVersion.SchemaStatus.DRAFT
            }
        )

        if not draft_created and draft_v1.status != CommoditySchemaVersion.SchemaStatus.DRAFT:
             self.stdout.write(self.style.ERROR(f"Base Oil v1 exists but is not draft/published (Status: {draft_v1.status}). Aborting."))
             return

        # Clear existing attributes if draft already existed to ensure clean state
        if not draft_created:
             CommodityAttributeDefinition.objects.filter(schema_version=draft_v1).delete()

        # 4. Create Attributes with explicit semantic identities
        attributes = [
            {
                "key": "base_oil_group",
                "label_fa": "گروه روغن پایه",
                "label_en": "Base Oil Group",
                "data_type": CommodityAttributeDefinition.DataType.ENUM,
                "is_required": True,
                "enum_metadata": {
                    "options": [
                        {"value": "Group I", "label_fa": "گروه ۱", "label_en": "Group I"},
                        {"value": "Group II", "label_fa": "گروه ۲", "label_en": "Group II"},
                        {"value": "Group III", "label_fa": "گروه ۳", "label_en": "Group III"}
                    ]
                },
                "display_group": "Classification",
                "sort_order": 10
            },
            {
                "key": "viscosity_grade",
                "label_fa": "گرید گرانروی",
                "label_en": "Viscosity Grade",
                "data_type": CommodityAttributeDefinition.DataType.ENUM,
                "is_required": True,
                "enum_metadata": {
                    "options": [
                        {"value": "SN150", "label_fa": "SN150", "label_en": "SN150"},
                        {"value": "SN350", "label_fa": "SN350", "label_en": "SN350"},
                        {"value": "SN500", "label_fa": "SN500", "label_en": "SN500"},
                        {"value": "SN650", "label_fa": "SN650", "label_en": "SN650"}
                    ]
                },
                "display_group": "Classification",
                "sort_order": 20
            },
            {
                "key": "viscosity_at_40c",
                "label_fa": "گرانروی در ۴۰ درجه",
                "label_en": "Viscosity at 40°C",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "cSt"},
                "validation_metadata": {"minimum": 0},
                "display_group": "Physical Properties",
                "sort_order": 30
            },
            {
                "key": "viscosity_index",
                "label_fa": "شاخص گرانروی",
                "label_en": "Viscosity Index",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "validation_metadata": {"minimum": 0, "maximum": 200},
                "display_group": "Physical Properties",
                "sort_order": 40
            },
            {
                "key": "flash_point",
                "label_fa": "نقطه اشتعال",
                "label_en": "Flash Point",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "°C"},
                "validation_metadata": {"minimum": 0},
                "display_group": "Safety Properties",
                "sort_order": 50
            },
            {
                "key": "pour_point",
                "label_fa": "نقطه ریزش",
                "label_en": "Pour Point",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "°C"},
                "validation_metadata": {"maximum": 50},
                "display_group": "Physical Properties",
                "sort_order": 60
            }
        ]

        for attr_data in attributes:
            sem_id = BASE_OIL_SEMANTIC_IDENTITIES[attr_data["key"]]["id"]
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_v1,
                semantic_identity_id=sem_id,
                **attr_data
            )

        # 5. Publish and Activate
        publish_schema(draft_v1, activate=True)

        self.stdout.write(self.style.SUCCESS("Successfully seeded and activated Base Oil v1 definition."))
