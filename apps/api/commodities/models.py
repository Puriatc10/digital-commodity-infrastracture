import uuid

from django.db import models


class CommodityDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, help_text="Unique canonical code (e.g., bitumen)")
    name_fa = models.CharField(max_length=255, help_text="Persian name")
    name_en = models.CharField(max_length=255, help_text="English name")
    is_active = models.BooleanField(default=True)

    # Active schema version reference.
    # Must belong to the same commodity and be Published, but we will enforce
    # the business logic in T0302. For T0301, we provide structural support.
    active_schema_version = models.ForeignKey(
        "CommoditySchemaVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The currently active schema version for new domain instances."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name_en} ({self.code})"


class CommoditySchemaVersion(models.Model):
    class SchemaStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commodity = models.ForeignKey(CommodityDefinition, on_delete=models.CASCADE, related_name="schema_versions")
    version = models.PositiveIntegerField(help_text="Version number (e.g., 1, 2)")
    status = models.CharField(
        max_length=20,
        choices=SchemaStatus.choices,
        default=SchemaStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commodity", "version"],
                name="unique_commodity_version"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "published", "retired"]),
                name="check_valid_schema_status"
            )
        ]

    def __str__(self):
        return f"{self.commodity.code} v{self.version} ({self.get_status_display()})"


class CommodityAttributeDefinition(models.Model):
    class DataType(models.TextChoices):
        STRING = "string", "String"
        NUMBER = "number", "Number"
        INTEGER = "integer", "Integer"
        BOOLEAN = "boolean", "Boolean"
        ENUM = "enum", "Enum"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.ForeignKey(CommoditySchemaVersion, on_delete=models.CASCADE, related_name="attributes")

    key = models.CharField(max_length=100, help_text="Canonical machine-readable key")
    label_fa = models.CharField(max_length=255, help_text="Persian label")
    label_en = models.CharField(max_length=255, help_text="English label")

    data_type = models.CharField(max_length=20, choices=DataType.choices)
    is_required = models.BooleanField(default=False)

    # Metadata for different aspects of the attribute
    unit_metadata = models.JSONField(default=dict, blank=True, help_text="Unit metadata (e.g., canonical unit, allowed units)")
    enum_metadata = models.JSONField(default=dict, blank=True, help_text="Enum metadata (canonical value, localized labels, sort order)")
    validation_metadata = models.JSONField(default=dict, blank=True, help_text="Validation rules (e.g., min/max values, min/max length)")

    # UI rendering hints
    display_group = models.CharField(max_length=100, blank=True, help_text="Logical group for UI presentation")
    sort_order = models.PositiveIntegerField(default=0, help_text="Deterministic sort order")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schema_version", "key"],
                name="unique_schema_version_key"
            ),
            models.CheckConstraint(
                condition=models.Q(data_type__in=["string", "number", "integer", "boolean", "enum"]),
                name="check_valid_data_type"
            )
        ]
        ordering = ["schema_version", "sort_order", "key"]

    def __str__(self):
        return f"{self.key} ({self.schema_version})"
