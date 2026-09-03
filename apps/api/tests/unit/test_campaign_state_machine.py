import pytest

from app.modules.campaigns.enums import CampaignStatus
from app.modules.campaigns.service import InvalidStatusTransition, validate_status_transition


@pytest.mark.parametrize(
    "current,new",
    [
        (CampaignStatus.DRAFT, CampaignStatus.ACTIVE),
        (CampaignStatus.DRAFT, CampaignStatus.ARCHIVED),
        (CampaignStatus.ACTIVE, CampaignStatus.PAUSED),
        (CampaignStatus.ACTIVE, CampaignStatus.COMPLETED),
        (CampaignStatus.ACTIVE, CampaignStatus.ARCHIVED),
        (CampaignStatus.PAUSED, CampaignStatus.ACTIVE),
        (CampaignStatus.PAUSED, CampaignStatus.ARCHIVED),
        (CampaignStatus.COMPLETED, CampaignStatus.ARCHIVED),
    ],
)
def test_valid_transitions_are_accepted(current, new):
    validate_status_transition(current, new)  # must not raise


@pytest.mark.parametrize(
    "current,new",
    [
        (CampaignStatus.DRAFT, CampaignStatus.PAUSED),
        (CampaignStatus.DRAFT, CampaignStatus.COMPLETED),
        (CampaignStatus.ACTIVE, CampaignStatus.DRAFT),
        (CampaignStatus.PAUSED, CampaignStatus.COMPLETED),
        (CampaignStatus.COMPLETED, CampaignStatus.ACTIVE),
        (CampaignStatus.COMPLETED, CampaignStatus.DRAFT),
        (CampaignStatus.COMPLETED, CampaignStatus.PAUSED),
        (CampaignStatus.ARCHIVED, CampaignStatus.ACTIVE),
        (CampaignStatus.ARCHIVED, CampaignStatus.DRAFT),
    ],
)
def test_invalid_transitions_are_rejected(current, new):
    with pytest.raises(InvalidStatusTransition):
        validate_status_transition(current, new)


def test_same_status_is_a_noop_not_an_error():
    for status in CampaignStatus:
        validate_status_transition(status, status)  # must not raise, including ARCHIVED


def test_archived_is_terminal():
    for status in CampaignStatus:
        if status == CampaignStatus.ARCHIVED:
            continue
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition(CampaignStatus.ARCHIVED, status)
