from django.core.management.base import BaseCommand
from django.db import transaction
from commodities.models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from commodities.services import publish_schema

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

        # 2. Check if a published v1 already exists
        existing_v1 = CommoditySchemaVersion.objects.filter(
            commodity=commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
        ).first()

        if existing_v1:
            self.stdout.write(self.style.WARNING("Published Bitumen v1 already exists. Skipping mutation to preserve historical semantics."))

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
             # Should be handled by the existing_v1 check, but just in case for RETIRED etc
             self.stdout.write(self.style.ERROR(f"Bitumen v1 exists but is not draft/published (Status: {draft_v1.status}). Aborting."))
             return

        # Clear existing attributes if draft already existed to ensure clean state
        if not draft_created:
             CommodityAttributeDefinition.objects.filter(schema_version=draft_v1).delete()

        # 3. Create Attributes
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
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_v1,
                **attr_data
            )

        # 4. Publish and Activate
        publish_schema(draft_v1, activate=True)

        self.stdout.write(self.style.SUCCESS("Successfully seeded and activated Bitumen v1 definition."))
