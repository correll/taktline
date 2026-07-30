#!/usr/bin/env python3
"""Run the line from N simulated tablets, live, against a running server.

This is not a test harness: it drives the **public HTTP API** exactly as the
Operator view does — log in, pick a station, start a work session, wait out the
cycle, stop, then advance / merge / hand off. Every card movement therefore
broadcasts on the websocket, so an open browser shows the lots moving in real
time, and the sessions it records feed the real cycle-time, line-cycle-time and
OEE statistics.

    # zero-config: fresh company, the shipped battery line, 8 tablets, 1 hour
    .venv/bin/python simulate_line.py

    # drive your own company (imports nothing, uses the line already there)
    .venv/bin/python simulate_line.py --email you@example.com --company "My line"

Each tablet is an independent worker with its own operator id, so they race
each other for the same lots exactly as real tablets do. A losing race returns
4xx and the tablet simply tries again next tick — which is the point: a
simulation that serialised the workers would prove nothing about the line.

What a tablet does, in priority order, at its own station:
  1. if a merge is possible here, work a cycle and merge (the proposal);
  2. if lots are waiting, work a cycle and move them on —
     - a split fans out on one advance,
     - a choice deals units by what the downstream merge actually needs
       (surplus to the storage branch: the line's own relief valve),
     - a plain station advances everything;
  3. if this is where goods leave, hand them to the shipper;
  4. otherwise idle briefly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "battery-remanufacturing.json"


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Api:
    """One authenticated session, shared by every tablet (they are all the same
    human's browser as far as the server is concerned — the operator id on each
    work session is what distinguishes them)."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base, timeout=30.0,
                                        follow_redirects=True)
        self.company_id: str | None = None

    async def close(self):
        await self.client.aclose()

    def _headers(self) -> dict:
        h = {}
        csrf = self.client.cookies.get("taktline_csrf")
        if csrf:
            h["X-CSRF-Token"] = csrf
        if self.company_id:
            h["X-Company-Id"] = self.company_id
        return h

    async def req(self, method: str, path: str, body=None) -> httpx.Response:
        return await self.client.request(method, path, json=body, headers=self._headers())

    async def get(self, path: str):
        r = await self.req("GET", path)
        r.raise_for_status()
        return r.json()


# ── Setup ─────────────────────────────────────────────────────────────────────

async def authenticate(api: Api, args) -> str:
    """Return a human-readable description of what we are driving."""
    if args.email:
        password = args.password or os.environ.get("TAKTLINE_SIM_PASSWORD")
        if not password:
            sys.exit("--email needs --password (or $TAKTLINE_SIM_PASSWORD)")
        r = await api.req("POST", "/auth/login", {"email": args.email, "password": password})
        if r.status_code != 200:
            sys.exit(f"login failed: {r.status_code} {r.text}")
        me = r.json()
        companies = me.get("companies", [])
        if args.company:
            match = [c for c in companies if c["name"].lower() == args.company.lower()]
            if not match:
                names = ", ".join(repr(c["name"]) for c in companies) or "none"
                sys.exit(f"no company named {args.company!r} — you belong to: {names}")
            chosen = match[0]
        elif len(companies) == 1:
            chosen = companies[0]
        else:
            names = ", ".join(repr(c["name"]) for c in companies)
            sys.exit(f"several companies — pick one with --company: {names}")
        api.company_id = chosen["companyId"] if "companyId" in chosen else chosen["id"]
        return f"{chosen['name']} (signed in as {args.email})"

    # Zero-config: a throwaway dev company nobody else is using.
    r = await api.req("POST", "/auth/dev/bootstrap",
                      {"email": "demo-admin@taktline.dev", "password": "demo-password-123",
                       "companyName": args.new_company})
    if r.status_code != 200:
        sys.exit("dev bootstrap unavailable — start the backend with TAKTLINE_DEV=1, "
                 "or pass --email/--password to drive your own company.\n"
                 f"  server said: {r.status_code} {r.text}")
    api.company_id = r.json()["companyId"]
    return (f"{args.new_company} — a fresh company ({api.company_id}).\n"
            f"    To watch it: sign in at http://localhost:3000 as "
            f"demo-admin@taktline.dev / demo-password-123\n"
            f"    and pick {args.new_company!r} in the company switcher.")


async def import_example(api: Api) -> None:
    doc = json.loads(EXAMPLE.read_text())
    r = await api.req("POST", "/map-io/import", doc)
    if r.status_code != 200:
        sys.exit(f"could not import the example line: {r.status_code} {r.text}")


# ── The line, as the tablets understand it ────────────────────────────────────

class Line:
    def __init__(self, stations, routes, processes, templates):
        self.stations = {s["_id"]: s for s in stations}
        self.processes = {p["_id"]: p for p in processes}
        self.templates = {t["_id"]: t for t in templates}
        self.partners = {s["_id"] for s in stations if s.get("integrationProvider")}
        self.flow = [r for r in routes
                     if r["load"] not in self.partners and r["unload"] not in self.partners]
        self.sinks = {r["load"]: r["unload"] for r in routes
                      if r["unload"] in self.partners
                      and self.stations[r["unload"]].get("integrationRole") in ("sink", "both")}
        self.out: dict[str, list] = {}
        self.inn: dict[str, list] = {}
        for r in self.flow:
            self.out.setdefault(r["load"], []).append(r)
            self.inn.setdefault(r["unload"], []).append(r)

    def name(self, sid: str) -> str:
        return self.stations.get(sid, {}).get("name", "?")

    def out_in_process(self, sid: str, pid: str) -> list:
        return [r for r in self.out.get(sid, []) if r["processId"] == pid]

    def is_merge(self, sid: str) -> bool:
        per_proc: dict = {}
        for r in self.inn.get(sid, []):
            per_proc.setdefault(r["processId"], set()).add(r["load"])
        return any(len(v) >= 2 for v in per_proc.values())

    def is_choice(self, sid: str) -> bool:
        return self.stations.get(sid, {}).get("branchMode") == "choice"

    def is_fan(self, sid: str) -> bool:
        """Two or more outgoing routes *within one process* — the same scoping
        the server uses. Counting across processes calls every shared queue a
        split."""
        per_proc: dict = {}
        for r in self.out.get(sid, []):
            per_proc.setdefault(r["processId"], set()).add(r["unload"])
        return any(len(v) >= 2 for v in per_proc.values())

    def is_storage(self, sid: str) -> bool:
        return bool(self.stations.get(sid, {}).get("isStorage"))

    def work_stations(self) -> list[str]:
        """Stations a person can stand at: real work, in topological-ish order
        (sources first) so tablet numbering reads along the flow."""
        ids = [s for s in self.stations
               if s not in self.partners and not self.is_storage(s)
               and (self.out.get(s) or self.inn.get(s) or s in self.sinks)]
        depth: dict[str, int] = {}

        def d(sid, seen=frozenset()):
            if sid in depth:
                return depth[sid]
            if sid in seen:
                return 0
            ups = [r["load"] for r in self.inn.get(sid, [])]
            depth[sid] = 0 if not ups else 1 + max(d(u, seen | {sid}) for u in ups)
            return depth[sid]

        for s in ids:
            d(s)
        return sorted(ids, key=lambda s: (depth.get(s, 0), self.name(s)))

    def throughput_rank(self, sid: str) -> int:
        """Roughly how many units pass through per pack — used to decide where
        the spare tablets go."""
        return sum(max(1, r["quantity"]) for r in self.inn.get(sid, [])) or 1


# ── Tablets ───────────────────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.orders = 0
        self.sessions = 0
        self.moves = 0
        self.merges = 0
        self.handoffs = 0
        self.refused = 0
        self.errors: dict[str, int] = {}

    def refuse(self, what: str):
        self.refused += 1
        self.errors[what] = self.errors.get(what, 0) + 1


async def tablet(idx: int, station_id: str, api: Api, line: Line, stats: Stats,
                 cycle: float, stop_at: float, mistakes: float, verbose: bool):
    """One worker at one station, for the duration of the shift."""
    operator = f"tablet-{idx:02d}"
    name = line.name(station_id)
    rng = random.Random(1000 + idx)

    def say(msg: str):
        if verbose:
            print(f"  [{operator} @ {name}] {msg}", flush=True)

    async def work_a_cycle(card_id: str | None, quantity: int):
        """A real work session: start, spend the cycle, stop. This is what makes
        the statistics in the app mean something."""
        r = await api.req("POST", "/sessions/", {"stationId": station_id, "cardId": card_id,
                                                 "operatorId": operator, "quantity": quantity})
        sid = r.json()["_id"] if r.status_code == 201 else None
        await asyncio.sleep(cycle * rng.uniform(0.8, 1.2))
        if sid:
            await api.req("POST", f"/sessions/{sid}/end", {"quantity": quantity})
            stats.sessions += 1

    while time.monotonic() < stop_at:
        try:
            # ── 1. Can we assemble here? ──
            if line.is_merge(station_id):
                pv = await api.get(f"/merge/{station_id}")
                if pv.get("assembliesPossible", 0) >= 1:
                    picks = [cid for req in pv["requirements"] for cid in req["proposedCardIds"]]
                    await work_a_cycle(picks[0] if picks else None, pv["assembliesPossible"])
                    r = await api.req("POST", f"/merge/{station_id}",
                                      {"cardIds": picks, "processId": pv["processId"]})
                    if r.status_code == 201:
                        stats.merges += 1
                        say(f"merged {r.json()['assemblies']}× "
                            f"{pv.get('assemblyTemplateName') or 'assembly'}")
                    else:
                        stats.refuse(f"merge {r.status_code}")
                    continue

            # ── 2. Anything waiting to move on? ──
            cards = await api.get("/cards/")
            here = [c for c in cards if c["bins"].get(station_id, {}).get("count", 0) > 0]
            if line.is_merge(station_id):
                # Only what this station MAKES may leave it. The parts waiting
                # to be consumed are not movable work — pushing one onward is
                # the mistake /advance answers with 409, and a tablet that kept
                # trying would spin on it forever.
                here = [c for c in here
                        if line.templates.get(c["lotTemplateId"], {}).get("startStationId")
                        == station_id]
            if not here:
                await asyncio.sleep(rng.uniform(0.5, 1.5))
                continue
            card = min(here, key=lambda c: c["createdAt"])
            units = card["bins"][station_id]["count"]
            pid = card["processId"]
            branches = line.out_in_process(station_id, pid)

            if branches:
                await work_a_cycle(card["_id"], units)
                if line.is_choice(station_id) and len(branches) > 1:
                    # Deal by what the downstream actually needs; the rest goes
                    # to the shelf — the relief valve this line is drawn with.
                    plan: list[tuple[str, int]] = []
                    left = units
                    for r_ in sorted(branches, key=lambda b: line.is_storage(b["unload"])):
                        target = r_["unload"]
                        if left <= 0:
                            break
                        if line.is_storage(target):
                            want = left
                        else:
                            want = left
                            try:
                                pv = await api.get(f"/merge/{target}?processId={pid}")
                                need = next((q["requiredPerAssembly"] for q in pv["requirements"]
                                             if q["sourceStationId"] == station_id), left)
                                want = min(left, need)
                            except Exception:
                                pass
                        if want > 0:
                            plan.append((target, want))
                            left -= want
                    for target, qty in plan:
                        r = await api.req("POST", f"/cards/{card['_id']}/advance",
                                          {"fromStationId": station_id, "toStationId": target,
                                           "quantity": qty})
                        if r.status_code == 200:
                            stats.moves += 1
                            say(f"{qty} → {line.name(target)}")
                        else:
                            stats.refuse(f"advance {r.status_code}")
                else:
                    # A split fans out on a single advance; a plain station just
                    # moves. Sometimes a worker only carries part of the lot.
                    qty = units
                    if rng.random() < mistakes and units > 1:
                        qty = rng.randint(1, units - 1)
                    target = rng.choice(branches)["unload"]
                    r = await api.req("POST", f"/cards/{card['_id']}/advance",
                                      {"fromStationId": station_id, "toStationId": target,
                                       "quantity": qty})
                    if r.status_code == 200:
                        stats.moves += 1
                        say(f"{qty} → {line.name(target)}")
                    else:
                        stats.refuse(f"advance {r.status_code}")
                continue

            # ── 3. Is this where the goods leave? ──
            if station_id in line.sinks:
                await work_a_cycle(card["_id"], units)
                r = await api.req("POST", f"/cards/{card['_id']}/handoff",
                                  {"fromStationId": station_id,
                                   "integrationStationId": line.sinks[station_id],
                                   "quantity": units})
                if r.status_code == 200:
                    stats.handoffs += 1
                    say(f"shipped {units} via {line.name(line.sinks[station_id])}")
                else:
                    stats.refuse(f"handoff {r.status_code}")
                continue

            await asyncio.sleep(rng.uniform(0.5, 1.5))

        except httpx.HTTPError as e:
            stats.refuse(type(e).__name__)
            await asyncio.sleep(1.0)


async def releaser(api: Api, line: Line, stats: Stats, interval: float, stop_at: float,
                   verbose: bool):
    """Customer demand: one order a minute, alternating between the products
    that are actually made at the end of each process."""
    finished = []
    for t in line.templates.values():
        sid = t.get("startStationId")
        if not sid or sid not in line.stations:
            continue
        pid = t.get("processId")
        # A finished good: made at a station this process sends nowhere else.
        if pid and not line.out_in_process(sid, pid):
            finished.append(t)
    if not finished:
        # Fall back to whatever a merge station makes.
        finished = [t for t in line.templates.values()
                    if t.get("startStationId") and line.is_merge(t["startStationId"])]
    finished.sort(key=lambda t: t["name"])
    if not finished:
        print("!! no finished product found — nothing to order", flush=True)
        return

    n = 0
    while time.monotonic() < stop_at:
        tmpl = finished[n % len(finished)]
        n += 1
        ref = f"SIM-{n:04d}"
        r = await api.req("POST", "/orders/", {"productTemplateId": tmpl["_id"], "quantity": 1,
                                              "source": "manual", "externalRef": ref,
                                              "lotCode": ref})
        if r.status_code in (200, 201):
            stats.orders += 1
            if verbose:
                print(f"  [orders] released {ref} — {tmpl['name']}", flush=True)
        else:
            stats.refuse(f"order {r.status_code}")
        await asyncio.sleep(interval)


async def reporter(api: Api, line: Line, stats: Stats, stop_at: float, started: float,
                   every: float):
    while time.monotonic() < stop_at:
        await asyncio.sleep(every)
        try:
            cards = await api.get("/cards/")
        except Exception:
            continue
        wip: dict[str, int] = {}
        for c in cards:
            for sid, b in c["bins"].items():
                wip[sid] = wip.get(sid, 0) + b["count"]
        busy = sorted(wip.items(), key=lambda kv: -kv[1])[:5]
        mins = (time.monotonic() - started) / 60
        print(f"[{mins:5.1f} min] orders {stats.orders:3d} · merges {stats.merges:3d} · "
              f"moves {stats.moves:4d} · shipped {stats.handoffs:3d} · "
              f"sessions {stats.sessions:4d} · refused {stats.refused:3d}   WIP: "
              + ", ".join(f"{line.name(s)} {n}" for s, n in busy), flush=True)


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--tablets", type=int, default=8)
    p.add_argument("--cycle", type=float, default=5.0, help="seconds of work per lot")
    p.add_argument("--minutes", type=float, default=60.0)
    p.add_argument("--order-interval", type=float, default=60.0)
    p.add_argument("--mistakes", type=float, default=0.15,
                   help="chance a worker carries only part of a lot")
    p.add_argument("--email", help="drive an existing company as this user")
    p.add_argument("--password")
    p.add_argument("--company", help="which of your companies to drive")
    p.add_argument("--new-company", default="Line Simulation")
    p.add_argument("--import-example", action="store_true",
                   help="REPLACE the line with examples/battery-remanufacturing.json")
    p.add_argument("--report-every", type=float, default=15.0)
    p.add_argument("-v", "--verbose", action="store_true", help="log every tablet action")
    args = p.parse_args()

    api = Api(args.base_url)
    try:
        who = await authenticate(api, args)
        fresh = args.email is None
        if fresh or args.import_example:
            await import_example(api)

        stations, routes, processes, templates = await asyncio.gather(
            api.get("/stations/"), api.get("/routes/"),
            api.get("/processes/"), api.get("/lot-templates/"))
        line = Line(stations, routes, processes, templates)
        posts = line.work_stations()
        if not posts:
            sys.exit("this company has no work stations to staff")

        # One tablet per station, then extras to the busiest posts.
        assignment = list(posts)
        extras = sorted(posts, key=lambda s: -line.throughput_rank(s))
        i = 0
        while len(assignment) < args.tablets:
            assignment.append(extras[i % len(extras)])
            i += 1
        assignment = assignment[:args.tablets]

        started = time.monotonic()
        stop_at = started + args.minutes * 60

        print(f"\nTaktline line simulator — driving {who}")
        print(f"  {args.tablets} tablets · {args.cycle:g}s cycle · one order every "
              f"{args.order_interval:g}s · running {args.minutes:g} min")
        for n, sid in enumerate(assignment, 1):
            role = []
            if line.is_merge(sid):
                role.append("merge")
            if line.is_fan(sid):
                role.append("choice" if line.is_choice(sid) else "split")
            if sid in line.sinks:
                role.append("ships")
            print(f"    tablet-{n:02d} → {line.name(sid)}"
                  + (f"  ({', '.join(role)})" if role else ""))
        print("  Watch it at http://localhost:3000/lots — Ctrl-C to stop early.\n", flush=True)

        stats = Stats()
        workers = [asyncio.create_task(
            tablet(n, sid, api, line, stats, args.cycle, stop_at, args.mistakes, args.verbose))
            for n, sid in enumerate(assignment, 1)]
        workers.append(asyncio.create_task(
            releaser(api, line, stats, args.order_interval, stop_at, args.verbose)))
        workers.append(asyncio.create_task(
            reporter(api, line, stats, stop_at, started, args.report_every)))

        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            pass
        finally:
            for w in workers:
                w.cancel()

        mins = (time.monotonic() - started) / 60
        print(f"\nShift over after {mins:.1f} min.")
        print(f"  orders released : {stats.orders}")
        print(f"  work sessions   : {stats.sessions}")
        print(f"  lot movements   : {stats.moves}")
        print(f"  assemblies made : {stats.merges}")
        print(f"  shipped         : {stats.handoffs}")
        if stats.errors:
            print(f"  refused         : {stats.refused} "
                  f"({', '.join(f'{k}×{v}' for k, v in sorted(stats.errors.items()))})")
            print("    Refusals are normal: tablets race for the same lots and the "
                  "loser retries.")
    finally:
        await api.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped.", flush=True)
