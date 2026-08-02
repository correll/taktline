"""The public order-tracking page.

The only endpoint in Taktline written for somebody who is not our customer and
has no account, pointed at a customer's production data. So the tests are mostly
about what it must *not* do: answer for a company that has not switched it on,
answer to a guessed token, distinguish "no such order" from "not shared", or say
one word about any other order.
"""

import asyncio
import uuid

import pytest

from app.core import tracking
from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _line(a: Actor):
    """A four-step process with a product that starts at the first station."""
    ids = [a.req("POST", "/stations/", {**STATION, "name": n}).json()["_id"]
           for n in ("Saw", "Weld", "Paint", "Pack")]
    proc = a.req("POST", "/processes/", {"name": "Brackets"}).json()["_id"]
    for i in range(3):
        a.req("POST", "/routes/", {"processId": proc, "load": ids[i],
                                   "unload": ids[i + 1], "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Bracket", "processId": proc,
                                             "startStationId": ids[0]}).json()["_id"]
    return ids, proc, tmpl


def _order(a: Actor, tmpl: str, qty: int = 10):
    r = a.req("POST", "/orders/", {"productTemplateId": tmpl, "quantity": qty,
                                   "source": "manual", "externalRef": "SO-4471"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _set_tracking(company_id: str, on: bool, steps: bool = True):
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import GlobalSettings

    async def go():
        async with SessionLocal() as s:
            row = (await s.execute(select(GlobalSettings).where(
                GlobalSettings.companyId == uuid.UUID(company_id)))).scalars().first()
            if row is None:
                row = GlobalSettings(companyId=uuid.UUID(company_id))
                s.add(row)
            row.orderTracking = on
            row.orderTrackingSteps = steps
            await s.commit()
    asyncio.run(go())


def _path(order: dict) -> str:
    """The tracking path, taken from the URL the API hands the shop."""
    return "/" + order["trackingUrl"].split("/", 3)[3]


# ─── The happy path ──────────────────────────────────────────────────────────

def test_a_customer_can_follow_their_order(actor):
    a = actor()
    bootstrap_admin(a, "Bramble Metalworks")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    r = Actor().req("GET", _path(order).replace("/o/", "/track/"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference"] == "SO-4471"
    assert body["product"] == "Bracket"
    assert (body["quantity"], body["quantityDone"]) == (10, 0)
    assert body["stepTotal"] == 4
    assert [s["name"] for s in body["steps"]] == ["Saw", "Weld", "Paint", "Pack"]


def test_the_page_carries_a_preview_a_chat_app_can_read(actor):
    """These get pasted into email, WhatsApp and Teams, all of which fetch the
    URL and show a preview before any browser runs."""
    a = actor()
    bootstrap_admin(a, "Preview co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    r = Actor().req("GET", _path(order))
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'property="og:title" content="Bracket · SO-4471' in r.text
    assert 'property="og:description"' in r.text
    # And it must not end up in a search index: the token makes it unguessable,
    # but a customer forwarding it into a public forum should not also be
    # handing Google a permanent copy of somebody's production status.
    assert 'name="robots" content="noindex, nofollow"' in r.text


def test_progress_follows_the_line_before_the_first_unit_finishes(actor):
    """Otherwise a customer watching a genuinely half-built order sees a flat 0%
    for days and concludes nothing is happening."""
    a = actor()
    bootstrap_admin(a, "Progress co")
    ids, proc, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    track = f"/track/{order['id']}/{tracking.token_for(uuid.UUID(order['id']))}"
    first = Actor().req("GET", track).json()

    # Move the order's lots two steps down the line.
    cards = a.req("GET", "/cards/").json()
    mine = [c for c in cards if c.get("orderId") == order["id"]]
    assert mine, "the release should have seeded a lot"
    for c in mine:
        for target in (ids[1], ids[2]):
            a.req("POST", f"/cards/{c['_id']}/move",
                  {"fromStationId": list(c["bins"])[0] if c.get("bins") else ids[0],
                   "toStationId": target, "quantity": c["totalQuantity"]})
            c = a.req("GET", f"/cards/{c['_id']}").json()

    later = Actor().req("GET", track).json()
    assert later["percent"] > first["percent"], (first, later)
    assert later["stepIndex"] > (first["stepIndex"] or 0), (first, later)
    assert later["steps"][later["stepIndex"]]["current"] is True


# ─── What it must refuse ─────────────────────────────────────────────────────

def test_tracking_is_off_until_the_shop_turns_it_on(actor):
    """Publishing anything about production is the shop's decision."""
    a = actor()
    bootstrap_admin(a, "Private co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)

    assert Actor().req("GET", _path(order)).status_code == 404
    _set_tracking(a.company, True)
    assert Actor().req("GET", _path(order)).status_code == 200


def test_switching_it_off_stops_every_link_at_once(actor):
    a = actor()
    bootstrap_admin(a, "Regret co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)
    assert Actor().req("GET", _path(order)).status_code == 200

    _set_tracking(a.company, False)
    assert Actor().req("GET", _path(order)).status_code == 404

    # And switching it back on restores the same link rather than invalidating
    # every one a customer has bookmarked.
    _set_tracking(a.company, True)
    assert Actor().req("GET", _path(order)).status_code == 200


def test_a_guessed_token_is_refused(actor):
    a = actor()
    bootstrap_admin(a, "Guarded co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    for bad in ("0" * 24, "deadbeef", tracking.token_for(uuid.uuid4())):
        assert Actor().req("GET", f"/o/{order['id']}/{bad}").status_code == 404, bad


def test_a_real_order_is_indistinguishable_from_a_missing_one(actor):
    """A different answer for an order that exists would make this a way to
    find out whether a company has one."""
    a = actor()
    bootstrap_admin(a, "Oracle co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)          # exists, tracking off
    ghost = str(uuid.uuid4())        # does not exist

    real = Actor().req("GET", f"/o/{order['id']}/{'0' * 24}")
    fake = Actor().req("GET", f"/o/{ghost}/{'0' * 24}")
    assert real.status_code == fake.status_code == 404
    assert real.text == fake.text


def test_one_order_says_nothing_about_another(actor):
    a = actor()
    bootstrap_admin(a, "Two orders co")
    _, _, tmpl = _line(a)
    mine = _order(a, tmpl, qty=3)
    other = a.req("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 99,
                                       "source": "manual",
                                       "externalRef": "SECRET-CUSTOMER"}).json()
    _set_tracking(a.company, True)

    body = Actor().req("GET", f"/track/{mine['id']}/"
                              f"{tracking.token_for(uuid.UUID(mine['id']))}").text
    assert "SECRET-CUSTOMER" not in body
    assert "99" not in body
    assert other["id"] not in body


def test_a_shop_can_hide_its_process(actor):
    """Plenty will happily say "60% done" while not wanting to tell a customer
    they subcontract the plating."""
    a = actor()
    bootstrap_admin(a, "Discreet co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True, steps=False)

    body = Actor().req("GET", f"/track/{order['id']}/"
                              f"{tracking.token_for(uuid.UUID(order['id']))}").json()
    assert body["steps"] is None
    assert body["showSteps"] is False
    for station in ("Saw", "Weld", "Paint", "Pack"):
        assert station not in str(body)
    # The number a customer actually wants still works.
    assert body["quantity"] == 10


def test_tracking_needs_no_account(actor):
    a = actor()
    bootstrap_admin(a, "Anonymous co")
    _, _, tmpl = _line(a)
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    stranger = Actor()
    assert stranger.tc.cookies.get("taktline_session") is None
    assert stranger.req("GET", _path(order)).status_code == 200


def test_tokens_differ_per_order(actor):
    """Guard the guard: a derivation that ignored the order id would pass every
    test above and hand one customer everybody's link."""
    ids = [uuid.uuid4() for _ in range(50)]
    tokens = {tracking.token_for(i) for i in ids}
    assert len(tokens) == 50
    assert all(len(t) == 24 for t in tokens)


def test_an_erp_node_is_not_a_step(actor):
    """A link into Shopify or out to ShipStation is a boundary, not a place work
    happens. Counting one would show a customer "shipstation" as an operation and
    inflate the denominator — a four-step line reporting 50% when it is three
    quarters done."""
    a = actor()
    bootstrap_admin(a, "Wired co")
    ids, proc, tmpl = _line(a)
    dock = a.req("POST", "/stations/", {**STATION, "name": "ShipStation",
                                        "integrationProvider": "shipstation",
                                        "integrationRole": "sink"}).json()["_id"]
    r = a.req("POST", "/routes/", {"processId": proc, "load": ids[3],
                                   "unload": dock, "quantity": 1})
    assert r.status_code == 201, r.text

    order = _order(a, tmpl)
    _set_tracking(a.company, True)
    body = Actor().req("GET", f"/track/{order['id']}/"
                              f"{tracking.token_for(uuid.UUID(order['id']))}").json()
    assert body["stepTotal"] == 4, body["steps"]
    assert [s["name"] for s in body["steps"]] == ["Saw", "Weld", "Paint", "Pack"]
    assert "ShipStation" not in str(body)


# ─── Tracking a lot, not only an order ───────────────────────────────────────

def _lot(a: Actor, tmpl: str, proc: str, station: str, qty: int = 6):
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                  "lotNum": "L-2208", "totalQuantity": qty,
                                  "bins": {station: {"count": qty}}})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_lot_is_trackable_too(actor):
    """Orders only exist where an ERP or a CSV made one. The shops most likely
    to want to answer "where is my order?" enter work by hand, and for them the
    only object that exists is the lot — so tracking that could only follow an
    order was a feature they could not reach."""
    a = actor()
    bootstrap_admin(a, "By hand co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])
    _set_tracking(a.company, True)

    body = Actor().req("GET", f"/track/{card['_id']}/"
                              f"{tracking.token_for(uuid.UUID(card['_id']))}").json()
    assert body["reference"] == "L-2208"        # the lot code, which is what a shop quotes
    assert body["product"] == "Bracket"
    assert body["quantity"] == 6
    assert [s["name"] for s in body["steps"]] == ["Saw", "Weld", "Paint", "Pack"]
    assert body["steps"][0]["current"] is True


def test_a_lot_at_the_last_step_reads_as_complete(actor):
    """A lot is one group that moves together, so its completion is its
    position — there is no partial "units done" the way an order has."""
    a = actor()
    bootstrap_admin(a, "Finished co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])
    _set_tracking(a.company, True)
    for i in range(3):
        a.req("POST", f"/cards/{card['_id']}/move",
              {"fromStationId": ids[i], "toStationId": ids[i + 1], "quantity": 6})

    body = Actor().req("GET", f"/track/{card['_id']}/"
                              f"{tracking.token_for(uuid.UUID(card['_id']))}").json()
    assert body["status"] == "completed"
    assert body["percent"] == 100


def test_a_lot_token_does_not_open_an_order(actor):
    a = actor()
    bootstrap_admin(a, "Distinct co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])
    order = _order(a, tmpl)
    _set_tracking(a.company, True)

    crossed = f"/track/{order['id']}/{tracking.token_for(uuid.UUID(card['_id']))}"
    assert Actor().req("GET", crossed).status_code == 404


# ─── The QR code, and the operator half of it ────────────────────────────────

def test_the_qr_is_guarded_exactly_like_the_page(actor):
    """It encodes the tracking URL, so serving one for an unshared job would
    leak the same thing the page refuses to."""
    a = actor()
    bootstrap_admin(a, "QR co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])
    qr = f"/o/{card['_id']}/{tracking.token_for(uuid.UUID(card['_id']))}/qr.svg"

    assert Actor().req("GET", qr).status_code == 404, "served before tracking was on"
    _set_tracking(a.company, True)
    r = Actor().req("GET", qr)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content
    assert Actor().req("GET", f"/o/{card['_id']}/{'0' * 24}/qr.svg").status_code == 404


def test_a_customer_is_never_offered_the_work_button(actor):
    """The token is a read capability handed to somebody outside the company. It
    must not become a way to start a timer on their shop floor."""
    a = actor()
    bootstrap_admin(a, "Stranger co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])
    _set_tracking(a.company, True)
    track = f"/track/{card['_id']}/{tracking.token_for(uuid.UUID(card['_id']))}"

    assert Actor().req("GET", track).json()["work"] is None


def test_a_member_scanning_the_same_code_gets_a_way_to_the_bench(actor):
    a = actor()
    bootstrap_admin(a, "Operator co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0], qty=6)
    _set_tracking(a.company, True)

    body = a.req("GET", f"/track/{card['_id']}/"
                        f"{tracking.token_for(uuid.UUID(card['_id']))}").json()
    assert body["work"] == {"cardId": card["_id"], "stationId": ids[0], "units": 6}


def test_a_member_of_another_company_gets_nothing(actor):
    """Signed in is not enough — it has to be *their* floor."""
    owner, outsider = actor(), actor()
    bootstrap_admin(owner, "Ours co")
    bootstrap_admin(outsider, "Theirs co")
    ids, proc, tmpl = _line(owner)
    card = _lot(owner, tmpl, proc, ids[0])
    _set_tracking(owner.company, True)

    body = outsider.req("GET", f"/track/{card['_id']}/"
                               f"{tracking.token_for(uuid.UUID(card['_id']))}").json()
    assert body["work"] is None
    assert body["reference"] == "L-2208"      # they can still read it, like anyone


def test_the_printed_label_carries_both_codes(actor):
    """Two readers: a shop scanner driving scan-to-advance, and a phone camera.
    One label serves the floor and whoever is waiting on it."""
    a = actor()
    bootstrap_admin(a, "Label co")
    ids, proc, tmpl = _line(a)
    card = _lot(a, tmpl, proc, ids[0])

    zpl = a.req("GET", f"/cards/{card['_id']}/label").text
    assert "^BCN" in zpl, "Code128 for the shop scanner"
    assert "^BQN" in zpl, "QR for a phone"
    assert tracking.token_for(uuid.UUID(card["_id"])) in zpl
