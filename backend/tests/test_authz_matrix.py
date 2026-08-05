"""Every endpoint, against every principal, with the expectations *derived*.

The role a given endpoint requires is already written down — in the dependency
it declares. So rather than a hand-maintained table that drifts, this reads the
app's own dependency tree, works out what each route claims to require, and
then checks that the claim is actually enforced by calling it as somebody one
tier short.

That matters because the mistake this catches is not a wrong `if`. It is a new
endpoint wired to `get_active_company` when it meant `require_super_admin` —
which looks completely correct in review, has no failing test anywhere, and
hands every operator on the floor the ability to redraw the line. Deriving the
expectation from the declaration means a new endpoint is covered the day it
lands, and the only way to be wrong is to declare the wrong thing, which is at
least visible on the line you are reading.

`public` is derived too: a route with no auth dependency in its tree. Nobody
has to maintain a list of what is meant to be reachable signed out — the list
IS the code, and the test simply insists everything else refuses.
"""

import pytest

from tests.helpers import Actor, add_member, bootstrap_admin, flat_routes
from tests.test_tenancy_sweep import BODIES, STATION, _victim_line

# What each auth dependency means, in the order the role ladder runs.
GUARDS = {
    "require_super_admin": "super_admin",
    "require_admin": "admin",
    "get_active_company": "user",
    "require_scope.<locals>.dep": "scope",     # key OR session, role varies
    "require_platform_staff": "platform",
    "require_platform_owner": "platform",
    "get_current_user": "authenticated",
}
RANK = {"authenticated": 0, "user": 1, "admin": 2, "super_admin": 3}


def _routes():
    from app.main import app
    def walk(d):
        yield d
        for s in d.dependencies:
            yield from walk(s)

    out = []
    for r in flat_routes(app):
        methods = getattr(r, "methods", None)
        if not methods or not hasattr(r, "dependant"):
            continue
        guards = set()
        for d in walk(r.dependant):
            name = getattr(getattr(d, "call", None), "__qualname__", None)
            if name in GUARDS:
                guards.add(GUARDS[name])
        for m in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((m, r.path, guards))
    return sorted(out, key=lambda t: (t[1], t[0]))


def _required(guards):
    """The strictest company role this route declares, or None."""
    ranked = [g for g in guards if g in RANK]
    return max(ranked, key=lambda g: RANK[g]) if ranked else None


@pytest.fixture(scope="module")
def world():
    """One company, one of everything in it, and a principal at every tier."""
    owner = Actor()
    bootstrap_admin(owner, "Acme")
    ids = _victim_line(owner)

    admin, user = Actor(), Actor()
    add_member(owner, admin, role="admin")
    add_member(owner, user, role="user")
    return {"ids": ids, "super_admin": owner, "admin": admin, "user": user,
            "anonymous": Actor()}


def _call(actor: Actor, method: str, path: str, ids: dict):
    target = path
    for name, value in ids.items():
        target = target.replace("{" + name + "}", str(value))
    if "{" in target:
        return None
    body = BODIES.get((method, path))
    if body is not None:
        body = {k: (ids["station_id"] if v == "" else v) for k, v in body.items()}
    elif method in {"POST", "PUT", "PATCH"}:
        body = {}
    return actor.req(method, target, body).status_code


def test_the_matrix_is_not_empty(world):
    """Guard the guard: if the dependency walk stopped finding guards, every
    assertion below would pass by describing nothing."""
    routes = _routes()
    assert len(routes) > 80, len(routes)
    by = {}
    for _m, _p, g in routes:
        by[_required(g)] = by.get(_required(g), 0) + 1
    assert by.get("super_admin", 0) >= 15, by
    assert by.get("user", 0) >= 15, by
    assert by.get(None, 0) >= 5, by            # some genuinely public routes exist


def test_every_guarded_endpoint_refuses_an_anonymous_caller(world):
    """The one that would matter most if it broke, and the cheapest to state."""
    leaked = []
    for method, path, guards in _routes():
        if not guards:
            continue                            # public by declaration
        code = _call(world["anonymous"], method, path, world["ids"])
        if code is not None and code < 400:
            leaked.append(f"{method} {path} -> {code}")
    assert leaked == [], "reachable signed out:\n  " + "\n  ".join(leaked)


@pytest.mark.parametrize("tier,blocked", [("user", {"admin", "super_admin"}),
                                          ("admin", {"super_admin"})])
def test_a_principal_cannot_reach_above_its_tier(world, tier, blocked):
    """A `user` must not reach an admin endpoint; an `admin` must not reach a
    super-admin one. Anything that answers is a privilege escalation, and the
    ones worth fearing are structural configuration — stations, routes,
    templates — where an operator's mistake silently redraws the line."""
    over = []
    for method, path, guards in _routes():
        need = _required(guards)
        if need not in blocked:
            continue
        code = _call(world[tier], method, path, world["ids"])
        if code is not None and code < 400:
            over.append(f"{method} {path} declares {need}, answered {tier} with {code}")
    assert over == [], "privilege escalation:\n  " + "\n  ".join(over)


def test_platform_endpoints_are_invisible_to_ordinary_members(world):
    """Staff routes 404 rather than 403 — a 403 confirms the endpoint exists,
    and the platform surface is not a customer's business."""
    wrong = []
    for method, path, guards in _routes():
        if "platform" not in guards:
            continue
        for tier in ("user", "admin", "super_admin"):
            code = _call(world[tier], method, path, world["ids"])
            if code is not None and code != 404:
                wrong.append(f"{method} {path} -> {code} for a company {tier}")
    assert wrong == [], "platform surface visible to tenants:\n  " + "\n  ".join(wrong)


def test_an_api_key_is_never_a_super_admin(world):
    """A key authenticates as the admin tier. If one could reach super-admin
    config, a leaked integration token would be able to redraw the line rather
    than merely release orders against it."""
    key = world["super_admin"].req(
        "POST", "/api-keys/", {"name": "sweeper",
                               "scopes": ["orders", "reports", "cards:advance"]}).json()
    token = key.get("key") or key.get("token")
    assert token, key

    caller = Actor()
    over = []
    for method, path, guards in _routes():
        if _required(guards) != "super_admin":
            continue
        target = path
        for name, value in world["ids"].items():
            target = target.replace("{" + name + "}", str(value))
        if "{" in target:
            continue
        body = BODIES.get((method, path)) or ({} if method in {"POST", "PUT", "PATCH"} else None)
        r = caller.req(method, target, body, headers={"X-Api-Key": token})
        if r.status_code < 400:
            over.append(f"{method} {path} -> {r.status_code}")
    assert over == [], "an API key reached super-admin config:\n  " + "\n  ".join(over)
