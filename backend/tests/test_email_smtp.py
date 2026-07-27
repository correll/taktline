"""The SMTP delivery path, exercised for real.

`SMTPMailer` is the code that runs in production the moment a customer signs
up, and until this file existed nothing had ever executed it — the whole test
suite runs on `ConsoleMailer`, because no `SMTP_HOST` is configured under
pytest. A bug here would first surface as a stranger failing to receive their
verification link, which is both the worst place to find it and the hardest to
hear about.

So: a minimal SMTP server (no new dependency — the protocol is small enough to
speak directly), and assertions that a real message arrives over the wire with
the right envelope, headers and body.
"""

import asyncio

from app.core.email import SMTPMailer, _link


class CapturedSMTP:
    """A throwaway SMTP server that records one conversation.

    Speaks just enough of RFC 5321 for aiosmtplib: greeting, EHLO with an AUTH
    advertisement, AUTH, MAIL FROM, RCPT TO, DATA, QUIT.
    """

    def __init__(self):
        self.mail_from: str | None = None
        self.rcpt_to: list[str] = []
        self.data: str = ""
        self.authenticated = False
        self._server = None
        self.port = 0

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader, writer):
        async def say(line: str):
            writer.write(f"{line}\r\n".encode())
            await writer.drain()

        await say("220 test.local ESMTP")
        while True:
            raw = await reader.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            upper = line.upper()

            if upper.startswith("EHLO") or upper.startswith("HELO"):
                await say("250-test.local")
                await say("250 AUTH PLAIN LOGIN")
            elif upper.startswith("AUTH"):
                # A single-line "AUTH PLAIN <b64>" completes immediately.
                self.authenticated = True
                await say("235 2.7.0 Authentication successful")
            elif upper.startswith("MAIL FROM"):
                self.mail_from = line
                await say("250 OK")
            elif upper.startswith("RCPT TO"):
                self.rcpt_to.append(line)
                await say("250 OK")
            elif upper == "DATA":
                await say("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    part = await reader.readline()
                    if not part or part in (b".\r\n", b".\n"):
                        break
                    chunks.append(part.decode(errors="replace"))
                self.data = "".join(chunks)
                await say("250 OK: queued")
            elif upper == "QUIT":
                await say("221 Bye")
                break
            else:
                await say("250 OK")
        writer.close()


def _mailer(server):
    return SMTPMailer(host="127.0.0.1", port=server.port, user="resend",
                      password="re_test_key", sender="Taktline <no-reply@taktline.com>",
                      starttls=False)


def deliver(to, subject, body):
    """Run one real SMTP conversation and hand back what the server saw.

    The suite has no pytest-asyncio, so each test drives its own loop — the
    same convention the DB-touching tests use.
    """
    async def scenario():
        server = await CapturedSMTP().start()
        try:
            await _mailer(server).send(to, subject, body)
        finally:
            await server.stop()
        return server
    return asyncio.run(scenario())


def test_smtp_mailer_actually_delivers():
    """The path a real signup takes: SMTPMailer → the wire → a server."""
    smtp_server = deliver(
        "worker@example.com", "Verify your Taktline email", "Confirm: https://taktline.com/x")

    assert smtp_server.authenticated, "credentials were never offered"
    # Envelope: the address inside the display name, not the display name itself.
    assert "no-reply@taktline.com" in smtp_server.mail_from
    assert any("worker@example.com" in r for r in smtp_server.rcpt_to)
    # Headers + body as the recipient would see them.
    assert "Subject: Verify your Taktline email" in smtp_server.data
    assert "To: worker@example.com" in smtp_server.data
    assert "From: Taktline <no-reply@taktline.com>" in smtp_server.data
    assert "https://taktline.com/x" in smtp_server.data


def test_header_injection_cannot_forge_headers():
    """Company names reach the subject line. A CR/LF there would let a tenant
    append their own headers — a Bcc, a different Reply-To — to mail sent from
    our domain."""
    smtp_server = deliver(
        "worker@example.com",
        "You're invited to join Evil\r\nBcc: everyone@example.com",
        "body")

    # The defence flattens CR/LF to spaces, so the text survives *inside* the
    # Subject line — harmless. What must not exist is a real Bcc header, i.e.
    # a line that starts with it.
    lines = smtp_server.data.split("\r\n")
    assert not any(l.lower().startswith("bcc:") for l in lines), smtp_server.data
    assert sum(1 for l in lines if l.lower().startswith("subject:")) == 1
    assert len(smtp_server.rcpt_to) == 1


def test_verification_link_uses_the_configured_base_url(monkeypatch):
    """The link is built from FRONTEND_BASE_URL. Wrong there means every
    verification email points somewhere that does not answer."""
    from app.core import email as email_mod

    monkeypatch.setattr(email_mod.settings, "frontend_base_url", "https://taktline.com")
    link = _link("/verify-email", "tok en/with+chars")
    assert link.startswith("https://taktline.com/verify-email?token=")
    assert " " not in link and "+chars" not in link      # url-encoded, not raw

    smtp_server = deliver("w@example.com", "Verify", f"Click {link}")
    # Long URLs get soft-wrapped in transfer encoding; compare on the token.
    assert "tok%20en%2Fwith%2Bchars" in smtp_server.data.replace("=\r\n", "")
    assert "/with" not in smtp_server.data                # slash escaped, not literal
