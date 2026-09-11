from django.db import transaction
from django.core.exceptions import ValidationError
from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition, lock_commodities
import jsonschema
import math

@transaction.atomic
def publish_schema(schema: CommoditySchemaVersion, activate: bool = False) -> CommoditySchemaVersion:
    lock_commodities([schema.commodity_id])
    schema.refresh_from_db()
    if schema.status != CommoditySchemaVersion.SchemaStatus.DRAFT:
        raise ValidationError("Only draft schemas can be published.")

    schema.status = CommoditySchemaVersion.SchemaStatus.PUBLISHED
    schema.save()

    if activate:
        commodity = CommodityDefinition.objects.get(pk=schema.commodity_id)
        commodity.active_schema_version = schema
        commodity.save(update_fields=["active_schema_version", "updated_at"])

    return schema

def validate_commodity_payload(schema_version: CommoditySchemaVersion, payload: dict) -> None:
    """
    Validates a data payload against the JSON Schema generated from a CommoditySchemaVersion.
    Raises Django ValidationError with structured field-level errors if validation fails.
    """
    json_schema = generate_json_schema(schema_version)
    validator = jsonschema.Draft7Validator(json_schema)

    # Own the public error contract; never parse the validator's prose.
    structured_errors = []
    def add(field, code, message):
        structured_errors.append({"field": field, "code": code, "message": message})

    if isinstance(payload, dict):
        for key in sorted(set(json_schema.get("required", [])) - payload.keys()):
            add(key, "required", "This field is required.")
        for key in sorted(payload.keys() - json_schema["properties"].keys()):
            add(key, "unknown_field", "Unknown specification field.")
        for key, value in payload.items():
            if isinstance(value, float) and not math.isfinite(value):
                add(key, "invalid_type", "Value must be a finite JSON number.")
    codes = {
        "type": ("invalid_type", "Value has the wrong type."),
        "enum": ("invalid_enum", "Choose a canonical enum value."),
        "minimum": ("min_value", "Value is below the minimum."),
        "maximum": ("max_value", "Value exceeds the maximum."),
        "minLength": ("min_length", "Value is too short."),
        "maxLength": ("max_length", "Value is too long."),
    }
    for error in validator.iter_errors(payload):
        if error.validator in ("required", "additionalProperties"):
            continue
        field = ".".join(str(part) for part in error.path)
        code, message = codes.get(error.validator, ("invalid", "Invalid specification value."))
        add(field, code, message)
    if structured_errors:
        structured_errors.sort(key=lambda error: (error["field"], error["code"]))
        raise ValidationError("Payload validation failed.", code="invalid_payload", params={"errors": structured_errors})

@transaction.atomic
def retire_schema(schema: CommoditySchemaVersion) -> CommoditySchemaVersion:
    lock_commodities([schema.commodity_id])
    schema.refresh_from_db()
    if schema.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
        raise ValidationError("Only published schemas can be retired.")

    if CommodityDefinition.objects.filter(pk=schema.commodity_id, active_schema_version_id=schema.pk).exists():
        raise ValidationError("Cannot retire the currently active schema. Change the active schema first.")

    schema.status = CommoditySchemaVersion.SchemaStatus.RETIRED
    schema.save()
    return schema

@transaction.atomic
def clone_schema_to_draft(schema: CommoditySchemaVersion) -> CommoditySchemaVersion:
    """Clones a published/retired schema into a new draft version."""
    lock_commodities([schema.commodity_id])
    schema.refresh_from_db()
    if schema.status == CommoditySchemaVersion.SchemaStatus.DRAFT:
        raise ValidationError("Only published or retired schemas can be cloned.")
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


def validate_schema_definition(schema_version):
    """Draft metadata may be incomplete; publication must produce a valid v1 contract."""
    for attr in schema_version.attributes.all():
        if not isinstance(attr.unit_metadata, dict) or not isinstance(attr.enum_metadata, dict) or not isinstance(attr.validation_metadata, dict):
            raise ValidationError("Attribute metadata must be objects.")
        unit = attr.unit_metadata.get("canonical_unit", "")
        if not isinstance(unit, str):
            raise ValidationError("Canonical unit must be a string.")
        if attr.data_type == CommodityAttributeDefinition.DataType.ENUM:
            options = attr.enum_metadata.get("options")
            if not isinstance(options, list) or not options:
                raise ValidationError("Enum definitions require options.")
            values = []
            for option in options:
                if not isinstance(option, dict) or not isinstance(option.get("value"), str) or not option["value"]:
                    raise ValidationError("Enum options require nonempty canonical string values.")
                if any(not isinstance(option.get(label, ""), str) for label in ("label_fa", "label_en")):
                    raise ValidationError("Enum labels must be strings.")
                if "sort_order" in option and (type(option["sort_order"]) is not int or option["sort_order"] < 0):
                    raise ValidationError("Enum sort order must be a nonnegative integer.")
                values.append(option["value"])
            if len(values) != len(set(values)):
                raise ValidationError("Enum canonical values must be unique.")
        allowed = {
            "string": {"minLength", "maxLength"},
            "number": {"minimum", "maximum"},
            "integer": {"minimum", "maximum"},
            "boolean": set(), "enum": set(),
        }
        if attr.data_type not in allowed or set(attr.validation_metadata) - allowed[attr.data_type]:
            raise ValidationError("Unsupported validation metadata for attribute type.")
        for key, value in attr.validation_metadata.items():
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValidationError("Validation bounds must be finite numbers.")
            if key in ("minLength", "maxLength") and (type(value) is not int or value < 0):
                raise ValidationError("String lengths must be nonnegative integers.")
        for lower, upper in (("minimum", "maximum"), ("minLength", "maxLength")):
            if lower in attr.validation_metadata and upper in attr.validation_metadata:
                if attr.validation_metadata[lower] > attr.validation_metadata[upper]:
                    raise ValidationError("Minimum bound cannot exceed maximum bound.")
    try:
        jsonschema.Draft7Validator.check_schema(generate_json_schema(schema_version))
    except jsonschema.SchemaError as error:
        raise ValidationError("Invalid specification definition.") from error

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
