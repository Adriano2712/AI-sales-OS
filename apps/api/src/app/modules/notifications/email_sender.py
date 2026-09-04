import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587
_SMTP_TIMEOUT_SECONDS = 30


class EmailSendError(Exception):
    """Raised for any SMTP failure — the caller decides whether/how to
    retry (see workers/scheduler.py, which just tries again next tick)."""


def send_email(
    smtp_user: str,
    smtp_app_password: str,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    """Real Gmail SMTP send (smtp.gmail.com:587, STARTTLS) — no third-party
    email service, no new paid dependency, uses only the stdlib. Blocking —
    callers on an asyncio event loop should run this via
    `asyncio.to_thread()`.

    `smtp_app_password` must be a Google "App Password" (16 characters,
    generated at myaccount.google.com/apppasswords with 2-Step Verification
    on) — never the account's real login password; Google no longer accepts
    that for SMTP AUTH regardless."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = to_address
    message.attach(MIMEText(text_body, "plain"))
    if html_body:
        message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(smtp_user, smtp_app_password)
            server.sendmail(smtp_user, [to_address], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailSendError(f"Failed to send email via {_SMTP_HOST}: {exc}") from exc
