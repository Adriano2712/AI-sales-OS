import imaplib
import re
from email.message import EmailMessage

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993
_IMAP_TIMEOUT_SECONDS = 30

_MAILBOX_NAME_RE = re.compile(r'"([^"]*)"\s*$')


class GmailDraftError(Exception):
    """Raised for any IMAP failure creating the draft — never sends anything;
    a failure here just means the draft wasn't created, nothing went out."""


def _find_drafts_mailbox(imap: imaplib.IMAP4_SSL) -> str:
    """Gmail's drafts folder name depends on the account's UI language
    (`[Gmail]/Drafts` in English, `[Gmail]/Rascunhos` in Portuguese, ...) —
    found via the IMAP SPECIAL-USE extension (RFC 6154) rather than assumed,
    so this doesn't silently fail (or append to the wrong folder) on a
    non-English account."""
    status, mailboxes = imap.list()
    if status != "OK":
        raise GmailDraftError("Could not list IMAP mailboxes to find Drafts")

    for raw in mailboxes or []:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        if "\\Drafts" not in line:
            continue
        match = _MAILBOX_NAME_RE.search(line)
        if match:
            return match.group(1)

    raise GmailDraftError("No mailbox flagged \\Drafts found on this account")


def create_gmail_draft(
    smtp_user: str,
    smtp_app_password: str,
    to_address: str,
    subject: str,
    text_body: str,
) -> None:
    """Creates a draft in the Gmail account's own Drafts folder — never sends
    anything (spec: outreach send stays a human action, same reasoning as
    messages/service.py). Uses IMAP APPEND; the same Google "App Password"
    already used for SMTP sending (see email_sender.py) works here too — no
    new credential, no Google API/OAuth setup. Blocking — callers on an
    asyncio event loop should run this via `asyncio.to_thread()`."""
    message = EmailMessage()
    message["From"] = smtp_user
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(text_body)

    try:
        with imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=_IMAP_TIMEOUT_SECONDS) as imap:
            imap.login(smtp_user, smtp_app_password)
            drafts_mailbox = _find_drafts_mailbox(imap)
            status, _data = imap.append(drafts_mailbox, "\\Draft", None, message.as_bytes())
            if status != "OK":
                raise GmailDraftError(f"IMAP APPEND to {drafts_mailbox!r} did not return OK")
    except (imaplib.IMAP4.error, OSError) as exc:
        raise GmailDraftError(f"Failed to create Gmail draft via {_IMAP_HOST}: {exc}") from exc
