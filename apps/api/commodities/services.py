from django.db import transaction
from django.core.exceptions import ValidationError
from .models import CommoditySchemaVersion, CommodityAttributeDefinition
import jsonschema

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

def validate_commodity_payload(schema_version: CommoditySchemaVersion, payload: dict) -> None:
    """
    Validates a data payload against the JSON Schema generated from a CommoditySchemaVersion.
    Raises Django ValidationError with structured field-level errors if validation fails.
    """
    json_schema = generate_json_schema(schema_version)
    validator = jsonschema.Draft7Validator(json_schema)

    errors = list(validator.iter_errors(payload))
    if not errors:
        return

    structured_errors = []
    for error in errors:
        field = ""
        # For required errors, field is in the message (e.g., "'code' is a required property")
        if error.validator == "required":
            field = error.message.split("'")[1] if "'" in error.message else ""
            code = "required"
            message = error.message
        # For additional properties, error is in the message
        elif error.validator == "additionalProperties":
            field = error.message.split("'")[1] if "'" in error.message else ""
            code = "unknown_field"
            message = error.message
        else:
            # Field is derived from path (e.g. deque(['penetration_grade']))
            field = ".".join([str(p) for p in error.path])
            if error.validator == "type":
                code = "invalid_type"
                message = error.message
            elif error.validator == "enum":
                code = "invalid_enum"
                message = error.message
            elif error.validator == "minimum":
                code = "min_value"
                message = error.message
            elif error.validator == "maximum":
                code = "max_value"
                message = error.message
            elif error.validator == "minLength":
                code = "min_length"
                message = error.message
            elif error.validator == "maxLength":
                code = "max_length"
                message = error.message
            else:
                code = "invalid"
                message = error.message

        structured_errors.append({
            "field": field,
            "code": code,
            "message": message
        })

    # Raise a ValidationError mapping the list of structured dictionaries
    raise ValidationError("Payload validation failed.", code="invalid_payload", params={"errors": structured_errors})

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

def generate_json_schema(schema_version: CommoditySchemaVersion) -> dict:
    """
    Translates a CommoditySchemaVersion and its attributes into a deterministic JSON Schema (Draft 7).
    """
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    # Fetch attributes sorted by sort_order and key for determinism
    attributes = schema_version.attributes.all().order_by("sort_order", "key")

    for attr in attributes:
        prop = {}

        # Base type mapping
        if attr.data_type == CommodityAttributeDefinition.DataType.STRING:
            prop["type"] = "string"
        elif attr.data_type == CommodityAttributeDefinition.DataType.NUMBER:
            prop["type"] = "number"
        elif attr.data_type == CommodityAttributeDefinition.DataType.INTEGER:
            prop["type"] = "integer"
        elif attr.data_type == CommodityAttributeDefinition.DataType.BOOLEAN:
            prop["type"] = "boolean"
        elif attr.data_type == CommodityAttributeDefinition.DataType.ENUM:
            prop["type"] = "string"
            options = attr.enum_metadata.get("options", [])
            # Enum values can be objects with "value" or direct canonical strings if loosely formatted
            prop["enum"] = [opt["value"] if isinstance(opt, dict) else opt for opt in options]

        # Validation metadata (numeric/string constraints)
        val_meta = attr.validation_metadata
        if "minimum" in val_meta:
            prop["minimum"] = val_meta["minimum"]
        if "maximum" in val_meta:
            prop["maximum"] = val_meta["maximum"]
        if "minLength" in val_meta:
            prop["minLength"] = val_meta["minLength"]
        if "maxLength" in val_meta:
            prop["maxLength"] = val_meta["maxLength"]

        # Note: explicit nulls are rejected by default as types are not unioned with "null".
        # This fulfills the requirement: optional means may be absent, not automatically nullable;
        # explicit null requires schema support (which is not in v1 supported basic definitions).

        schema["properties"][attr.key] = prop
        if attr.is_required:
            schema["required"].append(attr.key)

    if not schema["required"]:
        del schema["required"]

    return schema
