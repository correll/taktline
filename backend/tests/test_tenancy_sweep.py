"""Every endpoint that takes an id, called with somebody else's id.

`test_tenancy.py` checks the endpoints someone thought to check. This one
enumerates the app's own routing table, so an endpoint added next month is
covered the day it lands — which is the only way this stays true, because the
failure is silent: a cross-tenant read returns a perfectly normal 200 and
nobody notices until a customer sees another customer's line.

Two assertions, and the second is the one that matters:

  1. no call from the wrong company succeeds, and
  2. after the entire sweep, the victim's line is byte-for-byte what it was —
     no station renamed, no lot moved, no order cancelled.

A status-code check alone would miss a write that happens before the ownership
check and then reports an error.
"""

import uuid

import pytest

from tests.helpers import Actor, bootstrap_admin, flat_routes

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}

# Not company-scoped by design, and deliberately so:
SKIP_PATHS = {
    "/uploads/{filename}",              # static files, no tenant in the path
    "/invitations/{token}",             # a token IS the authorisation
    "/invitations/{token}/accept",
    "/invitations/{token}/accept-signup",
}

# Bodies good enough to get past request validation and reach the ownership
# check — a 422 would prove nothing about tenancy.
BODIES = {
    ("PUT", "/stations/{station_id}"): {**STATION, "name": "Renamed"},
    ("POST", "/stations/{station_id}/command"): {"command": "ping"},
    ("PUT", "/routes/{route_id}"): {"quantity": 1},
    ("PUT", "/processes/{process_id}"): {"name": "Renamed"},
    ("PUT", "/lot-templates/{template_id}"): {"name": "Renamed"},
    ("PUT", "/cards/{card_id}"): {"totalQuantity": 9, "lotNum": "HACKED"},
    ("PATCH", "/cards/{card_id}/status"): {"status": "working"},
    ("POST", "/cards/{card_id}/move"): {"fromStationId": "", "toStationId": "", "quantity": 1},
    ("POST", "/cards/{card_id}/advance"): {"fromStationId": "", "toStationId": "", "quantity": 1},
    ("POST", "/cards/{card_id}/handoff"): {"fromStationId": "", "integrationStationId": "",
                                           "quantity": 1},
    ("POST", "/cards/{card_id}/unmerge"): {"stationId": "", "quantity": 1},
    ("POST", "/sessions/{session_id}/end"): {"quantity": 1},
    ("POST", "/merge/{station_id}"): {},
    ("POST", "/merge/{station_id}/pull"): {"quantity": 1},
    ("POST", "/orders/{order_id}/cancel"): {},
    ("PATCH", "/companies/{company_id}/members/{user_id}"): {"role": "admin"},
    ("POST", "/companies/{company_id}/invitations"): {"email": "x@example.com", "role": "user"},
    ("PUT", "/platform/users/{user_id}/platform-role"): {"platformRole": "support"},
    ("DELETE", "/platform/companies/{company_id}"): {"confirmName": "Victim"},
}


def _endpoints():
    from app.main import app
    out = []
    for r in flat_routes(app):
        methods = getattr(r, "methods", None)
        if not methods or "{" not in r.path or r.path in SKIP_PATHS:
            continue
        for m in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((m, r.path))
    return sorted(out)


def _victim_line(a: Actor) -> dict:
    """A company with one of everything worth stealing."""
    st = lambda n, **k: a.req("POST", "/stations/", {**STATION, "name": n, **k}).json()["_id"]
    one, two = st("Cutting"), st("Welding")
    proc = a.req("POST", "/processes/", {"name": "Frames"}).json()["_id"]
    route = a.req("POST", "/routes/", {"processId": proc, "load": one, "unload": two,
                                       "quantity": 1}).json()["_id"]
    tmpl = a.req("POST", "/lot-templates/", {"name": "Frame", "processId": proc,
                                             "startStationId": one}).json()["_id"]
    card = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                     "lotNum": "SECRET-1", "totalQuantity": 4,
                                     "bins": {one: {"count": 4}}}).json()["_id"]
    sess = a.req("POST", "/sessions/", {"stationId": one, "cardId": card,
                                        "operatorId": "tablet-01", "quantity": 1}).json()["_id"]
    made = a.req("POST", "/api-keys/", {"name": "k", "scopes": ["orders"]}).json()
    key = made.get("id") or made.get("_id") or str(uuid.uuid4())
    order = a.req("POST", "/orders/", {"productTemplateId": tmpl, "quantity": 2,
                                       "source": "manual", "externalRef": "SECRET-ORDER"})
    me = a.req("GET", "/auth/me").json()
    return {
        "station_id": one, "route_id": route, "process_id": proc, "template_id": tmpl,
        "card_id": card, "session_id": sess, "key_id": key,
        "order_id": order.json().get("_id") if order.status_code < 300 else str(uuid.uuid4()),
        "company_id": a.company,
        "user_id": (me.get("user") or me).get("_id") or (me.get("user") or me).get("id"),
        "event_id": str(uuid.uuid4()), "error_id": str(uuid.uuid4()),
        "invitation_id": str(uuid.uuid4()), "filename": "x.png",
    }


def _state(a: Actor):
    """Everything the victim would notice being changed."""
    return {p: a.req("GET", p).json() for p in
            ("/stations/", "/routes/", "/processes/", "/lot-templates/", "/cards/", "/orders/")}


def _norm(text: str, ids: dict) -> str:
    """Blank out the ids so two answers about two different resources can be
    compared for whether they say the same *thing*."""
    for v in sorted({str(v) for v in ids.values()}, key=len, reverse=True):
        text = text.replace(v, "<ID>")
    return text


@pytest.fixture(scope="module")
def sweep():
    """Call every id-taking endpoint twice: once with the victim's real ids,
    once with ids that exist nowhere. Run once; the tests below read it."""
    victim, thief = Actor(), Actor()
    bootstrap_admin(victim, "Victim")
    bootstrap_admin(thief, "Thief")
    ids = _victim_line(victim)
    nowhere = {k: (str(uuid.uuid4()) if k != "filename" else "nope.png") for k in ids}
    before = _state(victim)

    results = []
    for method, path in _endpoints():
        def fill(table):
            t = path
            for name, value in table.items():
                t = t.replace("{" + name + "}", str(value))
            return t
        real, fake = fill(ids), fill(nowhere)
        if "{" in real:                       # an id shape nobody supplied
            continue
        body = BODIES.get((method, path))
        if body is not None:
            body = {k: (ids["station_id"] if v == "" else v) for k, v in body.items()}
        r1 = thief.req(method, real, body)
        r2 = thief.req(method, fake, body)
        results.append({
            "method": method, "path": path,
            "status": r1.status_code, "control": r2.status_code,
            "body": _norm(r1.text, ids), "control_body": _norm(r2.text, nowhere),
        })

    return {"results": results, "before": before, "after": _state(victim), "ids": ids}


def test_the_sweep_actually_covered_the_api(sweep):
    """Guard the guard: a substitution bug that skipped every route would make
    every assertion below vacuous."""
    assert len(sweep["results"]) >= 40, len(sweep["results"])


def test_no_endpoint_can_tell_a_foreign_id_from_a_nonexistent_one(sweep):
    """The property is INDISTINGUISHABILITY, not the status code.

    Several endpoints answer 2xx for another company's id and are perfectly
    safe doing it: `/cards/{id}/events` filters by company and returns `[]`,
    `/sessions/stats/{id}` returns its empty shape, and deleting a favourite is
    keyed on the *requesting* user, so there is nothing of the victim's to
    delete. None of them reveal that the resource exists.

    Demanding a 404 everywhere would have failed on all three and taught us
    nothing. What must never happen is for a foreign id to produce a different
    answer than an id that exists nowhere — that difference is the probe: it
    tells an attacker which of their guesses are real customers' stations, lots
    and orders, and it is how a leak starts.
    """
    probes = [r for r in sweep["results"]
              if (r["status"], r["body"]) != (r["control"], r["control_body"])]
    assert probes == [], (
        "these answer differently for a real foreign id than for a fake one:\n  "
        + "\n  ".join(f"{r['method']} {r['path']}: {r['status']} vs {r['control']}"
                      for r in probes))


def test_no_endpoint_reports_a_server_error_on_a_foreign_id(sweep):
    """A 500 is not a security hole, but it is the shape of an ownership check
    that runs *after* the work — which is how a write lands before the refusal."""
    crashed = [(r["method"], r["path"], r["status"]) for r in sweep["results"]
               if r["status"] >= 500 or r["control"] >= 500]
    assert crashed == [], f"server errors on foreign ids: {crashed}"


def test_the_victims_line_is_untouched(sweep):
    """The assertion that does not depend on status codes at all."""
    assert sweep["after"] == sweep["before"], "the sweep changed the victim's line"
