import enum


class JobType(str, enum.Enum):
    PING = "PING"  # Phase 0 infra smoke-test job; removed once a real job type exists.
    DISCOVERY = "DISCOVERY"
    ENRICHMENT = "ENRICHMENT"
    WEBSITE_ANALYSIS = "WEBSITE_ANALYSIS"
    BUSINESS_ANALYSIS = "BUSINESS_ANALYSIS"
    SCORING = "SCORING"
    MESSAGE_GENERATION = "MESSAGE_GENERATION"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
