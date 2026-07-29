"""Several processes over one set of physical locations.

A location is a place on the floor; a **process** is a route through those
places. The same bench can belong to two value streams, and alternative routing
("this order goes A→C, that one goes A→B→C") is modelled as a second process
rather than a branch — which means every judgement the graph makes has to be
scoped to *one* process or it reads another line's shape as its own.

That scoping is easy to state and easy to lose, and losing it is quiet: a merge
that demands material from a line that never fed it, a pass-through station
frozen because a different product assembles there, a pull seeding queues that
belong to someone else. These scenarios exist to make that loud.

    Shared bench           Alternative routing        Two merges, one bench
    A ─┐                   Fast:  Cut ────► Pack      X ─┐        P ─┐
       ├─► Bench ─► Ship   Slow:  Cut ► Grind ► Pack     ├─► Bench   ├─► Bench
    B ─┘                                              Y ─┘        Q ─┘
    (two processes)        (two processes, one         (two merges at one
                            shared start location)      location, one each)
"""

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _st(a: Actor, name: str) -> str:
    return a.req("POST", "/stations/", {**STATION, "name": name}).json()["_id"]


def _proc(a: Actor, name: str) -> str:
    return a.req("POST", "/processes/", {"name": name}).json()["_id"]


def _route(a: Actor, proc: str, load: str, unload: str, qty: int = 1) -> str:
    r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                   "unload": unload, "quantity": qty})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _tmpl(a: Actor, name: str, proc: str, station: str) -> str:
    r = a.req("POST", "/lot-templates/", {"name": name, "processId": proc,
                                          "startStationId": station})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _card(a: Actor, tmpl: str, proc: str, station: str, n: int = 1) -> dict:
    r = a.req("POST", "/cards/", {"lotTemplateId": tmpl, "processId": proc,
                                  "totalQuantity": n, "bins": {station: {"count": n}}})
    assert r.status_code == 201, r.text
    return r.json()


def _at(a: Actor, station: str) -> int:
    return sum(c["bins"].get(station, {}).get("count", 0)
               for c in a.req("GET", "/cards/").json())


# ─── A location shared by two processes ──────────────────────────────────────

def _shared_bench(a: Actor):
    """Two independent lines that happen to use one bench.

        Left:  Left In  ─► Bench ─► Ship
        Right: Right In ─► Bench ─► Ship
    """
    left_in, right_in = _st(a, "Left In"), _st(a, "Right In")
    bench, ship = _st(a, "Bench"), _st(a, "Ship")
    out = {}
    for name, source in (("Left", left_in), ("Right", right_in)):
        p = _proc(a, name)
        _route(a, p, source, bench)
        _route(a, p, bench, ship)
        out[name] = {"proc": p, "source": source,
                     "tmpl": _tmpl(a, f"{name} part", p, source)}
    return out, bench, ship


def test_the_bench_is_not_a_merge_station_for_either_line(actor):
    """The merge preview must not offer to assemble at a location that simply
    happens to be busy on two lines — the Operator view trusts this flag."""
    a = actor(); bootstrap_admin(a)
    lines, bench, ship = _shared_bench(a)
    r = a.req("GET", f"/merge/{bench}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["isMergeStation"] is False, body
    assert body["assembliesPossible"] == 0, body


def test_a_merge_never_consumes_the_other_lines_material(actor):
    """The failure this guards: two feeds *in total* looks like a merge to any
    check that forgets which process it is standing in, and the assembly would
    then eat a lot that belongs to a different value stream."""
    a = actor(); bootstrap_admin(a)
    lines, bench, ship = _shared_bench(a)
    # Park material from both lines on the shared bench.
    for L in lines.values():
        c = _card(a, L["tmpl"], L["proc"], L["source"])
        a.req("POST", f"/cards/{c['_id']}/advance",
              {"fromStationId": L["source"], "toStationId": bench, "quantity": 1})
    assert _at(a, bench) == 2

    r = a.req("POST", f"/merge/{bench}")
    assert r.status_code >= 400, f"merged at a location that assembles nothing: {r.text}"
    assert _at(a, bench) == 2, "material was consumed by a merge that should not exist"


# ─── Alternative routing: two ways through the same locations ────────────────

def _fast_and_slow(a: Actor):
    """The documented way to model "either/or": a second process, not a branch.

        Fast: Cut ───────────► Pack
        Slow: Cut ─► Grind ──► Pack
    """
    cut, grind, pack = _st(a, "Cut"), _st(a, "Grind"), _st(a, "Pack")
    fast = _proc(a, "Fast")
    _route(a, fast, cut, pack)
    slow = _proc(a, "Slow")
    _route(a, slow, cut, grind)
    _route(a, slow, grind, pack)
    return {
        "cut": cut, "grind": grind, "pack": pack,
        "fast": {"proc": fast, "tmpl": _tmpl(a, "Fast part", fast, cut)},
        "slow": {"proc": slow, "tmpl": _tmpl(a, "Slow part", slow, cut)},
    }


def test_cut_is_not_a_split_because_two_processes_leave_it(actor):
    """Cut sends work onward in both processes, so it has two outgoing routes in
    total — but one per process. Advancing must move the lot, not fan it out
    into a piece on every line."""
    a = actor(); bootstrap_admin(a)
    g = _fast_and_slow(a)
    c = _card(a, g["fast"]["tmpl"], g["fast"]["proc"], g["cut"])
    r = a.req("POST", f"/cards/{c['_id']}/advance",
              {"fromStationId": g["cut"], "toStationId": g["pack"], "quantity": 1})
    assert r.status_code == 200, r.text
    assert len(a.req("GET", "/cards/").json()) == 1, "a second lot was minted on the other route"
    assert _at(a, g["grind"]) == 0, "material appeared on a route this lot never took"


def test_a_lot_cannot_ride_the_other_processs_route(actor):
    """A fast-line lot has no route to Grind: that route belongs to the slow
    process. Riding it would teleport the lot out of its own value stream."""
    a = actor(); bootstrap_admin(a)
    g = _fast_and_slow(a)
    c = _card(a, g["fast"]["tmpl"], g["fast"]["proc"], g["cut"])
    r = a.req("POST", f"/cards/{c['_id']}/advance",
              {"fromStationId": g["cut"], "toStationId": g["grind"], "quantity": 1})
    assert r.status_code == 400, r.text


def test_pack_receives_from_both_routes_without_becoming_a_merge(actor):
    """Pack has two incoming routes in total and one per process, so neither
    line's lots are held there waiting to be assembled."""
    a = actor(); bootstrap_admin(a)
    g = _fast_and_slow(a)
    fast = _card(a, g["fast"]["tmpl"], g["fast"]["proc"], g["cut"])
    a.req("POST", f"/cards/{fast['_id']}/advance",
          {"fromStationId": g["cut"], "toStationId": g["pack"], "quantity": 1})
    slow = _card(a, g["slow"]["tmpl"], g["slow"]["proc"], g["cut"])
    a.req("POST", f"/cards/{slow['_id']}/advance",
          {"fromStationId": g["cut"], "toStationId": g["grind"], "quantity": 1})
    r = a.req("POST", f"/cards/{slow['_id']}/advance",
              {"fromStationId": g["grind"], "toStationId": g["pack"], "quantity": 1})
    assert r.status_code == 200, r.text
    assert _at(a, g["pack"]) == 2


# ─── Two real merges sharing one physical location ──────────────────────────

def _two_merges_one_bench(a: Actor):
    """Two lines that both assemble, at the same bench.

        Alpha: X ─┐            Beta: P ─┐
                  ├─► Bench             ├─► Bench
               Y ─┘                  Q ─┘
    """
    bench = _st(a, "Bench")
    out = {}
    for name, feeds in (("Alpha", ("X", "Y")), ("Beta", ("P", "Q"))):
        p = _proc(a, name)
        sources = [_st(a, s) for s in feeds]
        for s in sources:
            _route(a, p, s, bench)
        out[name] = {
            "proc": p, "sources": sources,
            "precursors": [_tmpl(a, f"{name}-{label}", p, sid)
                           for label, sid in zip(feeds, sources)],
            "assembly": _tmpl(a, f"{name} assembly", p, bench),
        }
    return out, bench


def test_each_process_merges_only_its_own_precursors(actor):
    """Both lines assemble at one bench. A merge on Alpha must consume Alpha's
    two parts and leave Beta's alone — the sharpest test of scoping there is,
    because every card involved is standing on the same location."""
    a = actor(); bootstrap_admin(a)
    lines, bench = _two_merges_one_bench(a)
    for L in lines.values():
        for tmpl in L["precursors"]:
            _card(a, tmpl, L["proc"], bench)
    assert _at(a, bench) == 4

    r = a.req("POST", f"/merge/{bench}")
    assert r.status_code in (200, 201), r.text

    cards = a.req("GET", "/cards/").json()
    merged_proc = None
    for L_name, L in lines.items():
        remaining = [c for c in cards if c["processId"] == L["proc"]]
        if len(remaining) == 1 and remaining[0]["lotTemplateId"] == L["assembly"]:
            merged_proc = L_name
        else:
            # the untouched line still has exactly its two precursors
            assert len(remaining) == 2, f"{L_name} was disturbed by the other line's merge: {remaining}"
            assert {c["lotTemplateId"] for c in remaining} == set(L["precursors"])
    assert merged_proc is not None, "no line actually assembled"


def test_a_precursor_is_held_only_by_its_own_processs_merge(actor):
    """Alpha's part is a precursor at the bench and cannot leave. Beta's part is
    a precursor of a *different* merge at the same bench — it is held too, but
    by its own line's rule, not by Alpha's."""
    a = actor(); bootstrap_admin(a)
    lines, bench = _two_merges_one_bench(a)
    ship = _st(a, "Ship")
    for L in lines.values():
        _route(a, L["proc"], bench, ship)

    for name, L in lines.items():
        part = _card(a, L["precursors"][0], L["proc"], bench)
        r = a.req("POST", f"/cards/{part['_id']}/advance",
                  {"fromStationId": bench, "toStationId": ship, "quantity": 1})
        assert r.status_code == 409, f"{name}'s precursor escaped: {r.text}"

        made = _card(a, L["assembly"], L["proc"], bench)
        r = a.req("POST", f"/cards/{made['_id']}/advance",
                  {"fromStationId": bench, "toStationId": ship, "quantity": 1})
        assert r.status_code == 200, f"{name}'s finished assembly was held: {r.text}"


def test_a_pull_seeds_only_its_own_lines_queues(actor):
    """Ordering Alpha's assembly must raise demand at X and Y, never at P or Q —
    the queues of a line that has nothing to do with this order."""
    a = actor(); bootstrap_admin(a)
    lines, bench = _two_merges_one_bench(a)
    alpha, beta = lines["Alpha"], lines["Beta"]

    r = a.req("POST", "/orders", {"productTemplateId": alpha["assembly"], "quantity": 1,
                                  "source": "manual", "externalRef": "ALPHA-1"})
    assert r.status_code == 201, r.text

    seeded = {sid for c in a.req("GET", "/cards/").json() for sid in c["bins"]}
    assert seeded == set(alpha["sources"]), seeded
    assert not seeded & set(beta["sources"]), "the other line's queues were seeded"


# ─── Weights are a per-process judgement too ─────────────────────────────────

def test_a_weight_is_refused_where_the_graph_does_not_branch_in_that_process(actor):
    """A weight only means something on a merge feed or a split branch. Cut has
    two outgoing routes overall but one per process, so neither is a branch and
    neither may carry a weight."""
    a = actor(); bootstrap_admin(a)
    g = _fast_and_slow(a)
    routes = a.req("GET", "/routes/").json()
    cut_to_pack = next(r for r in routes
                       if r["load"] == g["cut"] and r["unload"] == g["pack"])
    r = a.req("PUT", f"/routes/{cut_to_pack['_id']}", {"quantity": 4})
    assert r.status_code == 400, f"a weight was accepted on a route that does not branch: {r.text}"
