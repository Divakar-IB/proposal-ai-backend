"""How an email physically leaves this process.

Two families of transport:

* **SMTP** (`smtplib`, port 587) — fine locally, but a lot of hosting
  platforms block outbound SMTP to stop spam. On Render the connect fails
  instantly with ``OSError: [Errno 101] Network is unreachable`` — the packets
  have nowhere to go, so no amount of retrying or timeout tuning helps.
* **Provider HTTPS APIs** — the same mail sent as an HTTPS POST on port 443,
  which is never blocked. This is the only thing that works on Render.

Pick one with ``smtp.provider`` in CONFIG. Every transport takes the same
arguments and returns nothing, so utilities/email_service.py does not care
which is in use.

``body`` is always the plain-text part. Passing ``html_body`` as well sends a
multipart mail carrying both, which is what clients want: the HTML is shown
where it can be, and the text part still covers plain-text readers and keeps
spam filters happy. Every transport spells that pairing differently, which is
the only reason they diverge below.
"""

import base64
import smtplib
from email.message import EmailMessage
from typing import Callable, NamedTuple, Optional

import httpx

from config import config
from utilities.logger import get_logger

logger = get_logger(__name__)

# A provider API that is slow or down must not hang a request forever.
HTTP_TIMEOUT_SECONDS = 20.0
SMTP_TIMEOUT_SECONDS = 20.0


class EmailAttachment(NamedTuple):
    content: bytes
    filename: str
    content_type: str


def _sender() -> str:
    """"Name <address>" when a display name is configured, else the address."""

    if config.smtp.from_name:
        return f"{config.smtp.from_name} <{config.smtp.from_email}>"
    return config.smtp.from_email


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code >= 400:
        # The body carries the actual reason (unverified domain, bad key,
        # rejected recipient); without it the caller only sees a status code.
        raise RuntimeError(
            f"{provider} API rejected the message "
            f"({response.status_code}): {response.text[:500]}"
        )


# ----------------------------------------------------------------------
# SMTP
# ----------------------------------------------------------------------

def send_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[list[EmailAttachment]] = None,
    html_body: Optional[str] = None,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _sender()
    message["To"] = to_email
    message.set_content(body)
    if html_body:
        # set_content + add_alternative produces multipart/alternative with the
        # plain text first, which is the order clients expect: an HTML-capable
        # one shows the last part, a text-only one falls back to the first.
        message.add_alternative(html_body, subtype="html")

    for attachment in attachments or []:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )

    server = smtplib.SMTP(config.smtp.host, config.smtp.port, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        if config.smtp.use_tls:
            server.starttls()
        server.login(config.smtp.username, config.smtp.password)
        server.send_message(message)
    finally:
        server.quit()


# ----------------------------------------------------------------------
# Provider HTTPS APIs
# ----------------------------------------------------------------------

def send_via_resend(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[list[EmailAttachment]] = None,
    html_body: Optional[str] = None,
) -> None:
    payload: dict = {
        "from": _sender(),
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if html_body:
        payload["html"] = html_body
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment.filename,
                "content": base64.b64encode(attachment.content).decode("ascii"),
            }
            for attachment in attachments
        ]

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {config.smtp.api_key}"},
        json=payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, "Resend")


def send_via_brevo(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[list[EmailAttachment]] = None,
    html_body: Optional[str] = None,
) -> None:
    sender: dict = {"email": config.smtp.from_email}
    if config.smtp.from_name:
        sender["name"] = config.smtp.from_name

    payload: dict = {
        "sender": sender,
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }
    if html_body:
        payload["htmlContent"] = html_body
    if attachments:
        payload["attachment"] = [
            {
                "name": attachment.filename,
                "content": base64.b64encode(attachment.content).decode("ascii"),
            }
            for attachment in attachments
        ]

    response = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": config.smtp.api_key, "accept": "application/json"},
        json=payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, "Brevo")


def send_via_sendgrid(
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[list[EmailAttachment]] = None,
    html_body: Optional[str] = None,
) -> None:
    sender: dict = {"email": config.smtp.from_email}
    if config.smtp.from_name:
        sender["name"] = config.smtp.from_name

    # SendGrid requires the content parts in increasing order of preference,
    # so text/plain must come before text/html — reversing them is a 400.
    content: list[dict] = [{"type": "text/plain", "value": body}]
    if html_body:
        content.append({"type": "text/html", "value": html_body})

    payload: dict = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": sender,
        "subject": subject,
        "content": content,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment.filename,
                "type": attachment.content_type,
                "disposition": "attachment",
                "content": base64.b64encode(attachment.content).decode("ascii"),
            }
            for attachment in attachments
        ]

    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {config.smtp.api_key}"},
        json=payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    _raise_for_status(response, "SendGrid")


_TRANSPORTS: dict[str, Callable[..., None]] = {
    "smtp": send_via_smtp,
    "resend": send_via_resend,
    "brevo": send_via_brevo,
    "sendgrid": send_via_sendgrid,
}


def get_transport() -> Callable[..., None]:
    """Resolved per call rather than cached at import, so flipping
    smtp.provider does not require reasoning about import order."""

    provider = config.smtp.provider
    transport = _TRANSPORTS.get(provider)
    if transport is None:
        raise RuntimeError(f"Unknown smtp.provider '{provider}'; expected one of {sorted(_TRANSPORTS)}")
    return transport
