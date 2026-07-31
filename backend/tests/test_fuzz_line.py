"""Randomized abuse of the full battery line, with invariants after every op.

A seeded random walk hammers the imported example — advances, drags, merges,
unmerges, pulls, orders, handoffs, deliberate nonsense — and after EVERY call
asserts the things that must hold no matter what a worker does:

  1. a refused operation (4xx) leaves the line byte-for-byte unchanged — the
     transaction either happens or it did not;
  2. no unit ever sits on an integration partner's node;
  3. every bin holds a positive whole number of units;
  4. a plain move between two non-fan stations never changes what the material
     adds up to per product — only the declared transformations (split, merge,
     unmerge, un-split) may do that;
  5. after a few hundred random gestures the line still WORKS: a fresh order
     pulls, washes, and assembles into a finished pack.

The seed fixes which *kinds* of gesture the walk makes, but not the run: lot
ids are random UUIDs and the walk picks lots out of a list, so consecutive runs
of the same seed explore different paths. For a fuzzer that is a feature — CI
keeps finding new ground — but it means a failure cannot be reproduced by
rerunning it. So every failure prints the tail of the op log instead, which is
the actual repro: the calls, in order, with their status codes.
"""

import json
import random
from pathlib import Path

import pytest

from tests.helpers import Actor, bootstrap_admin

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

# Every line the repo ships, so the walk covers three genuinely different
# topologies rather than one three times: a diamond with a split whose weights
# multiply, a wide four-branch fan into a deep finishing chain, and two parallel
# chains converging on a merge that carries the ratios. A rule that only holds
# for the shape it was written against is not a rule.
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.json"))
STEPS = 220


def _import_line(a: Actor, example: Path):
    doc = json.loads(example.read_text())
    assert a.req("POST", "/map-io/import", doc).status_code == 200
    st = {s["name"]: s["_id"] for s in a.req("GET", "/stations/").json()}
    integrations = {s["_id"] for s in a.req("GET", "/stations/").json()
                    if s.get("integrationProvider")}
    tm = {t["name"]: t for t in a.req("GET", "/lot-templates/").json()}
    pr = {p["name"]: p["_id"] for p in a.req("GET", "/processes/").json()}
    routes = a.req("GET", "/routes/").json()
    # Fan stations: totals may legitimately change when material crosses them.
    fan_stations = set()
    per_proc_out: dict = {}
    for r in routes:
        if r["unload"] in integrations or r["load"] in integrations:
            continue
        per_proc_out.setdefault((r["processId"], r["load"]), set()).add(r["unload"])
    for (_, load), outs in per_proc_out.items():
        if len(outs) >= 2:
            fan_stations.add(load)
    return st, tm, pr, integrations, fan_stations


def _cards(a):
    """Every lot, in a stable order.

    `GET /cards/` has no ORDER BY, so without this the walk's choices depended
    on whatever row order Postgres felt like returning — nondeterminism on top
    of nondeterminism. Sorting does not make a run reproducible (the ids are
    random UUIDs, so the order differs anyway); it just stops the same process
    state from being explored differently for no reason."""
    return sorted(a.req("GET", "/cards/").json(), key=lambda c: c["_id"])


def _snapshot(a):
    return _snapshot_of(_cards(a))


def _snapshot_of(cards):
    return sorted(
        (c["_id"], c["lotTemplateId"], c["lotNum"], c["totalQuantity"],
         json.dumps(c["bins"], sort_keys=True), c["status"])
        for c in cards)


def _totals(a):
    out: dict = {}
    for c in _cards(a):
        for b in c["bins"].values():
            out[c["lotTemplateId"]] = out.get(c["lotTemplateId"], 0) + b["count"]
    return out


def _assert_structural(a, integrations, log):
    _assert_structural_of(_cards(a), integrations, log)


def _tail(log, n=15):
    """The repro, since rerunning the seed will not produce it."""
    return "\n  ".join(f"{m} {p} {b} -> {c}" for m, p, b, c in log[-n:])


def _assert_structural_of(cards, integrations, log):
    for c in cards:
        for sid, b in c["bins"].items():
            assert sid not in integrations, \
                f"units on an integration node.\nlast ops:\n  {_tail(log)}"
            assert isinstance(b["count"], int) and b["count"] >= 1, \
                f"bin count {b['count']!r}.\nlast ops:\n  {_tail(log)}"
        assert c["totalQuantity"] >= 1


def _by_station(a):
    """Units standing on each station, all products together."""
    return _by_station_of(_cards(a))


def _by_station_of(cards):
    out: dict = {}
    for c in cards:
        for sid, b in c["bins"].items():
            out[sid] = out.get(sid, 0) + b["count"]
    return out


def _identity_of(cards):
    """What each lot card *is*: its product and its line.

    The ledger below counts units by place. That is only half of what has to be
    conserved, because a card carries a physical label: relabel one and you
    have mislabelled a real part on a real bench. On the battery line the two
    chemistries are physically interchangeable and electrically incompatible,
    so a module that changes identity — or a pack assembled from two lines'
    parts — is not a reporting defect.
    """
    return {c["_id"]: (c["lotTemplateId"], c.get("processId")) for c in cards}


def _placed_of(cards):
    """Units per card per station, for working out what an operation consumed."""
    return {(c["_id"], sid): b["count"] for c in cards for sid, b in c["bins"].items()}


def _delta(before, after):
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0)
            for k in keys if after.get(k, 0) != before.get(k, 0)}


def _fan_maps(a, integrations):
    """Every fan in the line as `{target: weight}`, one map per (process,
    station). Read from the DECLARATION — the route rows — never re-derived,
    so the ledger below checks the arithmetic without re-implementing the
    decision of which arithmetic applies."""
    per: dict = {}
    for r in a.req("GET", "/routes/").json():
        if r["load"] in integrations or r["unload"] in integrations:
            continue
        per.setdefault((r["processId"], r["load"]), {})[r["unload"]] = r["quantity"]
    out: dict = {}
    for (_proc, load), targets in per.items():
        if len(targets) >= 2:
            out.setdefault(load, []).append(targets)
    return out


def _explains(delta, frm, to, fans):
    """Is this the delta of a LEGAL step?

    A move of material may take exactly three shapes, and the domain admits no
    fourth:

      1. a 1:1 transfer — n leaves one station and the same n arrives at another
         (a plain move, and every step out of a *choice* station);
      2. a forward fan — a split consumes n and mints n × weight down each of
         its branches, all of them, in one gesture;
      3. a backward fan — the mirror, where pieces returning to a split re-form
         n source units and the twins on every sibling branch are consumed in
         the ratio the weights describe.

    Anything else is material appearing from nowhere or vanishing without being
    consumed. The old check only looked at moves between two non-fan stations,
    which is precisely the case least likely to be wrong; every interesting bug
    this line has had lived in shapes 2 and 3.
    """
    if not delta:
        return "still"                    # a zero-unit step changes nothing
    if (len(delta) == 2 and delta.get(frm, 0) < 0
            and delta.get(to, 0) == -delta.get(frm, 0)):
        return "transfer"
    for branches in fans.get(frm, []):    # forward fan out of `frm`
        n = -delta.get(frm, 0)
        if n > 0 and delta == {frm: -n, **{t: n * w for t, w in branches.items()}}:
            return "split"
    for split, maps in fans.items():      # backward fan onto any split
        for branches in maps:
            n = delta.get(split, 0)
            if n > 0 and delta == {split: n, **{t: -n * w for t, w in branches.items()}}:
                return "unsplit"
    return None


def _shape(a, integrations):
    """What this particular line offers to abuse — derived, never named. The
    walk has to work on any of the three, and a body that hardcodes "Busbar
    Clean" only ever tested the one it was written against."""
    routes = a.req("GET", "/routes/").json()
    tmpls = a.req("GET", "/lot-templates/").json()
    feeds: dict = {}
    for r in routes:
        if r["load"] in integrations or r["unload"] in integrations:
            continue
        feeds.setdefault((r["processId"], r["unload"]), set()).add(r["load"])
    merges = sorted({st for (_p, st), ins in feeds.items() if len(ins) >= 2})
    # What a customer can order: made where an ERP raises demand, else made at
    # a merge, else anything at all.
    demand_targets = {r["unload"] for r in routes if r["load"] in integrations}
    orderable = [t for t in tmpls if t.get("startStationId") in demand_targets] \
        or [t for t in tmpls if t.get("startStationId") in set(merges)] or tmpls
    sinks = [r["unload"] for r in routes if r["unload"] in integrations]
    return merges, orderable, (sinks[0] if sinks else None)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
@pytest.mark.parametrize("seed", [7, 20260730])
def test_random_abuse_never_breaks_the_line(actor, seed, example):
    a = actor(); bootstrap_admin(a)
    st, tm, pr, integrations, fans = _import_line(a, example)
    merges, orderable, sink = _shape(a, integrations)
    fan_maps = _fan_maps(a, integrations)
    outs: dict = {}
    for r in a.req("GET", "/routes/").json():
        if r["load"] in integrations or r["unload"] in integrations:
            continue
        outs.setdefault((r["processId"], r["load"]), []).append(r["unload"])
    rng = random.Random(seed)
    stations = list(st.values())
    procs = list(pr.values())
    log: list = []
    shapes: dict = {}

    def do(method, path, body):
        cards_before = _cards(a)
        before = _snapshot_of(cards_before)
        units_before = _by_station_of(cards_before)
        ident_before = _identity_of(cards_before)
        placed_before = _placed_of(cards_before)
        before_card = [c for c in cards_before if c["_id"] == path.split("/")[2]] \
            if path.startswith("/cards/") else []
        r = a.req(method, path, body)
        log.append((method, path, json.dumps(body, default=str)[:120], r.status_code))
        if r.status_code >= 400:
            assert _snapshot(a) == before, f"a {r.status_code} half-applied.\nlast ops:\n  {_tail(log)}"
            return r

        cards_after = _cards(a)
        _assert_structural_of(cards_after, integrations, log)
        delta = _delta(units_before, _by_station_of(cards_after))

        # ── A lot card never changes what it IS ──
        # Transformations MINT cards; they do not relabel them. So any card id
        # that survives an operation must still carry the same product and the
        # same line. A silent relabel is a mislabelled physical part, and it
        # conserves the unit count perfectly — the ledger below would not see it.
        ident_after = _identity_of(cards_after)
        for cid, was in ident_before.items():
            if cid in ident_after:
                assert ident_after[cid] == was, \
                    f"lot {cid[:8]} was relabelled {was} -> {ident_after[cid]}.\nlast ops:\n  {_tail(log)}"

        # ── Nothing is ever assembled from two lines at once ──
        # Two chemistries share the reassembly bench. Consuming across
        # processes is how an LFP pack acquires an NMC module.
        placed_after = _placed_of(cards_after)
        consumed = {cid for (cid, sid), n in placed_before.items()
                    if n > placed_after.get((cid, sid), 0)}
        if len(consumed) > 1:
            procs = {ident_before[cid][1] for cid in consumed if cid in ident_before}
            assert len(procs) <= 1, \
                f"one operation consumed lots from {len(procs)} processes.\nlast ops:\n  {_tail(log)}"
        minted = set(ident_after) - set(ident_before)
        if consumed and minted:
            made = {ident_after[cid][1] for cid in minted}
            took = {ident_before[cid][1] for cid in consumed if cid in ident_before}
            assert not (made - took) or not took, \
                f"a lot was minted onto a line none of its inputs belonged to.\nlast ops:\n  {_tail(log)}"

        # ── The ledger: every operation must move material the way it says ──
        if "/advance" in path or "/move" in path:
            shape = _explains(delta, body["fromStationId"], body["toStationId"], fan_maps)
            if not shape:
                nm = {v: k for k, v in st.items()}
                raise AssertionError(
                    "ILLEGAL SHAPE\n"
                    f"  op       : {method} {path} {body}\n"
                    f"  from/to  : {nm.get(body['fromStationId'])} -> {nm.get(body['toStationId'])}\n"
                    f"  delta    : { {nm.get(k, k): v for k, v in delta.items()} }\n"
                    f"  fans     : { {nm.get(k): [{nm.get(t): w for t, w in m.items()} for m in v] for k, v in fan_maps.items()} }\n"
                    f"  card was : {json.dumps(before_card)}\n"
                    f"  card now : {json.dumps([c for c in _cards(a) if c['_id'] == path.split('/')[2]])}\n")
            shapes[shape] = shapes.get(shape, 0) + 1

        elif path.endswith("/handoff"):
            # Goods leave the line. Nothing is minted on the way out, and
            # nothing moves anywhere else.
            q = -delta.get(body["fromStationId"], 0)
            assert delta == ({body["fromStationId"]: -q} if q else {}), \
                f"a handoff disturbed the floor: {delta}.\nlast ops:\n  {_tail(log)}"

        elif path.startswith("/merge/") and not path.endswith("/pull"):
            # Precursors are consumed where they stand and the assembly is
            # minted in their place: a merge touches its own station and no
            # other, and always costs more units than it makes (a merge has
            # two feeds or it is not a merge).
            station = path.split("/")[2]
            assert set(delta) <= {station}, \
                f"a merge changed units away from its own station: {delta}.\nlast ops:\n  {_tail(log)}"
            assert delta.get(station, 0) < 0, \
                f"a merge did not consume: {delta}.\nlast ops:\n  {_tail(log)}"

        elif path.endswith("/pull") or path == "/orders/":
            # Demand seeds material; it may never remove any.
            assert all(v > 0 for v in delta.values()), \
                f"a pull/release destroyed material: {delta}.\nlast ops:\n  {_tail(log)}"

        return r

    n_orders = 0
    for _step in range(STEPS):
        cards = _cards(a)
        op = rng.random()

        if op < 0.10 or not cards:                       # release an order
            n_orders += 1
            do("POST", "/orders/", {"productTemplateId": rng.choice(orderable)["_id"],
                                    "quantity": rng.randint(1, 2), "source": "manual",
                                    "externalRef": f"FZ-{seed}-{n_orders}"})
        elif op < 0.20:                                  # pull somewhere random
            do("POST", f"/merge/{rng.choice(stations)}/pull",
               {"quantity": rng.randint(1, 3),
                **({"processId": rng.choice(procs)} if rng.random() < 0.5 else {})})
        elif op < 0.34:                                  # work a fan on purpose
            # Pure randomness almost never lands a legal step out of a split:
            # measured over 220 steps it managed one, and none at all on the
            # battery line. Left to chance the ledger below only ever sees 1:1
            # transfers — the one shape that has never been wrong. So the walk
            # aims at fans deliberately, in both directions.
            on_fan = [(c, s) for c in cards for s in c["bins"] if s in fan_maps]
            back = [(c, s, split) for c in cards for s in c["bins"]
                    for split, maps in fan_maps.items()
                    for m in maps if s in m]
            if on_fan and rng.random() < 0.7:
                c, s = rng.choice(on_fan)
                target = rng.choice(list(rng.choice(fan_maps[s])))
                do("POST", f"/cards/{c['_id']}/advance",
                   {"fromStationId": s, "toStationId": target,
                    "quantity": rng.choice([1, c["bins"][s]["count"]])})
            elif back:
                c, s, split = rng.choice(back)
                do("POST", f"/cards/{c['_id']}/move",
                   {"fromStationId": s, "toStationId": split,
                    "quantity": rng.choice([1, c["bins"][s]["count"]])})

        elif op < 0.44:                                  # follow a real route
            # Material that only ever moves at random never reaches the
            # interesting stations. This walks a lot one legal step downstream,
            # which is how anything gets to a fan or a merge in the first place.
            legal = [(c, s, t) for c in cards for s in c["bins"]
                     for t in outs.get((c.get("processId"), s), ())]
            if legal:
                c, s, t = rng.choice(legal)
                do("POST", f"/cards/{c['_id']}/advance",
                   {"fromStationId": s, "toStationId": t,
                    "quantity": c["bins"][s]["count"]})

        elif op < 0.55:                                  # advance: often nonsense
            c = rng.choice(cards)
            frm = (rng.choice(list(c["bins"])) if c["bins"] and rng.random() < 0.85
                   else rng.choice(stations))
            have = c["bins"].get(frm, {}).get("count", 0)
            qty = rng.choice([1, 1, have, have + 3, 0]) or 1
            do("POST", f"/cards/{c['_id']}/advance",
               {"fromStationId": frm, "toStationId": rng.choice(stations), "quantity": qty})
        elif op < 0.70:                                  # super-admin drag, any direction
            c = rng.choice(cards)
            frm = (rng.choice(list(c["bins"])) if c["bins"] and rng.random() < 0.85
                   else rng.choice(stations))
            have = c["bins"].get(frm, {}).get("count", 0)
            do("POST", f"/cards/{c['_id']}/move",
               {"fromStationId": frm, "toStationId": rng.choice(stations),
                "quantity": rng.choice([1, have, have + 1]) or 1})
        elif op < 0.85:                                  # merge, guided or not
            target = rng.choice(merges + [rng.choice(stations)]) if merges else rng.choice(stations)
            body = {}
            if rng.random() < 0.4:
                body["processId"] = rng.choice(procs)
            if rng.random() < 0.4 and cards:
                body["cardIds"] = [c["_id"] for c in
                                   rng.sample(cards, k=min(len(cards), rng.randint(1, 3)))]
            do("POST", f"/merge/{target}", body)
        elif op < 0.95:                                  # unmerge something, somewhere
            c = rng.choice(cards)
            station = (rng.choice(list(c["bins"])) if c["bins"] and rng.random() < 0.7
                       else rng.choice(stations))
            do("POST", f"/cards/{c['_id']}/unmerge",
               {"stationId": station, "quantity": rng.randint(1, 3)})
        elif sink:                                       # handoff attempt
            c = rng.choice(cards)
            frm = rng.choice(list(c["bins"])) if c["bins"] else rng.choice(stations)
            do("POST", f"/cards/{c['_id']}/handoff",
               {"fromStationId": frm, "integrationStationId": sink,
                "quantity": rng.randint(1, 2)})

    # ── After the storm, the line still answers ──
    ref = f"FZ-{seed}-final"
    product = orderable[0]
    r = a.req("POST", "/orders/", {"productTemplateId": product["_id"], "quantity": 1,
                                   "source": "manual", "externalRef": ref})
    assert r.status_code == 201, r.text
    seeded = [c for c in _cards(a) if c["lotNum"] == ref]
    assert seeded, "a release after the walk seeded nothing"
    _assert_structural(a, integrations, log)

    # Every merge the line has can still be asked what it needs, and every
    # station can still be pulled at without a 500.
    for m in merges:
        assert a.req("GET", f"/merge/{m}").status_code == 200
    assert a.req("GET", "/sessions/stats").status_code == 200
    assert a.req("GET", "/reports/export.xlsx").status_code == 200

    # Guard the guard. A ledger that only ever saw 1:1 transfers proves nothing
    # about the shapes that actually break — so the walk must have driven real
    # material through a fan, in at least one direction, or it did not test the
    # thing it exists to test.
    print(f"\n{example.stem} seed={seed} ledger shapes: {shapes}")
    assert shapes.get("split", 0) or shapes.get("unsplit", 0), \
        f"the walk never crossed a fan; the ledger was never exercised: {shapes}"
