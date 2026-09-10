from django.db import transaction
from django.core.exceptions import ValidationError
from .models import CommoditySchemaVersion, CommodityAttributeDefinition

@transaction.atomic
def publish_schema(schema: CommoditySchemaVersion, activate: bool = False) -> CommoditySchemaVersion:
    if schema.status != CommoditySchemaVersion.SchemaStatus.DRAFT:
        raise ValidationError("Only draft schemas can be published.")

    schema.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
    schema.save()

    if activate:
        schema.commodity.active_schema_version = schema
        schema.commodity.save()

    return schema

@transaction.atomic
def retire_schema(schema: CommoditySchemaVersion) -> CommoditySchemaVersion:
    if schema.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
        raise ValidationError("Only published schemas can be retired.")

    if schema.commodity.active_schema_version_id == schema.pk:
        raise ValidationError("Cannot retire the currently active schema. Change the active schema first.")

    schema.status = CommoditySchemaVersion.SchemaStatus.RETIRED
    schema.save()
    return schema

@transaction.atomic
def clone_schema_to_draft(schema: CommoditySchemaVersion) -> CommoditySchemaVersion:
    """Clones a published/retired schema into a new draft version."""
    # Find the next version number
    max_version = schema.commodity.schema_versions.order_by('-version').first()
    next_version = max_version.version + 1 if max_version else 1

    new_schema = CommoditySchemaVersion.objects.create(
        commodity=schema.commodity,
        version=next_version,
        status=CommoditySchemaVersion.SchemaStatus.DRAFT
    )

    # Duplicate attributes
    for attr in schema.attributes.all():
        CommodityAttributeDefinition.objects.create(
            schema_version=new_schema,
            key=attr.key,
            label_fa=attr.label_fa,
            label_en=attr.label_en,
            data_type=attr.data_type,
            is_required=attr.is_required,
            unit_metadata=attr.unit_metadata,
            enum_metadata=attr.enum_metadata,
            validation_metadata=attr.validation_metadata,
            display_group=attr.display_group,
            sort_order=attr.sort_order
        )

    return new_schema
