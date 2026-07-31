"""Absurd inputs, and lines far bigger than anyone draws by hand.

Two kinds of harm that are easy to miss because no reasonable person types
these numbers.

**Overflow.** Quantities are Postgres `INTEGER` — four bytes. A split
multiplies: advancing `n` units along a branch of weight `w` mints `n × w`.
Two numbers that each fit produce one that does not, and the failure mode of an
overflow in an inventory system is not an error message, it is a negative
count. The answer must be a refusal with a readable reason, never a 500 and
never a wrapped number.

**Scale.** The pull walk propagates demand across the whole process DAG, and it
was rewritten *away* from per-path recursion — which is what you do after
something blew up exponentially. This is a shared server: one customer drawing
a wide, deep, diamond-heavy line must not be able to stall it for everybody
else. So the large-graph tests assert a wall-clock ceiling, not just an answer.
"""

import time

import pytest

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}

from app.models.common import MAX_UNITS, MAX_WEIGHT

INT32_MAX = 2_147_483_647


def _st(a: Actor, name: str, **kw) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name, **kw}).json()["_id"]


def _split_line(a: Actor, weight=4):
    src, tube, off = _st(a, "Saw"), _st(a, "Tubes"), _st(a, "Offcuts")
    proc = a.req("POST", "/processes/", {"name": "Cutting"}).json()["_id"]
    made = []
    for target in (tube, off):
        made.append(a.req("POST", "/routes/", {"processId": proc, "load": src,
                                               "unload": target, "quantity": 1}).json())
    a.req("PUT", f"/routes/{made[0]['_id']}", {**made[0], "quantity": weight})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Bar", "processId": proc,
                                             "startStationId": src}).json()["_id"]
    return proc, src, tube, off, tmpl


def _units(a: Actor):
    out: dict = {}
    for c in a.req("GET", "/cards/").json():
        for sid, b in c["bins"].items():
            out[sid] = out.get(sid, 0) + b["count"]
    return out


# ── Numbers that do not fit ─────────────────────────────────────────────────

@pytest.mark.parametrize("quantity",
                         [INT32_MAX, INT32_MAX + 1, 10 ** 15, MAX_UNITS + 1, -1, 0])
def test_an_absurd_lot_size_is_refused_not_stored(actor, quantity):
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, tmpl = _split_line(a)

    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                  "lotNum": "BIG", "totalQuantity": quantity,
                                  "bins": {src: {"count": quantity}}})
    assert r.status_code >= 400, f"a lot of {quantity} was accepted"
    assert r.status_code < 500, f"a lot of {quantity} crashed the server ({r.status_code})"
    assert a.req("GET", "/cards/").json() == [], "a refused lot was stored anyway"


def test_a_split_cannot_multiply_its_way_past_the_column(actor):
    """The dangerous one, because both inputs are individually legal: a lot
    that fits, times a weight that fits, is a lot that does not. In an
    inventory system an overflow does not raise — it wraps, and a negative
    count is material the system believes it owes."""
    a = actor(); bootstrap_admin(a)
    # Both numbers are exactly what the API says it accepts. Their product is
    # ten billion, which is not.
    proc, src, tube, off, tmpl = _split_line(a, weight=MAX_WEIGHT)

    made = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "BAR", "totalQuantity": MAX_UNITS,
                                     "bins": {src: {"count": MAX_UNITS}}})
    assert made.status_code == 201, f"the documented maximum lot was refused: {made.text[:160]}"

    r = a.req("POST", f"/cards/{made.json()['_id']}/advance",
              {"fromStationId": src, "toStationId": tube, "quantity": MAX_UNITS})
    assert r.status_code < 500, \
        f"a legal lot times a legal weight crashed the server ({r.status_code})"
    assert r.status_code >= 400, "the multiply produced ten billion units"
    for station, n in _units(a).items():
        assert 0 <= n <= MAX_UNITS, \
            f"{station} holds {n} — past the ceiling the API enforces on the way in"


@pytest.mark.parametrize("weight", [INT32_MAX, 10 ** 12, MAX_WEIGHT + 1, 0, -3])
def test_an_absurd_branch_weight_is_refused(actor, weight):
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, tmpl = _split_line(a)
    route = [r for r in a.req("GET", "/routes/").json() if r["unload"] == tube][0]

    r = a.req("PUT", f"/routes/{route['_id']}", {**route, "quantity": weight})
    assert r.status_code >= 400, f"a branch weight of {weight} was accepted"
    assert r.status_code < 500, f"a branch weight of {weight} crashed the server"


def test_an_absurd_order_is_refused(actor):
    """A release runs the pull walk, multiplying demand by every weight on the
    way up. A big enough order turns that into a very large number of seeded
    lots, which is a denial of service written as a purchase order."""
    a = actor(); bootstrap_admin(a)
    proc, src, tube, off, tmpl = _split_line(a)

    r = a.req("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 10 ** 12,
                                   "source": "manual", "externalRef": "HUGE"})
    assert r.status_code >= 400, "an order for a trillion units was released"
    assert r.status_code < 500, f"it crashed the server instead ({r.status_code})"


# ── Lines nobody draws by hand ──────────────────────────────────────────────

def _wide_deep_line(a: Actor, depth=12, width=6):
    """A chain `depth` long where every level fans into `width` branches that
    immediately reconverge — a stack of diamonds, the shape that makes a
    per-path walk explode (width ** depth paths, ~2 billion here) while the DAG
    itself stays small."""
    proc = a.req("POST", "/processes/", {"name": "Deep"}).json()["_id"]
    spine = [_st(a, "L0")]
    for d in range(1, depth + 1):
        nxt = _st(a, f"L{d}")
        mids = [_st(a, f"M{d}_{w}") for w in range(width)]
        for m in mids:
            a.req("POST", "/routes/", {"processId": proc, "load": spine[-1],
                                       "unload": m, "quantity": 1})
            a.req("POST", "/routes/", {"processId": proc, "load": m,
                                       "unload": nxt, "quantity": 1})
        spine.append(nxt)
    tmpl = a.req("POST", "/lot-templates/", {"name": "Deep widget", "processId": proc,
                                             "startStationId": spine[-1]}).json()["_id"]
    return proc, spine, tmpl


def test_a_stack_of_diamonds_does_not_hang_the_server(actor):
    """`width ** depth` distinct paths, on a graph of a hundred-odd nodes. A
    walk that enumerates paths never returns; one that propagates over the DAG
    finishes immediately. This is multi-tenant, so 'never returns' is every
    other customer's outage too."""
    a = actor(); bootstrap_admin(a)
    proc, spine, tmpl = _wide_deep_line(a)
    target = spine[-1]

    t0 = time.monotonic()
    preview = a.req("GET", f"/merge/{target}")
    elapsed = time.monotonic() - t0
    assert preview.status_code == 200, preview.text
    assert elapsed < 10, f"the merge preview took {elapsed:.1f}s on a graph of ~100 nodes"

    t0 = time.monotonic()
    pull = a.req("POST", f"/merge/{target}/pull", {"quantity": 1})
    elapsed = time.monotonic() - t0
    assert pull.status_code < 500, pull.text
    assert elapsed < 20, f"the pull walk took {elapsed:.1f}s"


def test_a_big_line_still_answers_the_pages_that_draw_it(actor):
    """The floor plan, the board and the statistics table all load the whole
    line. They have to stay usable at a size a real multi-cell plant reaches."""
    a = actor(); bootstrap_admin(a)
    _wide_deep_line(a, depth=10, width=5)

    for path in ("/stations/", "/routes/", "/processes/", "/cards/", "/sessions/stats"):
        t0 = time.monotonic()
        r = a.req("GET", path)
        elapsed = time.monotonic() - t0
        assert r.status_code == 200, f"{path}: {r.text[:120]}"
        assert elapsed < 15, f"{path} took {elapsed:.1f}s"


def test_a_long_chain_does_not_recurse_off_the_stack(actor):
    """Depth alone. A recursive walk on a 200-deep line hits Python's recursion
    limit, and a RecursionError arrives as a 500 with nothing useful in it."""
    a = actor(); bootstrap_admin(a)
    proc = a.req("POST", "/processes/", {"name": "Long"}).json()["_id"]
    ids = [_st(a, f"C{i}") for i in range(200)]
    for x, y in zip(ids, ids[1:]):
        a.req("POST", "/routes/", {"processId": proc, "load": x, "unload": y, "quantity": 1})
    tmpl = a.req("POST", "/lot-templates/", {"name": "Long widget", "processId": proc,
                                             "startStationId": ids[0]}).json()["_id"]

    r = a.req("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 1,
                                   "source": "manual", "externalRef": "LONG-1"})
    assert r.status_code < 500, f"a 200-station line broke the release: {r.text[:200]}"
    assert a.req("GET", f"/merge/{ids[-1]}").status_code == 200
