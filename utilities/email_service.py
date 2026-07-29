import asyncio
import smtplib
import socket
import time
from email.message import EmailMessage
from typing import NamedTuple, Optional

from config import config
from utilities.logger import get_logger

logger = get_logger(__name__)


class EmailAttachment(NamedTuple):
    content: bytes
    filename: str
    content_type: str


# TEMPORARY: stage-by-stage timing instrumentation to diagnose why sending is
# slow on Render but not locally. Remove once the bottleneck is confirmed.
def _send_email_sync(
    to_email: str, subject: str, body: str, attachments: Optional[list[EmailAttachment]] = None
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp.from_email
    message["To"] = to_email
    message.set_content(body)

    for attachment in attachments or []:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )

    timings: dict[str, float] = {}
    overall_start = time.perf_counter()

    stage_start = time.perf_counter()
    socket.getaddrinfo(config.smtp.host, config.smtp.port)
    timings["dns_resolve"] = time.perf_counter() - stage_start

    stage_start = time.perf_counter()
    server = smtplib.SMTP(config.smtp.host, config.smtp.port, timeout=20)
    timings["tcp_connect"] = time.perf_counter() - stage_start

    try:
        if config.smtp.use_tls:
            stage_start = time.perf_counter()
            server.starttls()
            timings["starttls"] = time.perf_counter() - stage_start

        stage_start = time.perf_counter()
        server.login(config.smtp.username, config.smtp.password)
        timings["login"] = time.perf_counter() - stage_start

        stage_start = time.perf_counter()
        server.send_message(message)
        timings["send_message"] = time.perf_counter() - stage_start
    finally:
        stage_start = time.perf_counter()
        server.quit()
        timings["quit"] = time.perf_counter() - stage_start

    timings["total"] = time.perf_counter() - overall_start
    logger.info(
        "SMTP send timing to=%s | %s",
        to_email,
        " ".join(f"{stage}={duration:.3f}s" for stage, duration in timings.items()),
    )


async def send_email(
    to_email: str, subject: str, body: str, attachments: Optional[list[EmailAttachment]] = None
) -> None:
    dispatch_start = time.perf_counter()
    await asyncio.to_thread(_send_email_sync, to_email, subject, body, attachments)
    logger.info(
        "send_email total (including thread dispatch) to=%s | %.3fs",
        to_email, time.perf_counter() - dispatch_start,
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


async def send_team_invite_email(to_email: str, temporary_password: str) -> None:
    subject = "You're invited to Proposal AI"
    body = (
        "Hello,\n\n"
        "You have been invited to join Proposal AI.\n\n"
        "Your login credentials are:\n\n"
        "Email:\n"
        f"{to_email}\n\n"
        "Temporary Password:\n"
        f"{temporary_password}\n\n"
        "Please log in using these credentials and change your password immediately.\n\n"
        "Regards,\n"
        "Proposal AI Team"
    )
    try:
        await send_email(to_email, subject, body)
    except Exception:
        logger.exception("Failed to send team invite email to %s", to_email)
        raise
