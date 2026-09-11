import uuid
import re

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver


def lock_commodities(ids):
    """Serialize supported definition mutations with lifecycle/active changes."""
    list(CommodityDefinition.objects.select_for_update().filter(pk__in=ids).order_by("pk"))


class CommodityDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, help_text="Unique canonical code (e.g., bitumen)")
    name_fa = models.CharField(max_length=255, help_text="Persian name")
    name_en = models.CharField(max_length=255, help_text="English name")
    is_active = models.BooleanField(default=True)

    # Active schema version reference.
    # Same-commodity Published state is enforced in supported model/domain paths.
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
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.code):
            raise ValidationError({"code": "Use a canonical lowercase commodity code."})
        original_code = CommodityDefinition.objects.filter(pk=self.pk).values_list("code", flat=True).first()
        if original_code is not None and original_code != self.code:
            raise ValidationError({"code": "Commodity codes are stable identifiers."})
        if self.active_schema_version_id:
            active = CommoditySchemaVersion.objects.get(pk=self.active_schema_version_id)
            if active.commodity_id != self.id:
                raise ValidationError({"active_schema_version": "Active schema must belong to the same commodity."})
            if active.status != CommoditySchemaVersion.SchemaStatus.PUBLISHED:
                raise ValidationError({"active_schema_version": "Only a published schema can be active."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        lock_commodities([self.pk])
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
        if self._state.adding and self.status == self.SchemaStatus.RETIRED:
            raise ValidationError({"status": "New schemas must not start retired."})
        if self.pk:
            try:
                orig = CommoditySchemaVersion.objects.get(pk=self.pk)
                # Immutability of Published and Retired
                if orig.status in [self.SchemaStatus.PUBLISHED, self.SchemaStatus.RETIRED]:
                    if self.version != orig.version or self.commodity_id != orig.commodity_id:
                        raise ValidationError("Cannot modify commodity or version of a published/retired schema.")

                # Status transitions
                if orig.status == self.SchemaStatus.DRAFT and self.status == self.SchemaStatus.RETIRED:
                    raise ValidationError({"status": "Draft schemas must be published before retirement."})
                if orig.status == self.SchemaStatus.PUBLISHED:
                    if self.status == self.SchemaStatus.DRAFT:
                        raise ValidationError({"status": "Cannot revert published schema to draft."})
                elif orig.status == self.SchemaStatus.RETIRED:
                    if self.status != self.SchemaStatus.RETIRED:
                        raise ValidationError({"status": "Retired schema cannot change status."})

                # Check if retiring an active schema
                if self.status == self.SchemaStatus.RETIRED and orig.status == self.SchemaStatus.PUBLISHED:
                    if CommodityDefinition.objects.filter(pk=self.commodity_id, active_schema_version_id=self.pk).exists():
                        raise ValidationError({"status": "Cannot retire an active schema. Change the active schema first."})
            except CommoditySchemaVersion.DoesNotExist:
                pass

    @transaction.atomic
    def save(self, *args, **kwargs):
        original = CommoditySchemaVersion.objects.filter(pk=self.pk).first()
        lock_commodities([self.commodity_id] + ([original.commodity_id] if original else []))
        # A draft can be reparented; serialize against attribute edits as well.
        list(CommoditySchemaVersion.objects.select_for_update().filter(pk=self.pk))
        self.clean()
        if self.status == self.SchemaStatus.PUBLISHED and (not original or original.status == self.SchemaStatus.DRAFT):
            from .services import validate_schema_definition
            validate_schema_definition(self)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
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
        original_id = CommodityAttributeDefinition.objects.filter(pk=self.pk).values_list("schema_version_id", flat=True).first()
        parents = CommoditySchemaVersion.objects.filter(pk__in=[original_id, self.schema_version_id])
        if parents.exclude(status=CommoditySchemaVersion.SchemaStatus.DRAFT).exists():
            raise ValidationError("Cannot change attributes of a published or retired schema.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        original_id = CommodityAttributeDefinition.objects.filter(pk=self.pk).values_list("schema_version_id", flat=True).first()
        lock_commodities(CommoditySchemaVersion.objects.filter(pk__in=[original_id, self.schema_version_id]).values_list("commodity_id", flat=True))
        list(CommoditySchemaVersion.objects.select_for_update().filter(pk__in=[original_id, self.schema_version_id]).order_by("pk"))
        current = CommodityAttributeDefinition.objects.select_for_update().filter(pk=self.pk).first()
        if current and current.schema_version_id != original_id:
            raise ValidationError("Attribute ownership changed concurrently; reload before editing.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
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


@receiver(pre_delete, sender=CommodityDefinition)
@receiver(pre_delete, sender=CommoditySchemaVersion)
@receiver(pre_delete, sender=CommodityAttributeDefinition)
def protect_historical_deletion(sender, instance, **kwargs):
    # Django's collector calls signals for model, queryset, Admin and cascade deletes.
    if sender is CommodityDefinition:
        commodity_id = instance.pk
        schemas = CommoditySchemaVersion.objects.filter(commodity_id=commodity_id)
    elif sender is CommoditySchemaVersion:
        commodity_id = instance.commodity_id
        schemas = CommoditySchemaVersion.objects.filter(pk=instance.pk)
    else:
        schema_id = CommodityAttributeDefinition.objects.filter(pk=instance.pk).values_list("schema_version_id", flat=True).first()
        schemas = CommoditySchemaVersion.objects.filter(pk=schema_id)
        commodity_id = schemas.values_list("commodity_id", flat=True).first()
    lock_commodities([commodity_id])
    list(schemas.select_for_update().order_by("pk"))
    if schemas.exclude(status=CommoditySchemaVersion.SchemaStatus.DRAFT).exists():
        raise ValidationError("Cannot delete published or retired schema history.")
