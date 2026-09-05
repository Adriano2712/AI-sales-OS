import enum


class EvidenceConfidence(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    # Not "no evidence exists" — "no public evidence was found". The anti-
    # hallucination rule (spec section 35): absence of information is never
    # recorded as a fact, only as UNKNOWN.
    UNKNOWN = "UNKNOWN"


class EvidencePolarity(str, enum.Enum):
    """What this piece of evidence means for *our* commercial opportunity —
    not a judgment about the business itself. A business problem (e.g. "no
    online booking") is POSITIVE here: it's an opening for a software house,
    not a flaw we're grading them on. A modern, well-run website is NEGATIVE
    here for the same reason: less room for us to help.

    ABSOLUTE RULE (evolving Evidence into an Opportunity Signal): UNKNOWN is
    never NEGATIVE and never worth zero — it means no evidence either way,
    not "evidence of a problem". Enforced in evidence/service.py, not just
    documented here: a claim with EvidenceConfidence.UNKNOWN can only ever
    be recorded with polarity UNKNOWN."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class EvidenceCategory(str, enum.Enum):
    """What kind of signal this is — deliberately scoped to what the system
    actually collects today (see enrichment/service.py and
    business_analysis/service.py), not speculative categories for data
    sources that don't exist yet (Google reviews/Instagram followers land
    in a later phase and can extend this enum then, non-breaking)."""

    CONTACTABILITY = "CONTACTABILITY"
    SOCIAL_PRESENCE = "SOCIAL_PRESENCE"
    BUSINESS_STATUS = "BUSINESS_STATUS"
    BUSINESS_ANALYSIS = "BUSINESS_ANALYSIS"
    OTHER = "OTHER"
