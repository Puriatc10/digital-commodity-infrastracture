from django.db import models


class OfferorRole(models.TextChoices):
    """
    Authoritative commercial role assumed by the offering party on an RFQ.

    Note: Invariant across the platform: Only SUPPLIER and BROKER are allowed.
    """

    SUPPLIER = "SUPPLIER", "Supplier"
    BROKER = "BROKER", "Broker"


class OfferVersionStatus(models.TextChoices):
    """
    Lifecycle status of an OfferVersion commercial snapshot (Contract §10).

    Critical Invariant:
    - Exactly DRAFT or SUBMITTED.
    - SUPERSEDED is never stored as mutable state; it is derived from later submitted versions.
    """

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"


class LogisticsCostStatus(models.TextChoices):
    """
    Logistics cost status options for an OfferVersion (Contract §28).

    - KNOWN_SEPARATE: Logistics cost is known separately and specified in logistics_cost_amount.
    - INCLUDED_IN_PRICE: Logistics is already included in unit_price (amount is absent).
    - NOT_APPLICABLE: Logistics is not applicable for terms, e.g. EXW (amount is absent).
    - UNKNOWN: Logistics cost is unknown/unspecified (amount is absent, never zero).
    """

    KNOWN_SEPARATE = "KNOWN_SEPARATE", "Known Separate"
    INCLUDED_IN_PRICE = "INCLUDED_IN_PRICE", "Included in Price"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"
    UNKNOWN = "UNKNOWN", "Unknown"


class CostComponentKind(models.TextChoices):
    """
    Kinds of cost components attached to an OfferVersion commercial snapshot (Contract §27).
    """

    LOGISTICS = "LOGISTICS", "Logistics"
    OTHER = "OTHER", "Other"


class DecisionProfileLifecycleStatus(models.TextChoices):
    """
    Lifecycle status of a DecisionProfileVersion (T0808, Contract §39).

    Lifecycle:
        DRAFT -> PUBLISHED -> RETIRED

    Critical Invariant:
    - Published versions are strictly immutable.
    - Runs may only be executed against Published versions.
    """

    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class DecisionDimension(models.TextChoices):
    """
    Standard dimensions evaluated in multi-criteria procurement decision support (T0808).
    """

    COST = "COST", "Cost"
    QUALITY = "QUALITY", "Quality"
    DELIVERY = "DELIVERY", "Delivery"
    PAYMENT = "PAYMENT", "Payment"
    TRUST = "TRUST", "Trust"
    COMPLETENESS = "COMPLETENESS", "Completeness"


class DecisionSignalStatus(models.TextChoices):
    """
    Analytical evaluation outcome for a single decision signal (Contract §40, T0808).
    """

    PASS = "PASS", "Pass"
    PARTIAL = "PARTIAL", "Partial"
    FAIL = "FAIL", "Fail"
    UNKNOWN = "UNKNOWN", "Unknown"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"


class RevisionRequestStatus(models.TextChoices):
    """
    Lifecycle status of a RevisionRequest against an Offer (Epic 8 Contract §56).

    Lifecycle transitions:
        create: OPEN
        OPEN -> DECLINED (by Offer participant)
        OPEN -> CANCELLED (by Buyer / Operator)
        OPEN -> RESOLVED (by revised OfferVersion in T0811)
    """

    OPEN = "OPEN", "Open"
    RESOLVED = "RESOLVED", "Resolved"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"


class RevisionRequestedField(models.TextChoices):
    """
    Canonical commercial field identifiers eligible for negotiation revision requests (Epic 8 Contract §56).
    """

    UNIT_PRICE = "unit_price", "Unit Price"
    OFFERED_QUANTITY = "offered_quantity", "Offered Quantity"
    PAYMENT_TERMS = "payment_terms", "Payment Terms"
    DELIVERY_TERMS = "delivery_terms", "Delivery Terms"
    INCOTERM = "incoterm", "Incoterm"
    DELIVERY_START = "delivery_start", "Delivery Start"
    DELIVERY_END = "delivery_end", "Delivery End"
    VALID_UNTIL = "valid_until", "Valid Until"
    SPECIFICATIONS = "specifications", "Dynamic Specifications"
    LOGISTICS_COST_AMOUNT = "logistics_cost_amount", "Logistics Cost Amount"
    NOTES = "notes", "Commercial Notes"


FORBIDDEN_REVISION_FIELDS = frozenset(
    {
        "id",
        "offer",
        "offer_id",
        "version_number",
        "status",
        "created_by",
        "created_by_id",
        "submitted_by",
        "submitted_by_id",
        "submitted_at",
        "created_at",
        "updated_at",
        "aggregate_version",
        "schema_version",
        "schema_version_id",
        "currency",
        "quantity_unit",
    }
)

