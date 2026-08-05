"""The supply-chain loop: inviting a supplier, and reading what they publish.

The property this file exists to protect is the one a supplier will ask about
before they sign up: **an invitation grants the inviter nothing.** Everything
else here is input validation on a string that a browser will later fetch and
render.
"""

import uuid

import pytest

from app.core import network
from tests.helpers import Actor, add_member, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}

GOOD = ("https://taktline.com/o/6b548e64-d0e6-4112-a345-2fc981ed78ff"
        "/9abe409021dc8e1ed8212c93")


class Outbox:
    def __init__(self): self.sent = []
    async def send(self, to, subject, body): self.sent.append((to, subject, body))


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr("app.core.email.mailer", box, raising=False)
    monkeypatch.setattr("app.routers.network.mailer", box, raising=False)
    return box


# ─── What a pasted link may be ───────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "https://taktline.com/",                       # not a tracking path
    "https://taktline.com/o/not-a-uuid/abc123def4567890",
    "http://user:password@taktline.com/o/6b548e64-d0e6-4112-a345-2fc981ed78ff/9abe409021dc8e1ed8212c93",
    "",
    "x" * 600,
])
def test_hostile_links_are_refused(raw):
    assert network.parse_tracking_url(raw) is None


def test_a_real_link_survives_and_loses_its_query():
    """Query and fragment are dropped: a tracking link needs neither, and
    keeping them would let somebody smuggle content through a field we show."""
    assert network.parse_tracking_url(GOOD + "?x=<script>#frag") == GOOD
    assert network.parse_tracking_url(f"  {GOOD}/  ") == GOOD


def test_any_host_is_allowed():
    """A supplier may run Taktline on their own hardware. Restricting this to
    taktline.com would break the loop for exactly the customers who bought the
    on-premise tier."""
    onprem = GOOD.replace("taktline.com", "taktline.fenwick-castings.local:8000")
    assert network.parse_tracking_url(onprem) == onprem


def test_the_browser_is_told_where_the_json_is():
    assert network.status_url(GOOD).endswith(
        "/track/6b548e64-d0e6-4112-a345-2fc981ed78ff/9abe409021dc8e1ed8212c93")
    assert network.status_url("javascript:alert(1)") is None


# ─── Storing it ──────────────────────────────────────────────────────────────

def test_a_lot_takes_a_supplier_link_and_refuses_a_hostile_one(actor):
    a = actor()
    bootstrap_admin(a, "Waiting co")
    st = a.req("POST", "/stations/", {**STATION, "name": "Goods in"}).json()["_id"]
    proc = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    tmpl = a.req("POST", "/lot-templates/", {"name": "Casting", "processId": proc,
                                             "startStationId": st}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "IN-1", "totalQuantity": 4,
                                     "bins": {st: {"count": 4}}}).json()

    r = a.req("PUT", f"/cards/{card['_id']}", {"supplierUrl": GOOD})
    assert r.status_code == 200, r.text
    assert r.json()["supplierUrl"] == GOOD

    assert a.req("PUT", f"/cards/{card['_id']}",
                 {"supplierUrl": "javascript:alert(1)"}).status_code == 422
    # …and the good one is still there.
    assert a.req("GET", f"/cards/{card['_id']}").json()["supplierUrl"] == GOOD


def test_a_link_can_be_taken_away_again(actor):
    """Both routers drop nulls from a patch (`if v is not None`), so unlinking
    a supplier would have silently done nothing — the field looks cleared until
    the page is reloaded, which is worse than refusing."""
    a = actor()
    bootstrap_admin(a, "Unlinking co")
    st = a.req("POST", "/stations/", {**STATION, "name": "Goods in"}).json()["_id"]
    proc = a.req("POST", "/processes/", {"name": "P"}).json()["_id"]
    tmpl = a.req("POST", "/lot-templates/", {"name": "Casting", "processId": proc,
                                             "startStationId": st}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "IN-1", "totalQuantity": 4,
                                     "bins": {st: {"count": 4}}}).json()

    for path, body in (("/cards/" + card["_id"], {}),
                       ("/stations/" + st, {**STATION, "name": "Goods in"})):
        a.req("PUT", path, {**body, "supplierUrl": GOOD})
        assert a.req("GET", path).json()["supplierUrl"] == GOOD
        assert a.req("PUT", path, {**body, "supplierUrl": None}).json()["supplierUrl"] is None
        assert a.req("GET", path).json()["supplierUrl"] is None
        # …and an omission still means "leave it alone", which is what the
        # blanket null-drop was protecting in the first place.
        a.req("PUT", path, {**body, "supplierUrl": GOOD})
        a.req("PUT", path, body)
        assert a.req("GET", path).json()["supplierUrl"] == GOOD


def test_a_station_takes_one_too(actor):
    a = actor()
    bootstrap_admin(a, "Queue co")
    st = a.req("POST", "/stations/", {**STATION, "name": "Goods in"}).json()["_id"]
    r = a.req("PUT", f"/stations/{st}", {**STATION, "name": "Goods in",
                                         "supplierUrl": GOOD})
    assert r.status_code == 200, r.text
    assert r.json()["supplierUrl"] == GOOD


# ─── Reading it across the wire ──────────────────────────────────────────────

def test_a_strangers_browser_may_read_a_status_page():
    """The whole feature rests on this and nothing local can catch it: the
    supplier and their customer are two Taktline instances on two hosts, so the
    fetch is cross-origin. The app's ordinary CORS allowlist answers the
    preflight *itself* and 400s a stranger before any route runs — headers set
    on the route are never reached. `PublicReadCORSMiddleware` sits outside it.
    """
    # A client with no session at all — which is what a supplier's customer is.
    tc = Actor().tc
    stranger = {"Origin": "https://customer.example"}

    pre = tc.request("OPTIONS", "/track/abc/def", headers={
        **stranger, "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 204
    assert pre.headers["access-control-allow-origin"] == "*"

    # Headers ride on error responses too — an expired link is something the
    # reader is entitled to see rather than have blocked by the browser.
    missing = tc.request("GET", "/track/abc/def", headers=stranger)
    assert missing.status_code == 404
    assert missing.headers["access-control-allow-origin"] == "*"
    # `*` and credentials together is a pairing browsers reject outright, and
    # dropping credentials is the security property: no cookies cross, so a
    # stranger can only ever get the customer view.
    assert "access-control-allow-credentials" not in missing.headers


def test_the_rest_of_the_api_is_not_opened_up():
    """The guard on the guard. A middleware that matched too broadly would hand
    every endpoint to every origin, and the test above would still pass."""
    tc = Actor().tc
    r = tc.request("OPTIONS", "/cards/", headers={"Origin": "https://evil.example",
                                                  "Access-Control-Request-Method": "GET"})
    assert r.status_code == 400
    assert r.headers.get("access-control-allow-origin") != "*"


# ─── Invitations ─────────────────────────────────────────────────────────────

def test_inviting_a_supplier_sends_them_a_reason(outbox, actor):
    a = actor()
    bootstrap_admin(a, "Bramble Metalworks")
    r = a.req("POST", "/network/suppliers",
              {"email": "sales@fenwick.example", "supplies": "castings"})
    assert r.status_code == 201, r.text

    to, subject, body = outbox.sent[-1]
    assert to == "sales@fenwick.example"
    assert "Bramble Metalworks" in subject
    # It leads with who is asking and what they buy — the only thing that makes
    # this not spam.
    assert "castings" in body
    assert "/signup?supplier=" in body
    # And it answers the first question a supplier will have.
    assert "they cannot see your floor" in body


def test_an_invitation_grants_the_inviter_nothing(outbox, actor):
    """The property a supplier will ask about before signing up. Accepting
    creates an ordinary independent company; the inviter gets attribution and
    no access at all."""
    customer, supplier = actor(), actor()
    bootstrap_admin(customer, "Customer co")
    invite = customer.req("POST", "/network/suppliers",
                          {"email": "s@example.com", "supplies": "castings"}).json()

    bootstrap_admin(supplier, "Supplier co")
    marker = next(part for part in outbox.sent[-1][2].split()
                  if part.startswith("http") and "supplier=" in part).split("supplier=")[1]
    accepted = supplier.req("POST", "/companies/",
                            {"name": "Fenwick Castings", "timezone": "UTC",
                             "supplierInvite": marker})
    assert accepted.status_code == 201, accepted.text
    new_company = accepted.json()["id"]

    # Attributed…
    listed = customer.req("GET", "/network/suppliers").json()
    assert [i["accepted"] for i in listed if i["id"] == invite["id"]] == [True]

    # …and utterly powerless. The inviter is not a member and cannot read a thing.
    customer.company = new_company
    assert customer.req("GET", "/stations/").status_code == 403
    assert customer.req("GET", "/cards/").status_code == 403


def test_a_forged_marker_is_ignored_not_fatal(outbox, actor):
    """Failing somebody's signup over a mangled query parameter would be an
    absurd trade."""
    a = actor()
    bootstrap_admin(a, "Arriving co")
    for marker in ("nonsense", f"{uuid.uuid4()}.deadbeef", "..", ""):
        r = a.req("POST", "/companies/", {"name": f"Co {marker[:6]}", "timezone": "UTC",
                                          "supplierInvite": marker})
        assert r.status_code == 201, (marker, r.text)


def test_re_inviting_updates_rather_than_duplicates(outbox, actor):
    """A chased supplier is the normal case, not an error."""
    a = actor()
    bootstrap_admin(a, "Chasing co")
    a.req("POST", "/network/suppliers", {"email": "s@example.com", "supplies": "castings"})
    a.req("POST", "/network/suppliers", {"email": "s@example.com", "supplies": "forgings"})
    listed = a.req("GET", "/network/suppliers").json()
    assert len(listed) == 1
    assert listed[0]["supplies"] == "forgings"
    assert len(outbox.sent) == 2       # sent again, which is the point of chasing


def test_a_sandbox_may_not_email_strangers(outbox):
    a = Actor()
    r = a.req("POST", "/auth/sandbox", {})
    a.company = r.json()["companyId"]
    assert a.req("POST", "/network/suppliers",
                 {"email": "s@example.com"}).status_code == 403
    assert outbox.sent == []


def test_an_operator_cannot_invite(outbox, actor):
    admin, worker = actor(), actor()
    bootstrap_admin(admin, "Roles co")
    add_member(admin, worker, role="user")
    assert worker.req("POST", "/network/suppliers",
                      {"email": "s@example.com"}).status_code == 403


def test_suppliers_are_company_scoped(outbox, actor):
    a, b = actor(), actor()
    bootstrap_admin(a, "Mine co")
    bootstrap_admin(b, "Theirs co")
    a.req("POST", "/network/suppliers", {"email": "secret@example.com"})
    assert b.req("GET", "/network/suppliers").json() == []
