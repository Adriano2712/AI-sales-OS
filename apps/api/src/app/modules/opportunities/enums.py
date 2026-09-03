import enum


class OpportunityType(str, enum.Enum):
    WEBSITE = "WEBSITE"
    E_COMMERCE = "E_COMMERCE"
    AUTOMATION = "AUTOMATION"
    INTERNAL_SYSTEM = "INTERNAL_SYSTEM"
    INTEGRATION = "INTEGRATION"
    DIGITAL_PRESENCE = "DIGITAL_PRESENCE"
    OTHER = "OTHER"


class OpportunityStatus(str, enum.Enum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class OpportunityClassification(str, enum.Enum):
    HIGH = "HIGH"
    GOOD = "GOOD"
    REVIEW = "REVIEW"
    LOW = "LOW"
