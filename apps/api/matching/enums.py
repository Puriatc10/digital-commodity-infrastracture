from django.db import models


class MatchingAudience(models.TextChoices):
    BUYER = "BUYER", "Buyer"
    OPERATOR = "OPERATOR", "Operator"


class CandidateLane(models.TextChoices):
    DIRECT_SUPPLY = "DIRECT_SUPPLY", "Direct Supply"
    POTENTIAL_SUPPLIER = "POTENTIAL_SUPPLIER", "Potential Supplier"
    BROKER_PATH = "BROKER_PATH", "Broker Path"


class CandidateKind(models.TextChoices):
    SUPPLY_LISTING = "SUPPLY_LISTING", "Supply Listing"
    SUPPLY_OPPORTUNITY = "SUPPLY_OPPORTUNITY", "Supply Opportunity"
    SUPPLIER_ORGANIZATION = "SUPPLIER_ORGANIZATION", "Supplier Organization"
    BROKER_ORGANIZATION = "BROKER_ORGANIZATION", "Broker Organization"


class PolicyLifecycleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class SignalOutcome(models.TextChoices):
    PASS = "PASS", "Pass"
    PARTIAL = "PARTIAL", "Partial"
    FAIL = "FAIL", "Fail"
    UNKNOWN = "UNKNOWN", "Unknown"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"


class SignalDimension(models.TextChoices):
    SPECIFICATION = "SPECIFICATION", "Specification"
    QUANTITY = "QUANTITY", "Quantity"
    AVAILABILITY = "AVAILABILITY", "Availability"
    GEOGRAPHY = "GEOGRAPHY", "Geography"
    TRUST = "TRUST", "Trust"
    HISTORY = "HISTORY", "History"
