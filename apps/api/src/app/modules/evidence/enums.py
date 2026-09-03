import enum


class EvidenceConfidence(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    # Not "no evidence exists" — "no public evidence was found". The anti-
    # hallucination rule (spec section 35): absence of information is never
    # recorded as a fact, only as UNKNOWN.
    UNKNOWN = "UNKNOWN"
