"""The "get in touch" form on the landing page.

Public and unauthenticated, so the whole design is about not becoming a spam
relay. Four cheap defences, in the order a bot meets them:

1. **The form does not exist in the HTML.** The client builds it in JavaScript
   after a real interaction, so a scraper reading the page source finds no
   form and no field names to post. This is the one the user asked for and it
   is the most effective of the four against the commonest bots, which never
   run scripts.
2. **A honeypot field** (`company_website`) that is hidden from people and
   irresistible to form-fillers. Anything in it → accepted-looking 200 and
   dropped on the floor, because telling a bot it failed teaches it to retry.
3. **Time-to-fill.** A human cannot read and complete this in under three
   seconds; a script does it in milliseconds. The client stamps when the form
   was built and the server checks the gap.
4. **Rate limit** by IP, because 1–3 are all client-asserted and the only
   defence that survives someone who has read this file is the one enforced
   server-side.

Deliberately NOT a CAPTCHA: it costs every honest visitor real effort and
sends their behaviour to a third party, which is a poor trade for the volume a
form like this sees.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from ..core.config import settings
from ..core.email import mailer
from ..core.ratelimit import limiter

log = logging.getLogger("taktline.contact")

router = APIRouter(prefix="/contact", tags=["contact"])

# Where enquiries go. An env override so this is not a code change when the
# address changes, but with a working default so the form is never silently
# posting into a void.
_RECIPIENT = getattr(settings, "contact_email", None) or "nikolaus.correll@gmail.com"

_MIN_FILL_SECONDS = 3.0


class ContactBody(BaseModel):
    name:    str = Field(min_length=1, max_length=120)
    email:   EmailStr
    message: str = Field(min_length=10, max_length=4000)
    company: str = Field("", max_length=160)
    # Honeypot: hidden from people, so anything here is a bot.
    company_website: str = ""
    # Milliseconds the form was on screen before submitting.
    elapsedMs: Optional[int] = None


@router.post("/")
@limiter.limit("5/hour")
async def submit_contact(request: Request, body: ContactBody):
    """Always answers 200 `{ok: true}`.

    A bot that learns *which* of its attempts was rejected learns how to get
    through; a person only ever sees the honest path. The distinction lives in
    the logs, not in the response.
    """
    trap = bool(body.company_website.strip())
    too_fast = body.elapsedMs is not None and body.elapsedMs < _MIN_FILL_SECONDS * 1000
    if trap or too_fast:
        log.info("contact dropped (honeypot=%s, too_fast=%s) from=%s",
                 trap, too_fast, body.email)
        return {"ok": True}

    # The visitor's text never reaches a header — it goes in the body only, and
    # the subject is built from a length-capped name with newlines stripped
    # (the mailer strips them again; this keeps the log line clean too).
    who = body.name.replace("\r", " ").replace("\n", " ").strip()[:80]
    subject = f"Taktline enquiry from {who}"
    lines = [
        f"Name:    {who}",
        f"Email:   {body.email}",
        f"Company: {body.company.strip()[:160] or '—'}",
        "",
        body.message.strip(),
        "",
        "—",
        f"Sent from the taktline.com contact form · {request.client.host if request.client else 'unknown'}",
    ]
    try:
        await mailer.send(_RECIPIENT, subject, "\n".join(lines))
    except Exception:
        # A failed relay must not show the visitor a stack trace, and must not
        # lose the message: it is in the log either way.
        log.exception("contact email failed; message from %s follows:\n%s",
                      body.email, "\n".join(lines))
    return {"ok": True}
