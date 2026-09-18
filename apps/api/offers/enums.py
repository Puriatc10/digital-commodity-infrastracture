from django.db import models


class OfferorRole(models.TextChoices):
    """
    Authoritative commercial role assumed by the offering party on an RFQ.

    Note: Invariant across the platform: Only SUPPLIER and BROKER are allowed.
    """

    SUPPLIER = "SUPPLIER", "Supplier"
    BROKER = "BROKER", "Broker"
