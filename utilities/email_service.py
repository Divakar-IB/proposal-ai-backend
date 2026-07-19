import asyncio
import smtplib
from email.message import EmailMessage

from config import config
from utilities.logger import get_logger

logger = get_logger(__name__)


def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp.from_email
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(config.smtp.host, config.smtp.port) as server:
        if config.smtp.use_tls:
            server.starttls()
        server.login(config.smtp.username, config.smtp.password)
        server.send_message(message)


async def send_email(to_email: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_email_sync, to_email, subject, body)


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
