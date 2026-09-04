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


class OpportunityOutcome(str, enum.Enum):
    """Real-world sales-pipeline stage, tracked by a human as it happens
    outside the system (send is manual, spec section 47) — separate from
    `status` (which is about "is this opportunity worth working", not "how
    far did the deal get"). No transition rules enforced, same reasoning as
    `Company.status`/`do_not_contact`: this is a human correction reflecting
    reality, not a pipeline-driven state machine, so any value must be
    reachable from any other (e.g. correcting a mistaken WON back to
    CONTACTED)."""

    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    PROPOSAL_SENT = "PROPOSAL_SENT"
    WON = "WON"
    LOST = "LOST"
