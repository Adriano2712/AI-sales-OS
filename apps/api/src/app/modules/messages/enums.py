import enum


class MessageChannel(str, enum.Enum):
    """Spec section 49 — architecture prepared for these, no real integration
    with any of them yet (send is always manual, spec section 47)."""

    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    LINKEDIN = "LINKEDIN"
    PHONE = "PHONE"
    OTHER = "OTHER"


class MessageStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"


# Terminal states (REJECTED, SENT) have no outgoing transitions — same
# pattern as campaigns/enums.py's VALID_STATUS_TRANSITIONS.
VALID_MESSAGE_STATUS_TRANSITIONS: dict[MessageStatus, set[MessageStatus]] = {
    MessageStatus.DRAFT: {MessageStatus.APPROVED, MessageStatus.REJECTED},
    MessageStatus.APPROVED: {MessageStatus.SENT, MessageStatus.REJECTED},
    MessageStatus.REJECTED: set(),
    MessageStatus.SENT: set(),
}
