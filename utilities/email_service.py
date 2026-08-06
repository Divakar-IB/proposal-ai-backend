import asyncio
import time
from typing import Optional

from config import config
from utilities.email_templates import resolve_login_url, team_invite_email
from utilities.email_transport import EmailAttachment, get_transport
from utilities.logger import get_logger

logger = get_logger(__name__)

# Re-exported so callers keep importing EmailAttachment from here.
__all__ = [
    "EmailAttachment",
    "send_email",
    "send_otp_email",
    "send_proposal_export_email",
    "send_team_invite_email",
]


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[list[EmailAttachment]] = None,
    html_body: Optional[str] = None,
) -> None:
    """Sends one email via whichever transport `smtp.provider` selects (see
    utilities/email_transport.py).

    `body` is the plain-text part; pass `html_body` too and the mail carries
    both, so clients that render HTML get the styled version while plain-text
    readers still get something legible.

    Both transports are blocking network I/O, so they run in a worker thread
    to keep the event loop free.
    """

    transport = get_transport()
    started = time.perf_counter()
    await asyncio.to_thread(transport, to_email, subject, body, attachments, html_body)
    logger.info(
        "email sent | provider=%s to=%s subject=%r %.2fs",
        config.smtp.provider, to_email, subject, time.perf_counter() - started,
    )


async def send_otp_email(to_email: str, otp: str, expires_in_minutes: int) -> None:
    subject = "Your Proposal AI password reset code"
    body = (
        f"Your one-time password (OTP) to reset your Proposal AI account password is:\n\n"
        f"{otp}\n\n"
        f"This code expires in {expires_in_minutes} minutes. "
        f"If you did not request a password reset, you can safely ignore this email."
    )
    try:
        await send_email(to_email, subject, body)
    except Exception:
        logger.exception("Failed to send OTP email to %s", to_email)
        raise


async def send_proposal_export_email(
    to_email: str, proposal_title: str, attachment: EmailAttachment
) -> None:
    subject = f"Proposal Document - {proposal_title}"
    body = (
        "Dear Recipient,\n\n"
        "Please find the attached proposal document.\n\n"
        "If you have any questions, please let us know.\n\n"
        "Regards,\n"
        "Proposal AI Team"
    )
    try:
        await send_email(to_email, subject, body, attachments=[attachment])
    except Exception:
        logger.exception("Failed to send proposal export email to %s", to_email)
        raise


async def send_team_invite_email(
    to_email: str, temporary_password: str, login_url: Optional[str] = None
) -> None:
    """`login_url` defaults to `app_url` + `login_path` from CONFIG. Pass it
    explicitly only to override where this particular invite should land."""

    subject = "You're invited to Proposal AI"
    body, html_body = team_invite_email(
        to_email=to_email,
        temporary_password=temporary_password,
        login_url=login_url or resolve_login_url(),
    )
    try:
        await send_email(to_email, subject, body, html_body=html_body)
    except Exception:
        logger.exception("Failed to send team invite email to %s", to_email)
        raise
