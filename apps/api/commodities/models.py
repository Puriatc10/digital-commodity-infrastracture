import uuid

from django.db import models
from django.core.exceptions import ValidationError


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

    def clean(self):
        super().clean()
        if self.active_schema_version:
            if self.active_schema_version.commodity_id != self.id:
                raise ValidationError({"active_schema_version": "Active schema must belong to the same commodity."})
            if self.active_schema_version.status != "published":
                raise ValidationError({"active_schema_version": "Only a published schema can be active."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

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

    def clean(self):
        super().clean()
        if self.pk:
            try:
                orig = CommoditySchemaVersion.objects.get(pk=self.pk)
                # Immutability of Published and Retired
                if orig.status in [self.SchemaStatus.PUBLISHED, self.SchemaStatus.RETIRED]:
                    if self.version != orig.version or self.commodity_id != orig.commodity_id:
                        raise ValidationError("Cannot modify commodity or version of a published/retired schema.")

                # Status transitions
                if orig.status == self.SchemaStatus.PUBLISHED:
                    if self.status == self.SchemaStatus.DRAFT:
                        raise ValidationError({"status": "Cannot revert published schema to draft."})
                elif orig.status == self.SchemaStatus.RETIRED:
                    if self.status != self.SchemaStatus.RETIRED:
                        raise ValidationError({"status": "Retired schema cannot change status."})

                # Check if retiring an active schema
                if self.status == self.SchemaStatus.RETIRED and orig.status == self.SchemaStatus.PUBLISHED:
                    if self.commodity.active_schema_version_id == self.pk:
                        raise ValidationError({"status": "Cannot retire an active schema. Change the active schema first."})
            except CommoditySchemaVersion.DoesNotExist:
                pass

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in [self.SchemaStatus.PUBLISHED, self.SchemaStatus.RETIRED]:
            raise ValidationError("Cannot delete a published or retired schema.")
        return super().delete(*args, **kwargs)

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

    def clean(self):
        super().clean()
        if self.pk:
            try:
                orig = CommodityAttributeDefinition.objects.get(pk=self.pk)
                if orig.schema_version.status in ["published", "retired"]:
                    raise ValidationError("Cannot modify an attribute of a published or retired schema.")
            except CommodityAttributeDefinition.DoesNotExist:
                # If we're creating an object and force setting self.pk (e.g. fixtures or specific test cases),
                # we fall back to the creation logic.
                if getattr(self, "schema_version", None) and self.schema_version.status in ["published", "retired"]:
                    raise ValidationError("Cannot add attributes to a published or retired schema.")
        elif getattr(self, "schema_version", None) and self.schema_version.status in ["published", "retired"]:
            raise ValidationError("Cannot add attributes to a published or retired schema.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.schema_version.status in ["published", "retired"]:
            raise ValidationError("Cannot delete an attribute of a published or retired schema.")
        return super().delete(*args, **kwargs)

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
