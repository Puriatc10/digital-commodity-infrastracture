import uuid

from django.core.exceptions import ValidationError
from django.db import models


class AreaType(models.TextChoices):
    COUNTRY = "COUNTRY", "Country"
    ADMINISTRATIVE_AREA = "ADMINISTRATIVE_AREA", "Administrative Area"
    CITY = "CITY", "City"


class GeographicArea(models.Model):
    """
    Hierarchical geographic reference entity.

    Enforces strict structural invariants:
    - COUNTRY has no parent.
    - ADMINISTRATIVE_AREA has a COUNTRY parent.
    - CITY has an ADMINISTRATIVE_AREA parent (no city directly under country in v1).
    - Code is canonical, stable, and unique.
    - Cross-country chains and cycles are forbidden.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Canonical, stable, machine-readable area code (e.g. 'IR', 'IR-07', 'IR-07-THR').",
    )
    area_type = models.CharField(
        max_length=30,
        choices=AreaType.choices,
        help_text="Exact structural type: COUNTRY, ADMINISTRATIVE_AREA, or CITY.",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text="Parent geographic area in the hierarchy.",
    )
    country_code = models.CharField(
        max_length=2,
        db_index=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g. 'IR').",
    )
    name_fa = models.CharField(max_length=100, help_text="Persian display name.")
    name_en = models.CharField(max_length=100, help_text="English display name.")
    is_active = models.BooleanField(default=True, help_text="Whether this area is active for selection.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["country_code", "area_type", "code"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(parent__isnull=True) & models.Q(area_type=AreaType.COUNTRY))
                    | (
                        models.Q(parent__isnull=False)
                        & models.Q(area_type__in=[AreaType.ADMINISTRATIVE_AREA, AreaType.CITY])
                    )
                ),
                name="check_geographic_area_parent_nullability",
            ),
            models.CheckConstraint(
                condition=models.Q(area_type__in=[c[0] for c in AreaType.choices]),
                name="check_valid_geographic_area_type",
            ),
        ]
        indexes = [
            models.Index(fields=["country_code", "area_type"], name="idx_geo_country_type"),
            models.Index(fields=["parent", "area_type"], name="idx_geo_parent_type"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if not self.code:
            errors["code"] = "Code is required."
        else:
            self.code = self.code.strip()

        if self.country_code:
            self.country_code = self.country_code.strip().upper()
        else:
            errors["country_code"] = "Country code is required."

        if self.area_type not in AreaType.values:
            errors["area_type"] = f"Area type must be one of: {', '.join(AreaType.values)}."

        # Self-parent check
        if self.pk and self.parent_id and self.parent_id == self.pk:
            errors["parent"] = "A geographic area cannot be its own parent."

        # Parent nullability and type hierarchy invariants
        if self.area_type == AreaType.COUNTRY:
            if self.parent_id is not None:
                errors["parent"] = "Country areas must have no parent."
        elif self.area_type == AreaType.ADMINISTRATIVE_AREA:
            if self.parent is None:
                errors["parent"] = "Administrative areas must have a parent Country."
            elif self.parent.area_type != AreaType.COUNTRY:
                errors["parent"] = f"Administrative area parent must be a COUNTRY, got {self.parent.area_type}."
        elif self.area_type == AreaType.CITY:
            if self.parent is None:
                errors["parent"] = "City areas must have a parent Administrative Area."
            elif self.parent.area_type != AreaType.ADMINISTRATIVE_AREA:
                errors["parent"] = (
                    f"City parent must be an ADMINISTRATIVE_AREA, got {self.parent.area_type}."
                )

        # Cross-country chain check
        if self.parent is not None:
            if self.parent.country_code != self.country_code:
                errors["country_code"] = (
                    f"Country code '{self.country_code}' does not match parent's country code '{self.parent.country_code}'."
                )

        # Cycle detection
        if self.pk and self.parent_id:
            visited = {self.pk}
            curr = self.parent
            while curr is not None:
                if curr.pk in visited:
                    errors["parent"] = "Cycle detected in geographic area hierarchy."
                    break
                visited.add(curr.pk)
                curr = curr.parent

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name_en} ({self.code})"
