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

The seeds are fixed, so a failure replays exactly. When one of these trips,
print the op log it emits and the last op is the repro.
"""

import json
import random
from pathlib import Path

import pytest

from tests.helpers import Actor, bootstrap_admin

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "battery-remanufacturing.json"
STEPS = 220


def _import_line(a: Actor):
    doc = json.loads(EXAMPLE.read_text())
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
    return a.req("GET", "/cards/").json()


def _snapshot(a):
    return sorted(
        (c["_id"], c["lotTemplateId"], c["lotNum"], c["totalQuantity"],
         json.dumps(c["bins"], sort_keys=True), c["status"])
        for c in _cards(a))


def _totals(a):
    out: dict = {}
    for c in _cards(a):
        for b in c["bins"].values():
            out[c["lotTemplateId"]] = out.get(c["lotTemplateId"], 0) + b["count"]
    return out


def _assert_structural(a, integrations, log):
    for c in _cards(a):
        for sid, b in c["bins"].items():
            assert sid not in integrations, \
                f"units on an integration node after: {log[-3:]}"
            assert isinstance(b["count"], int) and b["count"] >= 1, \
                f"bin count {b['count']!r} after: {log[-3:]}"
        assert c["totalQuantity"] >= 1


@pytest.mark.parametrize("seed", [7, 20260730])
def test_random_abuse_never_breaks_the_line(actor, seed):
    a = actor(); bootstrap_admin(a)
    st, tm, pr, integrations, fans = _import_line(a)
    rng = random.Random(seed)
    stations = list(st.values())
    procs = list(pr.values())
    log: list = []

    def do(method, path, body):
        before = _snapshot(a)
        totals_before = _totals(a)
        r = a.req(method, path, body)
        log.append((method, path, json.dumps(body, default=str)[:120], r.status_code))
        if r.status_code >= 400:
            assert _snapshot(a) == before, \
                f"a {r.status_code} half-applied: {log[-1]}"
        else:
            _assert_structural(a, integrations, log)
            # Conservation: a successful plain step between two non-fan
            # stations must not change any product's total.
            if (method == "POST" and ("/advance" in path or "/move" in path)
                    and body.get("fromStationId") not in fans
                    and body.get("toStationId") not in fans):
                assert _totals(a) == totals_before, \
                    f"a plain move changed material totals: {log[-1]}"
        return r

    n_orders = 0
    for step in range(STEPS):
        cards = _cards(a)
        op = rng.random()

        if op < 0.10 or not cards:                       # release an order
            n_orders += 1
            line = rng.choice(["NMC", "LFP"])
            do("POST", "/orders", {"productTemplateId": tm[f"Reman {line}"]["_id"],
                                   "quantity": rng.randint(1, 2),
                                   "source": "manual", "externalRef": f"FZ-{seed}-{n_orders}"})
        elif op < 0.20:                                  # pull somewhere random
            do("POST", f"/merge/{rng.choice(stations)}/pull",
               {"quantity": rng.randint(1, 3),
                **({"processId": rng.choice(procs)} if rng.random() < 0.5 else {})})
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
            target = rng.choice([st["Busbar Clean"], st["Reassembly"], rng.choice(stations)])
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
        else:                                            # handoff attempt
            c = rng.choice(cards)
            frm = rng.choice(list(c["bins"])) if c["bins"] else rng.choice(stations)
            do("POST", f"/cards/{c['_id']}/handoff",
               {"fromStationId": frm, "toStationId": st["ShipStation"],
                "quantity": rng.randint(1, 2)})

    # ── After the storm, the line still works end to end ──
    ref = f"FZ-{seed}-final"
    r = a.req("POST", "/orders", {"productTemplateId": tm["Reman NMC"]["_id"],
                                  "quantity": 1, "source": "manual", "externalRef": ref})
    assert r.status_code == 201, r.text
    pack = next(c for c in _cards(a) if c["lotNum"] == ref
                and c["lotTemplateId"] == tm["NMC used pack"]["_id"])
    adv = lambda cid, f, t, q: a.req("POST", f"/cards/{cid}/advance",
                                     {"fromStationId": f, "toStationId": t, "quantity": q})
    assert adv(pack["_id"], st["Intake"], st["Teardown"], 1).status_code == 200
    assert adv(pack["_id"], st["Teardown"], st["Module Test"], 1).status_code == 200
    mods = next(c for c in _cards(a) if c["lotNum"] == ref
                and c["lotTemplateId"] == tm["NMC module"]["_id"])
    dirty = next(c for c in _cards(a) if c["lotNum"] == ref
                 and c["lotTemplateId"] == tm["NMC dirty busbar"]["_id"])
    sol = next(c for c in _cards(a) if c["lotNum"] == ref
               and c["lotTemplateId"] == tm["Cleaning solution (NMC)"]["_id"])
    assert dirty["bins"][st["Busbar Clean"]]["count"] == 2
    assert adv(sol["_id"], st["Cleaning solution"], st["Busbar Clean"],
               sol["bins"][st["Cleaning solution"]]["count"]).status_code == 200
    m = a.req("POST", f"/merge/{st['Busbar Clean']}",
              {"cardIds": [dirty["_id"], sol["_id"]]})
    assert m.status_code == 201, m.text
    cleaned = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
    assert adv(mods["_id"], st["Module Test"], st["Reassembly"], 3).status_code == 200
    assert adv(cleaned["_id"], st["Busbar Clean"], st["Reassembly"],
               cleaned["bins"][st["Busbar Clean"]]["count"]).status_code == 200
    m = a.req("POST", f"/merge/{st['Reassembly']}",
              {"cardIds": [mods["_id"], cleaned["_id"]]})
    assert m.status_code == 201, m.text
    made = a.req("GET", f"/cards/{m.json()['createdCardId']}").json()
    assert made["lotTemplateId"] == tm["Reman NMC"]["_id"]
