"""The supply-chain network: inviting a supplier, and reading what they publish.

Manufacturing is a chain, and the loop this opens runs both ways. A shop that
shares status links with its customers is showing Taktline to people who run
factories. A shop that wants to see *its own* suppliers has a reason to ask them
to use it — and an invitation from a customer carries commercial weight that no
referral link has.

Two rules shape the whole thing.

**An invitation grants nothing.** Accepting one creates an ordinary, independent
company. The inviter gets attribution and nothing else: no access, no rights, no
visibility except what the supplier chooses to send them, which is the same
public tracking link any customer gets. Anything stronger would make signing up
an act of submission to a customer, and no supplier does that twice.

**A supplier's status is fetched by the browser, never by this server.** The URL
comes from a user, and a server that fetches user-supplied URLs is an SSRF
waiting to be found — this codebase already had to fence one (see
`map_settings._localise_remote_image`). The browser can do it instead, the
tracking endpoint is public and CORS-open, and cookies are never sent
cross-origin, so a pasted link can only ever read the public view.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

#: What a tracking link looks like: /o/<uuid>/<token>. Anchored, because the
#: point is to refuse anything that is not one.
_PATH = re.compile(
    r"^/o/([0-9a-fA-F-]{36})/([0-9a-f]{16,64})/?$"
)


def parse_tracking_url(raw: str) -> Optional[str]:
    """Normalise a pasted supplier link, or None if it is not one.

    Refuses on purpose: anything that is not http(s) (a `javascript:` URL pasted
    into a field that later becomes an href is the classic version of this), and
    anything whose path is not a tracking page. Returning None rather than
    raising lets the caller decide between a 400 and simply not showing a panel.

    **Any host is allowed**, and that is deliberate rather than an oversight. A
    supplier may be running Taktline on their own hardware, and restricting this
    to taktline.com would break the loop for exactly the customers who bought
    the on-premise tier. The safety does not come from trusting the host: the
    fetch happens in the browser of somebody who chose to paste that link, the
    response is rendered as React text (escaped), and nothing about the reader
    is sent — no cookies cross-origin, and no credentials in the URL.
    """
    if not raw or len(raw) > 500:
        return None
    try:
        u = urlparse(raw.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    if u.username or u.password:            # credentials in a URL: never
        return None
    if not _PATH.match(u.path):
        return None
    # Drop query and fragment: a tracking link needs neither, and keeping them
    # would let somebody smuggle content through a field we display.
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def status_url(tracking_url: str) -> Optional[str]:
    """The JSON endpoint behind a tracking page — what the browser actually
    fetches. `/o/<id>/<token>` → `/track/<id>/<token>`."""
    clean = parse_tracking_url(tracking_url)
    if clean is None:
        return None
    return clean.replace("/o/", "/track/", 1)


# ─── Invitations ─────────────────────────────────────────────────────────────

def invite_body(*, customer: str, supplies: str, link: str) -> str:
    """The email a supplier gets.

    It leads with who is asking and what they buy, because that is the only
    reason this message is not spam — and it says plainly that the customer
    gains no access, because that is the first thing a supplier will wonder.
    """
    what = f" — you make their {supplies}" if supplies.strip() else ""
    return (
        f"{customer} uses Taktline to run their production, and they would like "
        f"to see where the parts they buy from you are{what}.\n\n"
        f"Taktline is a live board for a shop floor: every job on a map of your "
        f"own factory, with the timings that come out of running it. Sharing "
        f"status is one link per job — you choose which, and you can stop at any "
        f"time.\n\n"
        f"Free for up to 3 stations, no card:\n\n{link}\n\n"
        f"To be clear about what {customer} gets: nothing, unless you send it. "
        f"Your account is your own — they cannot see your floor, your other "
        f"customers, or anything you have not shared.\n"
    )
