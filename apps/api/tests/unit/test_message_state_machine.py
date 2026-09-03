import pytest

from app.modules.messages.enums import MessageStatus
from app.modules.messages.service import InvalidMessageStatusTransition, validate_message_status_transition


@pytest.mark.parametrize(
    "current,new",
    [
        (MessageStatus.DRAFT, MessageStatus.APPROVED),
        (MessageStatus.DRAFT, MessageStatus.REJECTED),
        (MessageStatus.APPROVED, MessageStatus.SENT),
        (MessageStatus.APPROVED, MessageStatus.REJECTED),
    ],
)
def test_valid_transitions_are_accepted(current, new):
    validate_message_status_transition(current, new)  # must not raise


@pytest.mark.parametrize(
    "current,new",
    [
        (MessageStatus.DRAFT, MessageStatus.SENT),
        (MessageStatus.APPROVED, MessageStatus.DRAFT),
        (MessageStatus.REJECTED, MessageStatus.DRAFT),
        (MessageStatus.REJECTED, MessageStatus.APPROVED),
        (MessageStatus.SENT, MessageStatus.DRAFT),
        (MessageStatus.SENT, MessageStatus.APPROVED),
        (MessageStatus.SENT, MessageStatus.REJECTED),
    ],
)
def test_invalid_transitions_are_rejected(current, new):
    with pytest.raises(InvalidMessageStatusTransition):
        validate_message_status_transition(current, new)


def test_same_status_is_a_noop_not_an_error():
    for status in MessageStatus:
        validate_message_status_transition(status, status)  # must not raise


def test_sent_and_rejected_are_terminal():
    for terminal in (MessageStatus.SENT, MessageStatus.REJECTED):
        for status in MessageStatus:
            if status == terminal:
                continue
            with pytest.raises(InvalidMessageStatusTransition):
                validate_message_status_transition(terminal, status)
