from django.core.management.base import BaseCommand
from django.db import transaction
from commodities.models import (
    CommodityDefinition,
    CommoditySchemaVersion,
    CommodityAttributeDefinition,
    CommodityAttributeSemanticIdentity,
)
from commodities.services import publish_schema

BITUMEN_SEMANTIC_IDENTITIES = {
    "penetration_grade": {
        "id": "10000000-0000-0000-0000-000000000001",
        "code": "penetration_grade",
        "name_fa": "درجه نفوذ",
        "name_en": "Penetration Grade",
        "description": "Standard penetration grade classification for bitumen",
    },
    "penetration": {
        "id": "10000000-0000-0000-0000-000000000002",
        "code": "penetration",
        "name_fa": "نفوذپذیری",
        "name_en": "Penetration",
        "description": "Depth of penetration of standard needle under specified conditions",
    },
    "softening_point": {
        "id": "10000000-0000-0000-0000-000000000003",
        "code": "softening_point",
        "name_fa": "نقطه نرمی",
        "name_en": "Softening Point",
        "description": "Temperature at which bitumen reaches a specified degree of softness",
    },
    "ductility": {
        "id": "10000000-0000-0000-0000-000000000004",
        "code": "ductility",
        "name_fa": "انگمی",
        "name_en": "Ductility",
        "description": "Distance to which a briquette of bitumen can be stretched before breaking",
    },
    "flash_point": {
        "id": "10000000-0000-0000-0000-000000000005",
        "code": "flash_point",
        "name_fa": "نقطه اشتعال",
        "name_en": "Flash Point",
        "description": "Lowest temperature at which bitumen vapor flashes on ignition",
    },
    "solubility": {
        "id": "10000000-0000-0000-0000-000000000006",
        "code": "solubility",
        "name_fa": "حلالیت",
        "name_en": "Solubility",
        "description": "Percentage of bitumen soluble in standard solvent",
    },
    "loss_on_heating": {
        "id": "10000000-0000-0000-0000-000000000007",
        "code": "loss_on_heating",
        "name_fa": "افت وزنی",
        "name_en": "Loss on Heating",
        "description": "Weight loss percentage after heating under standard conditions",
    },
}

class Command(BaseCommand):
    help = "Seeds the initial deterministic Bitumen v1 definition."

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Create or get Commodity
        commodity, created = CommodityDefinition.objects.get_or_create(
            code="bitumen",
            defaults={
                "name_fa": "قیر",
                "name_en": "Bitumen",
                "is_active": True,
            }
        )

        # 2. Ensure deterministic semantic identities exist
        for key, sdata in BITUMEN_SEMANTIC_IDENTITIES.items():
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
            self.stdout.write(self.style.WARNING("Published Bitumen v1 already exists. Skipping mutation to preserve historical semantics."))

            # Ensure attributes have semantic identity attached if missing
            for attr in existing_v1.attributes.filter(semantic_identity__isnull=True):
                if attr.key in BITUMEN_SEMANTIC_IDENTITIES:
                    sem_id = BITUMEN_SEMANTIC_IDENTITIES[attr.key]["id"]
                    CommodityAttributeDefinition.objects.filter(pk=attr.pk).update(semantic_identity_id=sem_id)

            # Ensure it is active if no active schema is set
            if not commodity.active_schema_version:
                commodity.active_schema_version = existing_v1
                commodity.save()
                self.stdout.write(self.style.SUCCESS("Activated existing Published Bitumen v1."))

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
             self.stdout.write(self.style.ERROR(f"Bitumen v1 exists but is not draft/published (Status: {draft_v1.status}). Aborting."))
             return

        # Clear existing attributes if draft already existed to ensure clean state
        if not draft_created:
             CommodityAttributeDefinition.objects.filter(schema_version=draft_v1).delete()

        # 4. Create Attributes with explicit semantic identities
        attributes = [
            {
                "key": "penetration_grade",
                "label_fa": "درجه نفوذ",
                "label_en": "Penetration Grade",
                "data_type": CommodityAttributeDefinition.DataType.ENUM,
                "is_required": True,
                "enum_metadata": {
                    "options": [
                        {"value": "40/50", "label_fa": "۴۰/۵۰", "label_en": "40/50"},
                        {"value": "60/70", "label_fa": "۶۰/۷۰", "label_en": "60/70"},
                        {"value": "85/100", "label_fa": "۸۵/۱۰۰", "label_en": "85/100"}
                    ]
                },
                "display_group": "Classification",
                "sort_order": 10
            },
            {
                "key": "penetration",
                "label_fa": "نفوذپذیری",
                "label_en": "Penetration",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "0.1mm"},
                "validation_metadata": {"minimum": 0, "maximum": 300},
                "display_group": "Physical Properties",
                "sort_order": 20
            },
            {
                "key": "softening_point",
                "label_fa": "نقطه نرمی",
                "label_en": "Softening Point",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "°C"},
                "validation_metadata": {"minimum": 0, "maximum": 150},
                "display_group": "Physical Properties",
                "sort_order": 30
            },
            {
                "key": "ductility",
                "label_fa": "انگمی",
                "label_en": "Ductility",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "cm"},
                "validation_metadata": {"minimum": 0},
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
                "key": "solubility",
                "label_fa": "حلالیت",
                "label_en": "Solubility",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "%"},
                "validation_metadata": {"minimum": 0, "maximum": 100},
                "display_group": "Chemical Properties",
                "sort_order": 60
            },
            {
                "key": "loss_on_heating",
                "label_fa": "افت وزنی",
                "label_en": "Loss on Heating",
                "data_type": CommodityAttributeDefinition.DataType.NUMBER,
                "is_required": False,
                "unit_metadata": {"canonical_unit": "%"},
                "validation_metadata": {"minimum": 0, "maximum": 100},
                "display_group": "Chemical Properties",
                "sort_order": 70
            }
        ]

        for attr_data in attributes:
            sem_id = BITUMEN_SEMANTIC_IDENTITIES[attr_data["key"]]["id"]
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_v1,
                semantic_identity_id=sem_id,
                **attr_data
            )

        # 5. Publish and Activate
        publish_schema(draft_v1, activate=True)

        self.stdout.write(self.style.SUCCESS("Successfully seeded and activated Bitumen v1 definition."))
