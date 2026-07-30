"""The public contact form.

Unauthenticated and world-reachable, so the tests are mostly about what it
refuses to become: a spam relay, and an oracle that tells a bot which of its
tricks was spotted.
"""

from unittest.mock import AsyncMock, patch

from tests.helpers import Actor

GOOD = {"name": "Dana Chen", "email": "dana@example.com",
        "message": "We run two lines and would like to map them.",
        "company": "Chen Fabrication", "elapsedMs": 20_000}


def _sent(mock):
    return [c.args for c in mock.await_args_list]


def test_a_real_enquiry_is_delivered(actor):
    a = actor()
    with patch("app.routers.contact.mailer.send", new=AsyncMock()) as send:
        r = a.req("POST", "/contact/", GOOD)
    assert r.status_code == 200 and r.json() == {"ok": True}
    (to, subject, body), = _sent(send)
    assert to == "nikolaus.correll@gmail.com"
    assert "Dana Chen" in subject
    assert "dana@example.com" in body and "would like to map them" in body


def test_the_honeypot_is_dropped_silently(actor):
    """A bot told it failed learns to try again. It gets the same 200 a person
    gets — and no email is sent."""
    a = actor()
    with patch("app.routers.contact.mailer.send", new=AsyncMock()) as send:
        r = a.req("POST", "/contact/", {**GOOD, "company_website": "http://spam.example"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert send.await_count == 0


def test_a_form_filled_faster_than_a_human_could_is_dropped(actor):
    a = actor()
    with patch("app.routers.contact.mailer.send", new=AsyncMock()) as send:
        r = a.req("POST", "/contact/", {**GOOD, "elapsedMs": 120})
    assert r.status_code == 200
    assert send.await_count == 0


def test_a_slow_human_is_not_penalised(actor):
    a = actor()
    with patch("app.routers.contact.mailer.send", new=AsyncMock()) as send:
        r = a.req("POST", "/contact/", {**GOOD, "elapsedMs": 9_000_000})
    assert r.status_code == 200
    assert send.await_count == 1


def test_the_visitors_text_cannot_forge_mail_headers(actor):
    """A newline in the name would otherwise let someone add Bcc: to the
    subject line."""
    a = actor()
    with patch("app.routers.contact.mailer.send", new=AsyncMock()) as send:
        a.req("POST", "/contact/", {**GOOD, "name": "Dana\r\nBcc: victim@example.com"})
    (_to, subject, _body), = _sent(send)
    assert "\n" not in subject and "\r" not in subject


def test_rubbish_is_refused_outright(actor):
    a = actor()
    for bad in ({**GOOD, "email": "not-an-email"},
                {**GOOD, "message": "hi"},          # under the minimum
                {**GOOD, "name": ""}):
        assert a.req("POST", "/contact/", bad).status_code == 422


def test_a_broken_mailer_does_not_break_the_page(actor):
    """The visitor must not meet a stack trace, and the message must not be
    lost — it is in the log either way."""
    a = actor()
    with patch("app.routers.contact.mailer.send",
               new=AsyncMock(side_effect=RuntimeError("smtp down"))):
        r = a.req("POST", "/contact/", GOOD)
    assert r.status_code == 200 and r.json() == {"ok": True}
