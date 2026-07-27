"""Pluggable email delivery.

`ConsoleMailer` (default) logs the message — including any verification/invite
link — to the server console so flows are testable locally with no SMTP.
`SMTPMailer` is used automatically when `SMTP_HOST` is configured.

The `send_*` helpers build the user-facing link and return it, so routers can
also surface the link in API responses when `TAKTLINE_DEV=1`.
"""

from __future__ import annotations

import logging
from typing import Protocol
from urllib.parse import quote

from .config import settings

log = logging.getLogger("taktline.email")


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    async def send(self, to: str, subject: str, body: str) -> None:
        print(
            f"\n===== DEV EMAIL =====\nTo: {to}\nSubject: {subject}\n\n{body}\n"
            f"=====================\n",
            flush=True,
        )
        log.info("email(console) to=%s subject=%s", to, subject)


class SMTPMailer:
    def __init__(self, host: str, port: int, user: str | None, password: str | None,
                 sender: str, starttls: bool) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.starttls = starttls

    async def send(self, to: str, subject: str, body: str) -> None:
        import aiosmtplib
        from email.message import EmailMessage

        # Strip CR/LF so a user-controlled value (e.g. a company name in the
        # subject) can't inject additional email headers.
        subject = subject.replace("\r", " ").replace("\n", " ")
        to = to.replace("\r", "").replace("\n", "")

        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            start_tls=self.starttls,
        )
        log.info("email(smtp) to=%s subject=%s", to, subject)


def get_mailer() -> Mailer:
    if settings.sendgrid_api_key:
        return SMTPMailer(
            host="smtp.sendgrid.net", port=settings.smtp_port or 587,
            user="apikey", password=settings.sendgrid_api_key,
            sender=settings.smtp_from, starttls=True,
        )
    if settings.smtp_host:
        return SMTPMailer(
            host=settings.smtp_host, port=settings.smtp_port,
            user=settings.smtp_user, password=settings.smtp_password,
            sender=settings.smtp_from, starttls=settings.smtp_starttls,
        )
    return ConsoleMailer()


mailer: Mailer = get_mailer()


# ── Message builders (return the link so dev responses can echo it) ───────────
def _link(path: str, token: str) -> str:
    # safe="" so a slash is escaped too: this is a query-string value, not a
    # path. Real tokens are token_urlsafe ([A-Za-z0-9_-]) so nothing changes
    # for them — this is about not depending on that.
    return f"{settings.frontend_base_url}{path}?token={quote(token, safe='')}"


async def send_verification_email(to: str, token: str) -> str:
    link = _link("/verify-email", token)
    await mailer.send(
        to,
        "Verify your Taktline email",
        f"Welcome to Taktline!\n\nConfirm your email address to activate your "
        f"account:\n\n{link}\n\nThis link expires in 24 hours. If you did not "
        f"sign up, you can ignore this message.",
    )
    return link


async def send_password_reset_email(to: str, token: str) -> str:
    link = _link("/reset-password", token)
    await mailer.send(
        to,
        "Reset your Taktline password",
        f"We received a request to reset your password.\n\n{link}\n\nThis link "
        f"expires in 1 hour. If you did not request this, no action is needed.",
    )
    return link


async def send_invitation_email(to: str, token: str, company_name: str) -> str:
    link = _link("/accept-invite", token)
    await mailer.send(
        to,
        f"You're invited to join {company_name} on Taktline",
        f"You have been invited to join the company '{company_name}' on "
        f"Taktline.\n\nAccept your invitation:\n\n{link}\n\nThis invitation "
        f"expires in 7 days.",
    )
    return link
