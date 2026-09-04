import pytest

from app.modules.notifications.gmail_draft import GmailDraftError, _find_drafts_mailbox


class _FakeImap:
    def __init__(self, list_response: tuple[str, list[bytes]]) -> None:
        self._list_response = list_response

    def list(self):
        return self._list_response


def test_finds_english_drafts_mailbox():
    imap = _FakeImap(
        (
            "OK",
            [
                b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
                b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"',
            ],
        )
    )
    assert _find_drafts_mailbox(imap) == "[Gmail]/Drafts"


def test_finds_localized_drafts_mailbox():
    """Real-world reason this matters: Gmail's Drafts folder name changes
    with the account's UI language — a hardcoded English name would silently
    append to the wrong (or a nonexistent) mailbox on a PT-BR account."""
    imap = _FakeImap(
        (
            "OK",
            [b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Rascunhos"'],
        )
    )
    assert _find_drafts_mailbox(imap) == "[Gmail]/Rascunhos"


def test_raises_when_no_drafts_mailbox_found():
    imap = _FakeImap(("OK", [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']))
    with pytest.raises(GmailDraftError):
        _find_drafts_mailbox(imap)


def test_raises_when_list_command_fails():
    imap = _FakeImap(("NO", []))
    with pytest.raises(GmailDraftError):
        _find_drafts_mailbox(imap)
