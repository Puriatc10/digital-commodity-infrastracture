import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    registration_identifier = models.CharField(max_length=255, blank=True)
    website = models.URLField(max_length=255, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2 country code")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    class OrganizationRole(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(
        max_length=50,
        choices=OrganizationRole.choices,
        default=OrganizationRole.VIEWER,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_organization_membership"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["owner", "manager", "member", "viewer"]),
                name="check_valid_membership_role"
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.organization} ({self.get_role_display()})"


class OrganizationCapability(models.Model):
    class CapabilityType(models.TextChoices):
        BUYER = "buyer", "Buyer"
        SUPPLIER = "supplier", "Supplier"
        BROKER = "broker", "Broker"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="capabilities")
    capability = models.CharField(max_length=50, choices=CapabilityType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "capability"],
                name="unique_organization_capability"
            ),
            models.CheckConstraint(
                condition=models.Q(capability__in=["buyer", "supplier", "broker"]),
                name="check_valid_capability"
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.get_capability_display()}"

class OrganizationCommodity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="commodities")
    commodity = models.ForeignKey("commodities.CommodityDefinition", on_delete=models.CASCADE, related_name="organizations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "commodity"],
                name="unique_organization_commodity"
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.commodity.code}"


class OrganizationOperatingArea(models.Model):
    """
    Explicit geographic operational coverage declared for an Organization.

    Critical invariant: Organization registered country, headquarters, or address
    MUST NEVER be inferred as operating area. Only explicit OrganizationOperatingArea
    records represent operating area coverage.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="operating_areas",
        help_text="Organization declaring operational coverage in this area.",
    )
    area = models.ForeignKey(
        "geography.GeographicArea",
        on_delete=models.CASCADE,
        related_name="operating_organizations",
        help_text="Geographic area where the organization operates.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "area"],
                name="unique_organization_operating_area",
            )
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.area.code}"
