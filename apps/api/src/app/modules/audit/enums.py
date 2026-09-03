import enum


class AuditEventType(str, enum.Enum):
    CAMPAIGN_CREATED = "campaign_created"
    CAMPAIGN_UPDATED = "campaign_updated"
    CAMPAIGN_STARTED = "campaign_started"
    COMPANY_CREATED = "company_created"
    COMPANY_UPDATED = "company_updated"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    OPPORTUNITY_CREATED = "opportunity_created"
    OPPORTUNITY_UPDATED = "opportunity_updated"
    OPPORTUNITY_APPROVED = "opportunity_approved"
    MESSAGE_GENERATED = "message_generated"
    MESSAGE_APPROVED = "message_approved"
    CONTACTED = "contacted"
    RESPONSE_RECEIVED = "response_received"
    FEEDBACK_ADDED = "feedback_added"
