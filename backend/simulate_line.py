#!/usr/bin/env python3
"""Run the line from N simulated tablets, live, against a running server.

This is not a test harness: it drives the **public HTTP API** exactly as the
Operator view does — log in, pick a station, start a work session, wait out the
cycle, stop, then advance / merge / hand off. Every card movement therefore
broadcasts on the websocket, so an open browser shows the lots moving in real
time, and the sessions it records feed the real cycle-time, line-cycle-time and
utilisation statistics.

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
import math
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
        # Where an ERP raises demand. Taktline's own placement rule says a
        # demand link must point at the station where the ordered product is
        # made, so this is the authority on what a customer can order.
        self.demand_targets = {r["unload"] for r in routes
                               if r["load"] in self.partners
                               and self.stations[r["load"]].get("integrationRole")
                               in ("source", "both")}
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

    def orderable_products(self) -> list:
        """What a customer can actually order — the finished goods.

        An ERP's demand link names them: the placement rule makes it point at
        the station where the ordered product is made, so a template starting
        there is a finished good. Without any integration drawn, fall back to
        the product furthest downstream in each process.

        Getting this wrong is not cosmetic. An earlier version asked "is this
        made at a station that sends work nowhere else?" — true of nothing on a
        line whose last bench still routes to QA — and then fell back to
        "anything a merge station makes", which includes the **cleaned busbar**.
        Ordering an intermediate pulls a whole pack to get it, and that pack's
        teardown also yields four modules nobody asked for. They pile up at the
        assembly bench forever: exactly the starvation this simulation was
        supposed to be free of.
        """
        by_start: dict = {}
        for t in self.templates.values():
            sid = t.get("startStationId")
            if sid and sid in self.stations and not self.is_storage(sid):
                by_start.setdefault(sid, []).append(t)

        picked = [t for sid, ts in by_start.items()
                  if sid in self.demand_targets for t in ts]
        if not picked:
            # No ERP drawn: the deepest station of each process makes its
            # finished good.
            depth = {s: i for i, s in enumerate(self.work_stations())}
            best = max((depth.get(s, -1) for s in by_start), default=-1)
            picked = [t for sid, ts in by_start.items()
                      if depth.get(sid, -1) == best for t in ts]
        return sorted(picked, key=lambda t: t["name"])

    def throughput_rank(self, sid: str) -> int:
        """Roughly how many units pass through per pack — used to decide where
        the spare tablets go."""
        return sum(max(1, r["quantity"]) for r in self.inn.get(sid, [])) or 1


# ── How long a cycle actually takes ───────────────────────────────────────────

class Pace:
    """Where the variation in a real shift comes from.

    A flat ±20% jitter made every station report the same cycle time and every
    window the same as the one before, so the statistics page had nothing to
    show: no spread down the table, no trend arrows, no bottleneck. Four
    independent sources, each of which a shop floor genuinely has:

    * **The station.** A teardown bench is not a scanner. A fixed factor per
      station, drawn from its name so two runs of the same line are comparable.
    * **The person.** Steady differences between operators, smaller than the
      differences between stations.
    * **The piece.** Task times are right-skewed — most are near the mode and a
      few run long — which is a lognormal, not a uniform band. `--variance` is
      its sigma.
    * **The hiccup.** Occasionally something jams: a rare multi-fold cycle,
      which is what actually moves line cycle time away from cycle time.

    On top of those the whole shift **drifts**, so consecutive windows differ
    and the trend arrows have a direction to report. Negative is the line
    getting faster.
    """

    def __init__(self, cycle: float, variance: float, hiccup: float, drift: float,
                 started: float, ends: float, stations: list[str] | None = None):
        self.cycle, self.variance, self.hiccup, self.drift = cycle, variance, hiccup, drift
        self.started, self.ends = started, max(ends, started + 1)
        # Centre the station factors on THIS line, so `--cycle 5` means five
        # seconds on this floor rather than five seconds times whatever these
        # particular station names happened to hash to. (On the battery line
        # the unnormalised names ran 31% slow.)
        names = stations or []
        self._station_norm = (
            sum(self._factor(n, 2.4) for n in names) / len(names)) if names else 1.0

    @staticmethod
    def _factor(seed: str, spread: float) -> float:
        """Deterministic multiplier in roughly [1/spread, spread]."""
        h = 0
        for ch in seed:
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
        return spread ** ((h % 1000) / 500.0 - 1.0)

    # Skewing and stalling both push the AVERAGE up, so without this `--cycle 5`
    # would quietly mean "about seven seconds". Divide by what the random parts
    # add in expectation — E[lognormal] = e^(σ²/2), and a hiccup of probability
    # h multiplying by 3–9 adds 5h — so the flag keeps meaning the mean cycle
    # time at a station of average speed.
    @property
    def _normaliser(self) -> float:
        return math.exp(self.variance ** 2 / 2) * (1.0 + 5.0 * self.hiccup)

    def seconds(self, station: str, operator: str, rng: random.Random) -> float:
        base = (self.cycle * (self._factor(station, 2.4) / self._station_norm)
                * self._factor(operator, 1.25))
        secs = base * math.exp(rng.gauss(0.0, self.variance)) / self._normaliser
        if rng.random() < self.hiccup:
            secs *= rng.uniform(3.0, 9.0)          # a jam, a missing part, a question
        progress = (time.monotonic() - self.started) / (self.ends - self.started)
        secs *= 1.0 + self.drift * min(1.0, max(0.0, progress))
        return max(0.15, secs)


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
                 pace: Pace, stop_at: float, mistakes: float, verbose: bool):
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
        await asyncio.sleep(pace.seconds(name, operator, rng))
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
    finished = line.orderable_products()
    if not finished:
        print("!! no finished product found — nothing to order", flush=True)
        return
    print(f"  [orders] ordering: {', '.join(t['name'] for t in finished)}", flush=True)

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
    p.add_argument("--variance", type=float, default=0.45,
                   help="spread of cycle times (lognormal sigma); 0 = every cycle identical")
    p.add_argument("--hiccup", type=float, default=0.06,
                   help="chance a cycle stalls to several times its length")
    p.add_argument("--drift", type=float, default=-0.4,
                   help="fractional pace change from the start of the run to the end "
                        "(-0.4 = 40%% faster by the end, so trends have a direction)")
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
        pace = Pace(args.cycle, args.variance, args.hiccup, args.drift, started, stop_at,
                    stations=[line.name(s) for s in assignment])

        print(f"\nTaktline line simulator — driving {who}")
        print(f"  {args.tablets} tablets · {args.cycle:g}s mean cycle "
              f"(σ {args.variance:g}, {args.hiccup:.0%} hiccups, "
              f"{args.drift:+.0%} drift) · one order every "
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
            tablet(n, sid, api, line, stats, pace, stop_at, args.mistakes, args.verbose))
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
