"""Who is allowed to read the route table raw.

Four separate bugs in this codebase have had one shape: a function asked the
route table a question about the *graph* — how many feeds does this station
have, what leaves it, is this a leaf — and counted edges that touch an
integration node. Those edges are not material flow. Each was found in
production-ish use, fixed on its own, and the next function to be written made
the same mistake, because the rule lived in people's heads.

Two of them are checked here instead:

  * an inventory with a **reason per entry**, so a new raw read fails until
    someone writes down why it is allowed to be raw;
  * a behavioural check that the editor and the engine agree about degree,
    which is the thing the convention exists to protect.

The inventory is deliberately crude. It cannot tell a correct raw read from an
incorrect one — but it can make sure nobody adds one silently, and the reason
column is where the thinking goes.
"""

import ast
import pathlib

import pytest

from tests.helpers import Actor, bootstrap_admin

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}

# module → {function: why it may read the route table without the helper}
ALLOWED = {
    "routers/cards.py": {
        "_split_branches": "excludes boundary links itself",
        "_sink_link": "is ABOUT the boundary link — that is what it looks for",
        "_record_order_progress": "excludes handoff targets itself",
        "_is_forward_move": "direction of one named edge, not degree",
        "_outgoing_routes_for_split": "excludes partner targets itself",
        "advance_card": "looks up one named edge; landing is gated separately",
        "handoff_card": "is ABOUT the boundary link",
    },
    "routers/merge.py": {
        "_incoming_routes": "THE boundary-filtered reader other code should use",
        "_outgoing_count": "the filtered degree helper",
        "_leaf_sources": "filters boundary before walking",
    },
    "routers/routes.py": {
        "_process_edges": "cycle check; excludes boundary links itself",
        "_check_boundary_placement": "is ABOUT the boundary link",
        "_not_a_boundary_link": "IS the filter",
        "_other_incoming_count": "degree — goes through _not_a_boundary_link",
        "_other_outgoing_count": "degree — goes through _not_a_boundary_link",
        "list_routes": "CRUD listing, no graph reasoning",
        "_normalize_weights": "rewrites weights on edges already judged",
        "create_route": "CRUD write path",
    },
    "routers/map_io.py": {"export_map": "serialises the rows as rows"},
    "core/line_snapshot.py": {
        "build": "hands rows to core.analysis, which filters boundary links itself",
    },
    "routers/sessions.py": {
        "_line_cycle_times_by_process": "maps each departure to the process whose route "
                                        "it took; asks no question about the graph's shape",
    },
    "core/flow.py": {
        "by_process": "attributes each lot event to the process whose route it took; "
                      "asks no question about the graph's shape",
    },
    "core/whatif_data.py": {
        "build_model": "builds the what-if model's process graph; drops every edge "
                       "touching an integration node itself (partners filter) "
                       "before any graph question is asked",
    },
    "core/tracking.py": {
        "_ordered_stations": "topologically orders one process's stations for a "
                             "customer-facing progress bar; filters boundary "
                             "links itself (an ERP node is not a step and would "
                             "inflate the denominator)",
    },
    "routers/mcp.py": {
        "_read_line": "serialises the rows as rows for an agent to read; the "
                      "degree it reports goes through merge._boundary_station_ids "
                      "— the same filter _incoming_routes and _outgoing_count are "
                      "built from — and is counted per process",
    },
    "routers/orders.py": {"_resolve_process": "picks a process, not a degree"},
    "routers/stations.py": {"_strip_split_semantics": "clears weights on flip to choice"},
}


def _readers():
    for path in sorted(APP.rglob("*.py")):
        src = path.read_text()
        if "RouteRow" not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if "RouteRow" in seg and "select(" in seg:
                yield path.relative_to(APP).as_posix(), node.name


def test_no_new_function_reads_the_route_table_raw():
    found = set(_readers())
    known = {(m, f) for m, fns in ALLOWED.items() for f in fns}
    new = sorted(found - known)
    assert not new, (
        "These read the route table directly and are not in the inventory:\n  "
        + "\n  ".join(f"{m}::{f}" for m, f in new)
        + "\n\nIf it asks a question about the GRAPH — how many feeds, what leaves,"
          "\nis this a leaf — use merge._incoming_routes / _outgoing_count, which"
          "\nexclude edges touching an integration node. If it genuinely needs the"
          "\nrows, add it to ALLOWED with the reason.")


def test_the_inventory_has_no_stale_entries():
    """A reason for a function that no longer exists is worse than no entry: it
    reads as coverage."""
    found = set(_readers())
    stale = sorted({(m, f) for m, fns in ALLOWED.items() for f in fns} - found)
    assert not stale, f"inventory lists functions that no longer read routes: {stale}"


# ── The behaviour the convention protects ───────────────────────────────────

def _line_with_a_demand_link(a: Actor):
    st = lambda n, **k: a.req("POST", "/stations/", {**STATION, "name": n, **k}).json()["_id"]
    cut, asm = st("Cutting"), st("Assembly")
    erp = st("Odoo", integrationProvider="odoo", integrationRole="source")
    proc = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    feed = a.req("POST", "/routes/", {"processId": proc, "load": cut,
                                      "unload": asm, "quantity": 1})
    assert feed.status_code == 201, feed.text
    a.req("POST", "/lot-templates/", {"name": "Widget", "processId": proc,
                                      "startStationId": asm})
    link = a.req("POST", "/routes/", {"processId": proc, "load": erp,
                                      "unload": asm, "quantity": 1})
    assert link.status_code == 201, link.text
    return asm, feed.json()


def test_a_demand_link_does_not_make_a_station_a_merge(actor):
    """Regression. `_other_incoming_count` counted the ERP's demand link as a
    feed, so a station with ONE real feed passed for a merge and accepted a
    weight on it — while `merge.py`, counting the same station properly, said
    it was not a merge and would never consume three of anything. The map drew
    a ×3 badge describing a rule the engine did not have."""
    a = actor(); bootstrap_admin(a)
    asm, feed = _line_with_a_demand_link(a)

    assert a.req("GET", f"/merge/{asm}").json()["isMergeStation"] is False

    r = a.req("PUT", f"/routes/{feed['_id']}", {**feed, "quantity": 3})
    assert r.status_code == 400, \
        f"a weight was accepted on a station the engine says is not a merge: {r.text}"


def test_a_real_second_feed_still_makes_it_a_merge(actor):
    """The other half: the fix must not have made weights impossible. A merge
    with a demand link pointed at it — the commonest ERP wiring there is — has
    to keep working."""
    a = actor(); bootstrap_admin(a)
    asm, feed = _line_with_a_demand_link(a)
    other = a.req("POST", "/stations/", {**STATION, "name": "Fasteners"}).json()["_id"]
    second = a.req("POST", "/routes/", {"processId": feed["processId"], "load": other,
                                        "unload": asm, "quantity": 1})
    assert second.status_code == 201, second.text

    assert a.req("GET", f"/merge/{asm}").json()["isMergeStation"] is True
    r = a.req("PUT", f"/routes/{feed['_id']}", {**feed, "quantity": 3})
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 3
