from django.core.management.base import BaseCommand
from django.db import transaction
from commodities.models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition
from commodities.services import publish_schema

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

        # 2. Check if a published v1 already exists
        existing_v1 = CommoditySchemaVersion.objects.filter(
            commodity=commodity,
            version=1,
            status=CommoditySchemaVersion.SchemaStatus.PUBLISHED
        ).first()

        if existing_v1:
            self.stdout.write(self.style.WARNING("Published Base Oil v1 already exists. Skipping mutation to preserve historical semantics."))

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
             # Should be handled by the existing_v1 check, but just in case for RETIRED etc
             self.stdout.write(self.style.ERROR(f"Base Oil v1 exists but is not draft/published (Status: {draft_v1.status}). Aborting."))
             return

        # Clear existing attributes if draft already existed to ensure clean state
        if not draft_created:
             CommodityAttributeDefinition.objects.filter(schema_version=draft_v1).delete()

        # 3. Create Attributes
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
            CommodityAttributeDefinition.objects.create(
                schema_version=draft_v1,
                **attr_data
            )

        # 4. Publish and Activate
        publish_schema(draft_v1, activate=True)

        self.stdout.write(self.style.SUCCESS("Successfully seeded and activated Base Oil v1 definition."))
