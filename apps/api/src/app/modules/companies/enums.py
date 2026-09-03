import enum


class CompanyStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"
