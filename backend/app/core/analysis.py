"""The line doctor: a deterministic expert system that reads a line and says
what is wrong with it, in the language of the manual.

No model, no network, no data leaving the building. Every conclusion here is
arithmetic over the graph and the measurements Taktline already keeps, which is
what makes it safe to run on a customer's production data and testable against
lines with known, planted faults.

**Two kinds of finding, and the first kind matters most.**

*Topology* findings need no measurements at all. A line that cannot complete an
order, a split that delivers six pieces into a bench that consumes one, a
station every order must pass through — these are visible the moment the graph
is drawn, before anyone presses Start. That is deliberately where the value is
on day one, because a new user has no data and is exactly the person who most
needs to be told their line cannot work.

*Timing* findings need sessions and departures. They are the classic lean
questions: where is the constraint, where is the waiting, is the line balanced,
is the work repeatable.

**The vocabulary is the manual's**, not a generic lean glossary — TIMWOOD, the
distinction between takt (the beat you choose), cycle time (the work) and line
cycle time (the exit rate), and Little's law. Findings carry the manual anchor
they belong to, so the report can send a reader to the paragraph that explains
the idea rather than defining it inline every time.

**Every number is carried on the finding**, so a caller can render values from
its own data rather than parsing them out of prose.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

# ─── Inputs ───────────────────────────────────────────────────────────────────


@dataclass
class StationIn:
    id: str
    name: str
    is_storage: bool = False
    provider: Optional[str] = None          # an integration partner, if bound
    branch_mode: Optional[str] = None       # 'split' | 'choice' | None
    x: float = 0.0
    y: float = 0.0


@dataclass
class RouteIn:
    load: str
    unload: str
    quantity: int
    process: str


@dataclass
class ProcessIn:
    id: str
    name: str
    desired_takt_sec: Optional[float] = None


@dataclass
class TemplateIn:
    id: str
    name: str
    process: Optional[str]
    start_station: Optional[str]


@dataclass
class StationMetrics:
    sessions: int = 0
    units: int = 0
    working_sec: float = 0.0
    cycle_sec: Optional[float] = None        # work time per piece
    line_cycle_sec: Optional[float] = None   # interval between departures, per piece
    oee: Optional[float] = None
    samples: list = field(default_factory=list)   # per-session seconds per piece
    operators: dict = field(default_factory=dict)  # operatorId → mean sec/piece
    downtime_sec: float = 0.0       # recorded breakdowns
    changeover_sec: float = 0.0     # recorded changeovers
    wip_avg: Optional[float] = None  # time-averaged units, rebuilt from the history


@dataclass
class Snapshot:
    stations: list
    routes: list
    processes: list
    templates: list
    wip: dict                       # stationId → units standing there now
    metrics: dict                   # stationId → StationMetrics
    # units on the floor per process — Little's law is per value stream
    wip_process: dict = field(default_factory=dict)
    # (stationId, processId) → line cycle time from that process's departures
    line_cycle_by_process: dict = field(default_factory=dict)
    # (stationId, processId) → average units over open time, from the history
    wip_avg_by_process: dict = field(default_factory=dict)
    # (stationId, processId) → pieces that left per open second
    exit_rate_by_process: dict = field(default_factory=dict)
    # processId → (measured mean lead time per unit, open seconds; units)
    observed_lead_by_process: dict = field(default_factory=dict)
    # stationId → processId → units: the per-line buffer at each station,
    # which is what the runout rule (core/runout.py) divides by the rate
    wip_station_process: dict = field(default_factory=dict)
    pixels_per_unit: float = 0.0
    unit: str = "m"


# ─── Output ───────────────────────────────────────────────────────────────────

CRITICAL, WARNING, INSIGHT = "critical", "warning", "insight"


@dataclass
class Finding:
    rule: str
    severity: str
    basis: str                      # 'topology' | 'timing'
    title: str
    detail: str
    stations: list = field(default_factory=list)
    process: Optional[str] = None
    waste: Optional[str] = None     # the TIMWOOD name, where one applies
    manual: Optional[str] = None    # anchor in the user manual
    metrics: dict = field(default_factory=dict)


@dataclass
class Report:
    readiness: str                  # 'no-data' | 'partial' | 'ready'
    headline: str
    narrative: list
    findings: list
    coverage: dict


# ─── Graph helpers ────────────────────────────────────────────────────────────


def _real_routes(s: Snapshot) -> list:
    """Production flow only. An edge touching an integration partner is a
    boundary link — where the line meets somebody else's system — and is not
    material moving between benches, so it is excluded from every judgement
    about shape."""
    partners = {st.id for st in s.stations if st.provider}
    return [r for r in s.routes if r.load not in partners and r.unload not in partners]


def _by_process(s: Snapshot) -> dict:
    out: dict = {}
    for r in _real_routes(s):
        out.setdefault(r.process, []).append(r)
    return out


def _degrees(routes: list):
    incoming: dict = {}
    outgoing: dict = {}
    for r in routes:
        incoming.setdefault(r.unload, set()).add(r.load)
        outgoing.setdefault(r.load, set()).add(r.unload)
    return incoming, outgoing


def _topo(routes: list, nodes: list) -> list:
    """Kahn's order. Returns whatever it can; the graph editor already refuses
    cycles, so this never needs to report one."""
    indeg = {n: 0 for n in nodes}
    adj: dict = {n: [] for n in nodes}
    for r in routes:
        if r.load in indeg and r.unload in indeg:
            adj[r.load].append(r.unload)
            indeg[r.unload] += 1
    queue = [n for n in nodes if indeg[n] == 0]
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    return order + [n for n in nodes if n not in order]


# ─── Structural accumulation ──────────────────────────────────────────────────


def _per_unit_need(s: Snapshot, exact: bool = False) -> dict:
    """How many pieces each station handles per finished unit, per process.

    This is the normalization every rate comparison depends on. On the battery
    line, Busbar Clean touches 32 pieces for every pack that leaves Pack Test —
    so its per-piece inter-departure interval is structurally ~32× shorter, on
    a perfectly healthy day. Conservation of flow says *finished-unit*
    throughput equalizes along a steady line; *piece* throughput does not.
    Comparing raw per-piece rates therefore names the end of any split-heavy
    line the constraint, forever, and the fix it suggests is fiction.

    The walk is the same demand propagation the accumulation warning uses
    (split → max, one unit feeds every branch; choice → sum, each unit feeds
    one; THE SPLIT OWNS THE WEIGHT), so the two can never disagree about what
    a cycle is.
    """
    storage = {st.id for st in s.stations if st.is_storage}
    choice = {st.id for st in s.stations if st.branch_mode == "choice"}
    out: dict = {}
    for pid, routes in _by_process(s).items():
        nodes = sorted({r.load for r in routes} | {r.unload for r in routes})
        incoming, outgoing = _degrees(routes)

        def is_merge(n): return len(incoming.get(n, ())) >= 2
        def is_split(n): return len(outgoing.get(n, ())) >= 2 and n not in choice
        def produces(r): return max(1, r.quantity) if is_split(r.load) else 1

        def consumes(r):
            if not is_merge(r.unload):
                return 1
            return 1 if is_split(r.load) else max(1, r.quantity)

        outs: dict = {n: [] for n in nodes}
        for r in routes:
            outs[r.load].append(r)

        need: dict = {}
        for n in reversed(_topo(routes, nodes)):
            branch = outs[n]
            if not branch:
                need[n] = 1
                continue
            if exact:
                # Rates are normalised by the true share: a station upstream of
                # a one-to-four split handles a quarter of a piece per finished
                # unit, not one. Rounded up and floored at one (right for
                # seeding whole lots), it read four times slower than it is and
                # could be named the constraint of a perfectly paced line.
                per = [consumes(r) * need.get(r.unload, 1) / produces(r) for r in branch]
                if n in choice and len(branch) >= 2:
                    kept = [p for r, p in zip(branch, per) if r.unload not in storage]
                    need[n] = sum(kept) if kept else 1
                else:
                    need[n] = max(per)
                continue
            per = [math.ceil(consumes(r) * need.get(r.unload, 1) / produces(r)) for r in branch]
            if n in choice and len(branch) >= 2:
                need[n] = max(1, sum(p for r, p in zip(branch, per)
                                     if r.unload not in storage))
            else:
                need[n] = max([1] + per)
        out[pid] = need
    return out


def _accumulations(s: Snapshot) -> list:
    """Where the weights deliver more per cycle than the next step consumes.

    A mirror of the frontend's `findAccumulations`, and the same rule the map's
    warning uses: THE SPLIT OWNS THE WEIGHT. An edge out of a split yields that
    many pieces per source unit whatever it lands on, and a merge fed by a split
    consumes one piece per assembly. Reading the same number as both yield and
    consumption double-books it.
    """
    storage = {st.id for st in s.stations if st.is_storage}
    choice = {st.id for st in s.stations if st.branch_mode == "choice"}
    found = []

    for pid, routes in _by_process(s).items():
        nodes = sorted({r.load for r in routes} | {r.unload for r in routes})
        incoming, outgoing = _degrees(routes)

        def is_merge(n): return len(incoming.get(n, ())) >= 2
        def is_split(n): return len(outgoing.get(n, ())) >= 2 and n not in choice

        def produces(r): return max(1, r.quantity) if is_split(r.load) else 1

        def consumes(r):
            if not is_merge(r.unload):
                return 1
            return 1 if is_split(r.load) else max(1, r.quantity)

        outs: dict = {n: [] for n in nodes}
        ins: dict = {n: [] for n in nodes}
        for r in routes:
            outs[r.load].append(r)
            ins[r.unload].append(r)

        need = _per_unit_need(s)[pid]

        for n in nodes:
            if is_merge(n) or n in storage or not outs[n] or not ins[n]:
                continue
            if any(r.unload in storage for r in outs[n]):
                continue                        # already has the relief valve
            delivered = sum(need.get(r.load, 1) * produces(r) for r in ins[n])
            taken = need.get(n, 0)
            if delivered > taken:
                found.append({"process": pid, "station": n,
                              "delivered": delivered, "consumed": taken,
                              "surplus": delivered - taken})
    return found


def _articulations(s: Snapshot) -> list:
    """Stations every unit of a process has to pass through.

    Removing one disconnects the sources from the finished-goods end, so a
    stoppage there stops the whole value stream. Worth naming even on a healthy
    line: it is where a second machine, a trained backup or a small buffer buys
    the most resilience.
    """
    out = []
    for pid, routes in _by_process(s).items():
        nodes = sorted({r.load for r in routes} | {r.unload for r in routes})
        incoming, outgoing = _degrees(routes)
        sources = [n for n in nodes if not incoming.get(n)]
        sinks = [n for n in nodes if not outgoing.get(n)]
        if not sources or not sinks:
            continue

        def reaches(without: str) -> bool:
            seen, stack = set(), [n for n in sources if n != without]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                for r in routes:
                    if r.load == n and r.unload != without:
                        stack.append(r.unload)
            return any(t in seen for t in sinks if t != without)

        for n in nodes:
            if n in sources or n in sinks:
                continue
            if not reaches(n):
                out.append({"process": pid, "station": n})
    return out


# ─── Rules: topology (no measurements required) ───────────────────────────────

def _fmt(n: float, unit: str = "") -> str:
    if n >= 100:
        return f"{n:,.0f}{unit}"
    if n >= 10:
        return f"{n:.0f}{unit}"
    return f"{n:.1f}{unit}"


def _mmss(sec: float) -> str:
    """Seconds a person can read. Cycle times run from seconds to hours."""
    if sec < 90:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{int(sec // 60)}m {int(sec % 60):02d}s"
    return f"{sec / 3600:.1f}h"


def _topology_findings(s: Snapshot) -> list:
    names = {st.id: st.name for st in s.stations}
    partners = {st.id for st in s.stations if st.provider}
    procs = {p.id: p for p in s.processes}
    routes = _real_routes(s)
    out: list = []

    if not routes:
        out.append(Finding(
            rule="no-flow", severity=CRITICAL, basis="topology",
            title="Nothing is connected yet",
            detail="No routes have been drawn, so there is no value stream to analyse. "
                   "Draw the real process once — where work happens and how it connects — "
                   "and every view derives from it.",
            ))
        return out

    touched = {r.load for r in routes} | {r.unload for r in routes}
    islands = [st for st in s.stations
               if st.id not in touched and st.id not in partners and not st.is_storage]
    if islands:
        out.append(Finding(
            rule="island-station", severity=WARNING, basis="topology",
            title=f"{_plural(len(islands), 'station').capitalize()} "
                  f"{'sit' if len(islands) != 1 else 'sits'} outside the flow",
            detail=f"{', '.join(st.name for st in islands[:4])} "
                   f"{'have' if len(islands) != 1 else 'has'} no routes at all, so no work can "
                   "reach or leave. Either connect them or remove them — a station on the floor "
                   "plan that nothing flows through still reads as part of the line.",
            stations=[st.id for st in islands]))

    for pid, rs in _by_process(s).items():
        pname = procs[pid].name if pid in procs else "this process"
        nodes = {r.load for r in rs} | {r.unload for r in rs}
        incoming, outgoing = _degrees(rs)
        sinks = [n for n in nodes if not outgoing.get(n)]
        sources = [n for n in nodes if not incoming.get(n)]
        hands_off = any(r.load in nodes and r.unload in partners for r in s.routes)

        if not sinks and not hands_off:
            out.append(Finding(
                rule="no-finished-end", severity=CRITICAL, basis="topology",
                title=f"{pname} never finishes",
                detail="Every station sends work onward and none is a finished-goods end, so "
                       "nothing in this process can ever complete. Give the last step no outgoing "
                       "route, or hand off to an integration.",
                process=pid))
        if not sources:
            out.append(Finding(
                rule="no-source", severity=CRITICAL, basis="topology",
                title=f"{pname} has nowhere for material to enter",
                detail="Every station is fed by another, so there is no queue where raw material "
                       "starts. A pull needs a leaf to seed.",
                process=pid))

        starts = {t.start_station for t in s.templates if t.process == pid and t.start_station}
        if not starts:
            out.append(Finding(
                rule="no-product", severity=WARNING, basis="topology",
                title=f"{pname} makes nothing yet",
                detail="No product template starts anywhere in this process, so an order has "
                       "nothing to release and a pull has nothing to seed.",
                process=pid))

        if procs.get(pid) and procs[pid].desired_takt_sec is None:
            out.append(Finding(
                rule="no-takt", severity=INSIGHT, basis="topology",
                title=f"No takt time set for {pname}",
                detail="Takt is the beat your customer sets — available time ÷ demand — and it is "
                       "the only one of the three timing numbers you choose rather than measure. "
                       "Without it there is nothing to judge a station's cycle time against, and "
                       "'fast enough' stays a matter of opinion. Set it in Settings → Processes.",
                process=pid, manual="timing"))

    for acc in _accumulations(s):
        pname = procs[acc["process"]].name if acc["process"] in procs else ""
        out.append(Finding(
            rule="accumulation", severity=WARNING, basis="topology",
            title=f"Work piles up at {names.get(acc['station'], 'a station')}",
            detail=f"Every cycle delivers {_plural(acc['delivered'], 'unit')} into "
                   f"{names.get(acc['station'], 'this station')}"
                   f"{f' on {pname}' if pname else ''} while the next step consumes "
                   f"{_words(acc['consumed'])} — a surplus of {_words(acc['surplus'])} per "
                   "cycle, built into the "
                   "weights rather than caused by anyone's pace. It will grow for as long as the "
                   "line runs. Route the surplus to a storage location, or correct the ratio.",
            stations=[acc["station"]], process=acc["process"],
            waste="Overproduction", manual="waste",
            metrics={"delivered": acc["delivered"], "consumed": acc["consumed"],
                     "surplus": acc["surplus"]}))

    # Grouped by station, not by process. A station that every line depends on
    # is *more* worth naming, not worth saying twice — and printing the same
    # sentence with a different process in it reads like a broken report, which
    # costs more credibility than the finding earns.
    per_station: dict = {}
    for art in _articulations(s):
        per_station.setdefault(art["station"], []).append(art["process"])
    for sid, pids in per_station.items():
        pnames = [procs[p].name for p in pids if p in procs]
        who = _english_list(pnames) if pnames else "this process"
        every = "Every unit of " + who + " has to cross"
        if len(pids) > 1:
            # "all two processes" is not English; two things are *both*.
            how_many = "both" if len(pids) == 2 else f"all {_words(len(pids))}"
            every = f"Every unit of {how_many} processes ({who}) has to cross"
        out.append(Finding(
            rule="single-point-of-failure", severity=INSIGHT, basis="topology",
            title=f"Everything passes through {names.get(sid, 'one station')}",
            detail=f"{every} {names.get(sid, 'this station')}; if it stops, the whole value "
                   "stream stops with it. That is where a trained backup, a second machine or a "
                   "small deliberate buffer buys more than anywhere else on the line.",
            stations=[sid], process=pids[0] if len(pids) == 1 else None,
            metrics={"processes": len(pids)}))

    if s.pixels_per_unit > 0:
        lengths = []
        for r in routes:
            a = next((st for st in s.stations if st.id == r.load), None)
            b = next((st for st in s.stations if st.id == r.unload), None)
            if a and b:
                d = math.dist((a.x, a.y), (b.x, b.y)) / s.pixels_per_unit
                lengths.append((d, r))
        if len(lengths) >= 3:
            median = statistics.median(d for d, _ in lengths)
            far = [(d, r) for d, r in lengths if median > 0 and d > 3 * median]
            if far:
                # Compare by distance only: two processes sharing one pair of
                # stations give two routes of identical length, and a plain
                # max() then compared RouteIn objects and raised TypeError,
                # taking the whole report down on a high-mix line with one
                # process per routing.
                d, r = max(far, key=lambda x: x[0])
                out.append(Finding(
                    rule="long-transport", severity=INSIGHT, basis="topology",
                    title="One move is much longer than the rest",
                    detail=f"{names.get(r.load, '?')} → {names.get(r.unload, '?')} is "
                           f"{_fmt(d, s.unit)}, against a typical {_fmt(median, s.unit)} on this "
                           "floor. Transport is the easiest waste to see and the first place to "
                           "gain: moving those two benches together costs nothing but a morning.",
                    stations=[r.load, r.unload], waste="Transport", manual="waste",
                    metrics={"metres": round(d, 1), "median": round(median, 1)}))
    return out


# ─── Rules: timing (need measurements) ────────────────────────────────────────

# What counts as enough to say anything about pace. Below this the honest answer
# is that nobody has run a timer, and saying so is the feature — a report that
# invents advice from three sessions is worse than one that admits it cannot see.
READY_STATIONS = 3
READY_SESSIONS = 12


def _worked(s: Snapshot) -> dict:
    """Stations with a measured cycle time, excluding the ones that are not
    supposed to have one: a shelf stores rather than runs, and an integration
    node never holds work at all."""
    skip = {st.id for st in s.stations if st.is_storage or st.provider}
    return {sid: m for sid, m in s.metrics.items()
            if sid not in skip and m.cycle_sec and m.cycle_sec > 0}


def _readiness(s: Snapshot) -> tuple:
    worked = _worked(s)
    sessions = sum(m.sessions for m in s.metrics.values())
    coverage = {"stationsWithTiming": len(worked), "sessions": sessions,
                "stationsNeeded": READY_STATIONS, "sessionsNeeded": READY_SESSIONS}
    if sessions == 0:
        return "no-data", coverage
    if len(worked) >= READY_STATIONS and sessions >= READY_SESSIONS:
        return "ready", coverage
    return "partial", coverage


def _reachable(routes: list, frm: str) -> set:
    """Stations downstream of `frm` within one process's production routes."""
    seen, stack = set(), [frm]
    while stack:
        n = stack.pop()
        for r in routes:
            if r.load == n and r.unload not in seen:
                seen.add(r.unload)
                stack.append(r.unload)
    return seen


def _stream_lead(s: Snapshot, pid: str, routes: list, need: dict):
    """Lead time of one value stream from the moves alone: each lot's measured
    flow time where enough have finished, Little's law (average WIP over exit
    rate) before that. None where the stream holds too little to say."""
    members = {r.load for r in routes} | {r.unload for r in routes}
    # Little's law holds for averages. Divided into the WIP on the floor at
    # the moment someone asks, it returns the lead time of that moment, and
    # a line's WIP swings through the day. The history gives the average, in finished-unit
    # equivalents; the live count is the fallback while there is no history.
    shelves_p = {st.id for st in s.stations if st.is_storage or st.provider}
    # Stock waiting at an entry station has not been released yet: lead time
    # runs from leaving it, so it is not work in process.
    shelves_p |= {n for n in members if not any(r.unload == n for r in routes)}
    avg = 0.0
    have_avg = False
    if s.wip_avg_by_process:
        # Each stream's own average WIP, from the history: at a shared
        # station the units of the other stream are not this one's.
        for sid in members:
            if sid in shelves_p:
                continue
            v = s.wip_avg_by_process.get((sid, pid))
            if v is not None:
                avg += v / max(need.get(sid, 1), 1e-9)
                have_avg = True
    for sid in (members if not have_avg else ()):
        m = s.metrics.get(sid)
        if sid in shelves_p or m is None or m.wip_avg is None:
            continue
        per = s.wip_station_process.get(sid) or {}
        total_here = sum(per.values())
        share = (per.get(pid, 0) / total_here) if total_here else (
            1.0 if sum(1 for rs in _by_process(s).values() if any(sid in (r.load, r.unload) for r in rs)) == 1 else 0.0)
        avg += m.wip_avg * share / max(need.get(sid, 1), 1e-9)
        have_avg = True
    wip_here = avg if have_avg else s.wip_process.get(pid, 0)
    if wip_here < 5:
        return None
    sinks = [n for n in members
             if not any(r.load == n for r in routes)]
    # A process that ends on a shelf exits through the stations feeding
    # it: nothing ever departs a warehouse, so its line cycle time is
    # null, and measuring there left every line that finishes into
    # storage without a lead time at all.
    storage = {st.id for st in s.stations if st.is_storage}
    ends: set = set()
    for n in sinks:
        if n in storage:
            ends |= {r.load for r in routes if r.unload == n and r.load not in storage}
        else:
            ends.add(n)
    # Throughput as Little's law needs it: pieces out per open second over
    # the period. The reciprocal of line cycle time is a mean of
    # per-departure ratios, which a once-a-day shipment makes noisy.
    exit_ths = [s.exit_rate_by_process[(n, pid)] for n in sorted(ends)
                if s.exit_rate_by_process.get((n, pid))]
    if not exit_ths:
        lc_end = {n: s.line_cycle_by_process.get((n, pid), s.metrics[n].line_cycle_sec)
                  for n in ends if n in s.metrics}
        exit_ths = [1.0 / v for n, v in sorted(lc_end.items()) if v]
    if not exit_ths:
        return None
    # The lead time the record measured, lot by lot, from release to
    # finish, where there is one; Little's law where there is not yet.
    # Little's law is exact for a line, but across a merge it adds up the
    # feeds' inventory, which flow in parallel, and overstates.
    obs = s.observed_lead_by_process.get(pid)
    measured = bool(obs and obs[1] >= 20)
    lead = obs[0] if measured else wip_here / sum(exit_ths)
    return {"lead": lead, "wip": wip_here, "have_avg": have_avg, "measured": measured}


def _timing_findings(s: Snapshot) -> list:
    names = {st.id: st.name for st in s.stations}
    procs = {p.id: p for p in s.processes}
    worked = _worked(s)
    out: list = []
    if not worked:
        return out

    by_process = _by_process(s)
    needs = _per_unit_need(s, exact=True)
    shelves = {st.id for st in s.stations if st.is_storage}
    floor = {sid: n for sid, n in s.wip.items() if sid not in shelves and n > 0}
    oees = {sid: m.oee for sid, m in worked.items() if m.oee is not None}
    oee_median = statistics.median(oees.values()) if len(oees) >= 3 else None

    # Which stations are entries (nothing feeds them): their exit rate is the
    # release rate, not their own pace, and the constraint rules must not
    # mistake the front door for the narrowest doorway.
    incoming_all, _o = _degrees(_real_routes(s))
    entries = {st.id for st in s.stations
               if not incoming_all.get(st.id) and not st.provider and not st.is_storage}

    constraint_of: dict = {}          # pid → station named the constraint

    # ── Per value stream: the constraint, and a line outrun by its orders ──
    #
    # All rates are normalized to FINISHED-UNIT equivalents: a station's
    # per-piece interval × the pieces it handles per finished unit. Without
    # this, the end of any split-heavy line looks like the constraint --
    # Pack Test sees one piece where Busbar Clean saw thirty-two -- and the
    # report sends someone to speed up a bench that is perfectly in step.
    for pid, routes in by_process.items():
        need = needs.get(pid, {})
        members = {r.load for r in routes} | {r.unload for r in routes}
        lct = {sid: s.line_cycle_by_process.get((sid, pid), worked[sid].line_cycle_sec)
               for sid in members if sid in worked}
        norm = {sid: v * need.get(sid, 1) for sid, v in lct.items() if v}
        if not norm:
            continue
        pname = procs[pid].name if pid in procs else "this line"

        # Outrun by its orders: the entry interval dwarfs the line's own pace.
        entry_norm = {sid: v for sid, v in norm.items() if sid in entries}
        rest_norm = {sid: v for sid, v in norm.items() if sid not in entries}
        if len(norm) >= 3 and entry_norm and rest_norm:
            feeder = max(entry_norm, key=lambda k: entry_norm[k])
            downstream = statistics.median(rest_norm.values())
            if downstream and entry_norm[feeder] > 1.3 * downstream:
                out.append(Finding(
                    rule="demand-limited", severity=INSIGHT, basis="timing",
                    title=f"{pname} is faster than the work arriving at "
                          f"{names.get(feeder, 'the front')}",
                    detail=f"A finished unit's worth of material enters at "
                           f"{names.get(feeder, 'the first station')} every "
                           f"{_mmss(entry_norm[feeder])}, while the line itself turns one "
                           f"round every {_mmss(downstream)}. Nothing here is a bottleneck — "
                           "the line is over-dimensioned for the orders it is getting, and "
                           "the idle capacity is paid for either way. Rather than speeding "
                           "anything up, consider combining steps so that fewer stations "
                           "each do more: a longer cycle time at fewer benches, matched to "
                           "the rate work actually arrives, frees people and floor without "
                           "slowing anything down.",
                    stations=[feeder], process=pid, waste="Waiting", manual="timing",
                    metrics={"entrySec": round(entry_norm[feeder], 1),
                             "downstreamSec": round(downstream, 1)}))

        # The constraint — with corroborating evidence where it exists.
        # Naming it is Goldratt's first focusing step; the *advice* is the
        # second and third: exploit it (it must never wait), subordinate the
        # rest, and only then buy capacity. An hour lost here is an hour lost
        # for the whole line; an hour saved anywhere else is a mirage.
        if len(rest_norm) >= 2:
            slowest = max(rest_norm, key=lambda k: rest_norm[k])
            others = sorted(v for k, v in rest_norm.items() if k != slowest)
            typical = statistics.median(others) if others else 0
            if typical and rest_norm[slowest] > 1.3 * typical:
                constraint_of[pid] = slowest
                factor = need.get(slowest, 1)
                per_unit = (f"A finished unit's worth of work leaves it every "
                            f"{_mmss(rest_norm[slowest])}"
                            + (f" ({factor:g} pieces at {_mmss(lct[slowest])}"
                               f" each)" if factor > 1 else "")
                            + f", against {_mmss(typical)} elsewhere on {pname}.")
                evidence = []
                if floor.get(slowest, 0) >= 3:
                    evidence.append(f"{_words(floor[slowest])} units are queued at it")
                if (oee_median and slowest in oees
                        and oees[slowest] >= max(oees.values()) - 1e-9
                        and oees[slowest] > 1.15 * oee_median):
                    evidence.append(f"it runs the largest share of open hours "
                                    f"({oees[slowest] * 100:.0f}%)")
                starved_downstream = [
                    t for t in _reachable(routes, slowest)
                    if t in oees and oee_median and oees[t] < oee_median / 2]
                if starved_downstream:
                    evidence.append(f"{names.get(starved_downstream[0], 'a station')} "
                                    "downstream is idle waiting for it")
                corro = (" More signs point the same way: "
                         + _english_list(evidence) + "." if evidence else "")
                out.append(Finding(
                    rule="bottleneck", severity=WARNING, basis="timing",
                    title=f"{names.get(slowest, '?')} is the constraint",
                    detail=f"{per_unit} That is the pace of the whole line, whatever the "
                           "other stations manage — an hour lost here is an hour lost for "
                           "everything, and an hour saved anywhere else is a mirage."
                           f"{corro} Before spending anything, make sure it never waits: "
                           "keep a small buffer in front of it, stagger breaks so it is "
                           "never unmanned, and move inspection or prep off it. Only when "
                           "it runs every open minute is more capacity worth buying.",
                    stations=[slowest], process=pid, manual="timing",
                    metrics={"lineCycleSec": round(rest_norm[slowest], 1),
                             "typicalSec": round(typical, 1),
                             "perUnitPieces": factor,
                             "evidence": len(evidence)}))

    # ── A line paced by its orders has no slow exit, but it still has a
    # station closest to its capacity, and that is the one that breaks first
    # when demand grows or a robot is chosen. Exit intervals cannot show it
    # (every station leaves at the release pace), so it is read from load: the
    # share of open time a station is working, broken down or being changed
    # over. Only when the exit-rate rule above has nothing to say.
    for pid, routes in by_process.items():
        if pid in constraint_of:
            continue
        members = {r.load for r in routes} | {r.unload for r in routes}
        load = {}
        for sid in members:
            m = worked.get(sid)
            if m is None or sid in entries or not m.oee or m.oee <= 0 or not m.working_sec:
                continue
            open_sec = m.working_sec / m.oee
            load[sid] = min(1.0, (m.working_sec + m.downtime_sec + m.changeover_sec) / open_sec)
        if len(load) < 2:
            continue
        top = max(load, key=lambda k: load[k])
        rest = sorted((v for k, v in load.items() if k != top), reverse=True)
        if load[top] < 0.7:
            continue
        constraint_of[pid] = top
        pname = procs[pid].name if pid in procs else "this line"
        m = worked[top]
        parts = [f"working {m.oee * 100:.0f}%"]
        if m.downtime_sec:
            parts.append(f"broken down {m.downtime_sec / (m.working_sec / m.oee) * 100:.0f}%")
        if m.changeover_sec:
            parts.append(f"in changeover {m.changeover_sec / (m.working_sec / m.oee) * 100:.0f}%")
        out.append(Finding(
            rule="bottleneck", severity=WARNING, basis="load",
            title=f"{names.get(top, '?')} is closest to its capacity",
            detail=f"{pname} is paced by the work arriving, so every station leaves at the "
                   f"same rate and none shows up as slow. {names.get(top, 'This station')} is "
                   f"the one with the least slack: {_english_list(parts)} of open time, "
                   f"{load[top] * 100:.0f}% in all, against {rest[0] * 100:.0f}% at the next "
                   "busiest. It is the constraint the line will meet first if demand rises, "
                   "and the first place where saved time shortens the queue.",
            stations=[top], process=pid, manual="timing",
            metrics={"load": round(load[top], 3), "nextLoad": round(rest[0], 3)}))

    # ── Against the beat the customer sets — in per-unit work, with sizing.
    for pid, p in procs.items():
        if not p.desired_takt_sec:
            continue
        need = needs.get(pid, {})
        members = ({r.load for r in by_process.get(pid, [])}
                   | {r.unload for r in by_process.get(pid, [])})
        per_unit = {sid: worked[sid].cycle_sec * need.get(sid, 1)
                    for sid in members if sid in worked and worked[sid].cycle_sec}
        over = [(sid, w) for sid, w in per_unit.items() if w > p.desired_takt_sec]
        if over:
            worst = max(over, key=lambda t: t[1])
            sid, w = worst
            factor = need.get(sid, 1)
            benches = math.ceil(w / p.desired_takt_sec)
            oee_note = ""
            if sid in oees and oees[sid] and oees[sid] < 0.97:
                sustainable = math.ceil(w / (p.desired_takt_sec * oees[sid]))
                if sustainable > benches:
                    oee_note = (f" And since this station only runs "
                                f"{oees[sid] * 100:.0f}% of open hours, holding the beat "
                                f"sustainably takes {_words(sustainable)} rather than "
                                f"{_words(benches)}.")
            out.append(Finding(
                rule="over-takt", severity=CRITICAL, basis="timing",
                title=f"{names.get(sid, '?')} cannot hold the takt for {p.name}",
                detail=f"Takt is {_mmss(p.desired_takt_sec)} — one finished unit must "
                       f"leave that often to meet demand — but each unit needs "
                       f"{_mmss(w)} of work at {names.get(sid, 'this station')}"
                       + (f" ({factor:g} pieces at {_mmss(worked[sid].cycle_sec)} each)"
                          if factor > 1 else "")
                       + ". A station whose work content exceeds takt cannot keep up "
                       f"however well it is run. Arithmetic, not opinion: this step "
                       f"needs {_words(benches)} parallel bench"
                       f"{'es' if benches != 1 else ''} or operators, or enough of the "
                       f"work moved elsewhere to fit under the beat.{oee_note}",
                stations=[t[0] for t in over], process=pid,
                waste="Waiting", manual="timing",
                metrics={"taktSec": p.desired_takt_sec, "perUnitWorkSec": round(w, 1),
                         "stationsOverTakt": len(over), "benchesNeeded": benches}))

        # No headroom: close to takt is not "just fitting", it is a queue
        # factory. Queueing theory (Kingman's formula) says waiting time grows
        # with utilisation/(1−utilisation): at 90% of takt every small hiccup
        # queues nine times longer than at 50%. A line needs slack to absorb
        # its own variability, and a station with none exports every wobble
        # downstream as lateness.
        near = [(sid, w) for sid, w in per_unit.items()
                if 0.85 * p.desired_takt_sec <= w <= p.desired_takt_sec]
        for sid, w in sorted(near, key=lambda t: -t[1])[:1]:
            rho = w / p.desired_takt_sec
            mult = rho / (1 - rho) if rho < 1 else float("inf")
            cv = None
            if len(worked[sid].samples) >= 6:
                mean = statistics.fmean(worked[sid].samples)
                if mean > 0:
                    cv = statistics.pstdev(worked[sid].samples) / mean
            out.append(Finding(
                rule="no-headroom", severity=INSIGHT, basis="timing",
                title=f"{names.get(sid, '?')} has no headroom against the takt",
                detail=f"Its work content is {_mmss(w)} against a takt of "
                       f"{_mmss(p.desired_takt_sec)} — {rho * 100:.0f}% loaded. That is "
                       "not comfortably fitting; it is the steep part of the queueing "
                       "curve, where waiting grows with load ÷ (1 − load): at this "
                       f"utilisation every disruption queues roughly {mult:.0f}× its own "
                       "length before draining."
                       + (f" The work here also varies (spread/mean {cv:.1f}), which "
                          "multiplies exactly that queueing." if cv and cv >= 0.3 else "")
                       + " Either shave a little work content off, or accept and size "
                       "the buffer in front knowingly.",
                stations=[sid], process=pid, waste="Inventory", manual="timing",
                metrics={"utilization": round(rho, 3),
                         "queueMultiplier": round(mult, 1) if mult != float("inf") else None}))

    # ── Balance, as the payroll sees it — in occupied time per finished
    #    unit, for the same reason the constraint is: a station doing eight
    #    pieces per unit is busy eight times its piece time.
    factor_of = {}
    for pid, need in needs.items():
        for sid, k in need.items():
            factor_of[sid] = max(factor_of.get(sid, k), k)
    # Balancing is about work that could be moved between stations that run
    # at one pace. An entry station (a press stamping into a supermarket, a
    # kitting bench) runs at the release pace, often in campaigns, and its
    # seconds per piece are not work anyone could move to an assembler — the
    # constraint rule leaves it out for the same reason.
    cycles = {sid: m.cycle_sec * factor_of.get(sid, 1)
              for sid, m in worked.items() if m.cycle_sec and sid not in entries}
    if len(cycles) >= 2:
        fastest = min(cycles, key=lambda k: cycles[k])
        slowest = max(cycles, key=lambda k: cycles[k])
        ratio = cycles[slowest] / cycles[fastest] if cycles[fastest] else 0
        if ratio >= 2:
            # Balance efficiency: of the station-time the payroll buys each
            # cycle, how much is work? Σ cycle / (n × slowest) — the classic
            # assembly-line-balancing measure.
            eff = sum(cycles.values()) / (len(cycles) * cycles[slowest])
            combine = ""
            for pid, routes in by_process.items():
                outs_ct: dict = {}
                ins_ct: dict = {}
                succ: dict = {}
                for r in routes:
                    outs_ct[r.load] = outs_ct.get(r.load, 0) + 1
                    ins_ct[r.unload] = ins_ct.get(r.unload, 0) + 1
                    succ[r.load] = r.unload
                pairs = [(u, v) for u, v in succ.items()
                         if outs_ct.get(u) == 1 and ins_ct.get(v) == 1
                         and u in cycles and v in cycles
                         and cycles[u] + cycles[v] <= cycles[slowest]]
                if pairs:
                    u, v = min(pairs, key=lambda t: cycles[t[0]] + cycles[t[1]])
                    combine = (f" For instance, {names.get(u, '?')} and "
                               f"{names.get(v, '?')} together "
                               f"({_mmss(cycles[u])} + {_mmss(cycles[v])}) still fit "
                               f"under the slowest step — one bench instead of two, "
                               "and nothing gets later.")
                    break
            out.append(Finding(
                rule="line-imbalance", severity=WARNING, basis="timing",
                title=f"The line is unbalanced — {ratio:.1f}× between fastest and slowest",
                detail=f"{names.get(slowest, '?')} carries {_mmss(cycles[slowest])} of work "
                       f"per finished unit while {names.get(fastest, '?')} carries "
                       f"{_mmss(cycles[fastest])}. "
                       f"Balance efficiency is {eff * 100:.0f}%: of every hour of "
                       "station time the payroll buys, only that share is work and the "
                       "rest is built-in waiting. Moving work from the slow step to the "
                       f"fast one costs nothing and raises the whole line.{combine}",
                stations=[slowest, fastest], waste="Waiting", manual="timing",
                metrics={"ratio": round(ratio, 2),
                         "slowestSec": round(cycles[slowest], 1),
                         "fastestSec": round(cycles[fastest], 1),
                         "balanceEfficiency": round(eff, 2)}))

    # ── Where the work-in-process is — on average over open time, not now.
    # A live count is a snapshot, and reads a momentary pile as a standing
    # one; the history-rebuilt average is what Little's law turns into lead
    # time. The live count stands in only before there is any history.
    avg_floor = {sid: m.wip_avg for sid, m in s.metrics.items()
                 if sid not in shelves and m.wip_avg is not None and m.wip_avg > 0}
    pile = avg_floor or floor
    if sum(pile.values()) >= 8 and pile:
        worst = max(pile, key=lambda k: pile[k])
        share = pile[worst] / max(1, sum(pile.values()))
        if share >= 0.4 and len(pile) >= 2:
            drain = ""
            if worst in worked and worked[worst].cycle_sec:
                wait = pile[worst] * worked[worst].cycle_sec
                drain = (f" Even working flat out, the last unit in that queue waits "
                         f"{_mmss(wait)} before its turn.")
            out.append(Finding(
                rule="wip-concentration", severity=WARNING, basis="timing",
                title=f"{int(share * 100)}% of the work in process is at "
                      f"{names.get(worst, '?')}",
                detail=f"{_words(int(round(pile[worst]))).capitalize()} of "
                       f"{_words(int(round(sum(pile.values()))))} units on the floor"
                       f"{' on average' if avg_floor else ''} are waiting "
                       f"at {names.get(worst, 'one station')}. WIP piling up in front of "
                       "a station is the signature of a bottleneck, and by Little's law "
                       "it is also lead time: halve the queue and you halve how long an "
                       f"order takes to cross the shop.{drain}",
                stations=[worst], waste="Inventory", manual="waste",
                metrics={"units": round(pile[worst], 1), "floorUnits": round(sum(pile.values()), 1),
                         "share": round(share, 2), "basis": "average" if avg_floor else "live"}))

    # ── Lead time and flow efficiency: the value-stream headline.
    # Little's law (lead time = WIP ÷ throughput) applied per value stream,
    # against the touch time a unit actually receives. The ratio is the number
    # value-stream mapping exists to expose, and in most job shops it is
    # single-digit percent — the unit spends its life waiting, and no one
    # working faster changes that. Only cutting WIP does.
    for pid, routes in by_process.items():
        need = needs.get(pid, {})
        members = {r.load for r in routes} | {r.unload for r in routes}
        sl = _stream_lead(s, pid, routes, need)
        if sl is None:
            continue
        lead, wip_here, have_avg, measured = sl["lead"], sl["wip"], sl["have_avg"], sl["measured"]
        obs = s.observed_lead_by_process.get(pid)
        touch = sum(worked[sid].cycle_sec * need.get(sid, 1)
                    for sid in members if sid in worked and worked[sid].cycle_sec)
        if touch <= 0:
            continue
        if lead <= touch:
            continue
        eff = touch / lead
        pname = procs[pid].name if pid in procs else "this line"
        out.append(Finding(
            rule="flow-efficiency", severity=INSIGHT, basis="timing",
            title=f"A unit crosses {pname} in {_mmss(lead)}; only "
                  f"{eff * 100:.0f}% of that is work",
            detail=f"By Little's law — lead time is WIP divided by throughput — the "
                   f"{_words(int(round(wip_here)))} units on the floor{' on average' if have_avg else ''} at today's exit rate mean "
                   f"about {_mmss(lead)} from release to finish, of which the work "
                   f"itself is {_mmss(touch)}. The other {(1 - eff) * 100:.0f}% is "
                   "waiting. Most job shops live in single digits here, so this is not "
                   "an accusation — it is the largest lever on the board: cutting WIP "
                   "in half halves the lead time, and nobody has to work faster.",
            process=pid, waste="Inventory", manual="waste",
            metrics={"leadSec": round(lead, 0), "touchSec": round(touch, 0),
                     "flowEfficiency": round(eff, 3), "wip": round(wip_here, 1),
                     "wipBasis": "average" if have_avg else "live",
                     "leadBasis": "measured" if measured else "littles-law"}))

    # ── A merge waits for its slowest feed: matched sets, not full bins.
    for pid, routes in by_process.items():
        need = needs.get(pid, {})
        ins_by: dict = {}
        for r in routes:
            ins_by.setdefault(r.unload, set()).add(r.load)
        for m_station, feeds in ins_by.items():
            if len(feeds) < 2:
                continue
            feed_lc = {u: s.line_cycle_by_process.get((u, pid), worked[u].line_cycle_sec)
                       for u in feeds if u in worked}
            feed_norm = {u: v * need.get(u, 1) for u, v in feed_lc.items() if v}
            if len(feed_norm) < 2:
                continue
            slow = max(feed_norm, key=lambda k: feed_norm[k])
            fast = min(feed_norm, key=lambda k: feed_norm[k])
            if feed_norm[fast] and feed_norm[slow] / feed_norm[fast] >= 1.5:
                out.append(Finding(
                    rule="unmatched-feeds", severity=INSIGHT, basis="timing",
                    title=f"{names.get(m_station, 'The merge')} is paced by its "
                          f"slowest feed, {names.get(slow, '?')}",
                    detail=f"An assembly can only start when EVERY part is there, so a "
                           "merge inherits the pace of its slowest branch. "
                           f"{names.get(slow, '?')} delivers a set every "
                           f"{_mmss(feed_norm[slow])} while {names.get(fast, '?')} "
                           f"manages {_mmss(feed_norm[fast])} — everything the fast "
                           "branch makes above that pace is inventory waiting for its "
                           "partner. Balance the branches, or give the erratic one a "
                           "small deliberate buffer sized in matched sets, not full "
                           "bins.",
                    stations=[m_station, slow], process=pid,
                    waste="Inventory", manual="waste",
                    metrics={"slowFeedSec": round(feed_norm[slow], 1),
                             "fastFeedSec": round(feed_norm[fast], 1)}))
                break
        else:
            continue
        break

    # ── One machine, every value stream: a monument.
    station_procs: dict = {}
    for pid, routes in by_process.items():
        for r in routes:
            station_procs.setdefault(r.load, set()).add(pid)
            station_procs.setdefault(r.unload, set()).add(pid)
    for sid, pids in station_procs.items():
        if len(pids) < 2 or sid not in oees or oee_median is None:
            continue
        if oees[sid] >= max(oees.values()) - 1e-9 and oees[sid] > 1.2 * oee_median:
            pnames = sorted(procs[p].name for p in pids if p in procs)
            out.append(Finding(
                rule="shared-monument", severity=INSIGHT, basis="timing",
                title=f"{names.get(sid, '?')} is a monument shared by "
                      f"{_words(len(pids))} value streams",
                detail=f"It serves {_english_list(pnames)} and runs the highest share "
                       f"of open hours on the floor ({oees[sid] * 100:.0f}%). One "
                       "machine every product must visit sets the pace for all of them "
                       "at once, and every changeover on it is paid by every line. "
                       "Schedule it deliberately, keep a small buffer in front, and "
                       "when it comes up for replacement consider two right-sized "
                       "machines over one faster monument.",
                stations=[sid], waste="Waiting",
                metrics={"processes": len(pids), "oee": round(oees[sid], 3)}))
            break

    # ── Repeatability — and WHICH kind of unrepeatable, because the remedies
    #    are opposite. A few extreme cycles among steady ones are special
    #    causes (a tool hunt, missing material, rework): go and see those
    #    events. A wide spread everywhere is a common cause (no standard
    #    work): write the method down. Shewhart's distinction, and chasing
    #    the wrong one demoralises people without moving the number.
    for sid, m in worked.items():
        if len(m.samples) < 6:
            continue
        mean = statistics.fmean(m.samples)
        med = statistics.median(m.samples)
        if mean <= 0 or med <= 0:
            continue
        cv = statistics.pstdev(m.samples) / mean
        if cv >= 0.6:
            spiky = mean / med >= 1.25 and max(m.samples) >= 3 * med
            if spiky:
                n_spikes = sum(1 for x in m.samples if x >= 3 * med)
                shape = "spikes"
                diagnosis = (f"Most cycles cluster near {_mmss(med)}, but "
                             f"{_words(n_spikes)} of {_words(len(m.samples))} blew "
                             f"out to {_mmss(max(m.samples))} or thereabouts. That "
                             "pattern is special-cause: something interrupts the work "
                             "— a tool hunt, missing material, rework — rather than "
                             "the work itself varying. Averages hide it; go and see "
                             "what happened on those particular cycles.")
            else:
                shape = "spread"
                diagnosis = ("The spread is broad across all cycles rather than a few "
                             "bad ones — common-cause variation, which usually means "
                             "the step is really several different jobs, or that there "
                             "is no standard way of doing it. Write the best method "
                             "down and teach it; exhorting people to be consistent "
                             "without a standard moves nothing.")
            out.append(Finding(
                rule="uneven-work", severity=INSIGHT, basis="timing",
                title=f"The work at {names.get(sid, '?')} is not repeatable",
                detail=f"Cycle times there range from {_mmss(min(m.samples))} to "
                       f"{_mmss(max(m.samples))} around a mean of {_mmss(mean)}. "
                       f"{diagnosis} Unevenness is the waste that hides the others: "
                       "no bottleneck, takt or average can be trusted until the same "
                       "job takes about the same time twice.",
                stations=[sid],
                metrics={"cv": round(cv, 2), "meanSec": round(mean, 1),
                         "medianSec": round(med, 1), "shape": shape,
                         "minSec": round(min(m.samples), 1),
                         "maxSec": round(max(m.samples), 1)}))
            break

    # ── Two people, one bench, very different times.
    for sid, m in worked.items():
        if len(m.operators) < 2:
            continue
        vals = sorted(m.operators.values())
        if vals[0] > 0 and vals[-1] / vals[0] >= 2.5:
            out.append(Finding(
                rule="operator-spread", severity=INSIGHT, basis="timing",
                title=f"Operators differ {vals[-1] / vals[0]:.1f}× at {names.get(sid, '?')}",
                detail=f"The quickest averages {_mmss(vals[0])} a piece and the slowest "
                       f"{_mmss(vals[-1])}, at the same station. That is rarely about "
                       "effort — it is the sign that there is no standard work, so "
                       "everyone has invented their own method. Write the best one down "
                       "and teach it; it is the cheapest improvement on this list. "
                       "(One honest caveat first: if these people run different "
                       "products at this bench, the gap may be the product mix, not "
                       "the person — compare like with like before concluding.)",
                stations=[sid],
                metrics={"fastestSec": round(vals[0], 1), "slowestSec": round(vals[-1], 1)}))
            break

    return out


# ─── The report ───────────────────────────────────────────────────────────────

_ORDER = {CRITICAL: 0, WARNING: 1, INSIGHT: 2}


def _lead_findings(s: Snapshot, done: set) -> list:
    """Lead time needs only the moves. A line where nobody times the work yet
    still has one, and it is the number a visibility tool's users ask for
    first; flow efficiency adds the touch time once there is one."""
    out = []
    needs = _per_unit_need(s)
    procs = {p.id: p for p in s.processes}
    for pid, routes in _by_process(s).items():
        if pid in done:
            continue
        sl = _stream_lead(s, pid, routes, needs.get(pid, {}))
        if sl is None:
            continue
        pname = procs[pid].name if pid in procs else "this line"
        out.append(Finding(
            rule="lead-time", severity=INSIGHT, basis="flow",
            title=f"A unit crosses {pname} in {_mmss(sl['lead'])}",
            detail=("Measured from each lot's own moves, from release to finish."
                    if sl["measured"] else
                    "By Little's law: the units on the floor on average, divided by "
                    "the rate at which they leave.")
                   + " Time the work at the stations and this becomes flow "
                     "efficiency: how much of that time is work.",
            process=pid, waste="Inventory", manual="waste",
            metrics={"leadSec": round(sl["lead"], 0), "wip": round(sl["wip"], 1),
                     "wipBasis": "average" if sl["have_avg"] else "live",
                     "leadBasis": "measured" if sl["measured"] else "littles-law"}))
    return out


def analyse(s: Snapshot) -> Report:
    """Read the line and say what is wrong with it."""
    readiness, coverage = _readiness(s)
    findings = _topology_findings(s)
    if readiness != "no-data":
        findings += _timing_findings(s)
    findings += _lead_findings(s, {f.process for f in findings if f.rule == "flow-efficiency"})
    findings.sort(key=lambda f: (_ORDER.get(f.severity, 9), f.rule))

    return Report(
        readiness=readiness,
        headline=_headline(s, findings, readiness),
        narrative=_narrative(s, findings, readiness, coverage),
        findings=findings,
        coverage=coverage,
    )


def _headline(s: Snapshot, findings: list, readiness: str) -> str:
    worst = next((f for f in findings if f.severity == CRITICAL), None)
    if worst:
        return worst.title
    warn = [f for f in findings if f.severity == WARNING]
    if warn:
        return warn[0].title
    if readiness == "no-data":
        return "The shape of your line looks sound"
    if findings:
        return "Nothing is wrong — here is where to look next"
    return "This line is running cleanly"


def _narrative(s: Snapshot, findings: list, readiness: str, coverage: dict) -> list:
    """The report as prose. Written here rather than in the client so every
    surface — the panel, an export, a printout — says the same thing."""
    names = {st.id: st.name for st in s.stations}
    real = _real_routes(s)
    workers = [st for st in s.stations if not st.provider and not st.is_storage]
    paras: list = []

    shape = []
    if workers:
        shape.append(_plural(len(workers), "work station"))
    if s.processes:
        shape.append(_plural(len(s.processes), "process", "processes"))
    # Merges and splits are judged per value stream, as everywhere else: a
    # station two streams pass through is shared, not a merge, and a station
    # they leave in different directions is not a split.
    choice = {st.id for st in s.stations if st.branch_mode == "choice"}
    merge_set, split_set = set(), set()
    for routes_p in _by_process(s).values():
        inc, out_ = _degrees(routes_p)
        merge_set |= {n for n, v in inc.items() if len(v) >= 2}
        split_set |= {n for n, v in out_.items() if len(v) >= 2 and n not in choice}
    merges, splits = sorted(merge_set), sorted(split_set)
    if merges:
        shape.append(_plural(len(merges), "merge"))
    if splits:
        shape.append(_plural(len(splits), "split"))
    if shape:
        paras.append("Your line has " + _english_list(shape) + ".")

    if readiness == "no-data":
        paras.append(
            "Nobody has run a timer yet, so there is nothing to say about pace — no bottleneck, "
            "no balance, no takt. What follows comes from the shape of the line alone, which is "
            "worth reading first anyway: a problem built into the graph will not be fixed by "
            "anyone working faster.")
    elif readiness == "partial":
        paras.append(
            f"There is some timing data — {_plural(coverage['sessions'], 'work session')} "
            f"across {_plural(coverage['stationsWithTiming'], 'station')} — but not enough to "
            f"trust an average. Run the line for a while longer; past about "
            f"{_words(READY_SESSIONS)} sessions on {_words(READY_STATIONS)} stations the timing "
            "findings below become worth acting on.")

    crit = [f for f in findings if f.severity == CRITICAL]
    warn = [f for f in findings if f.severity == WARNING]
    tips = [f for f in findings if f.severity == INSIGHT]

    if crit:
        paras.append(
            f"{_plural(len(crit), 'thing').capitalize()} will stop this line from "
            "working at all, and should be fixed before anything else: "
            + "; ".join(f.title.lower() for f in crit) + ".")
    if warn:
        paras.append(
            f"{_plural(len(warn), 'problem').capitalize()} "
            f"{'is' if len(warn) == 1 else 'are'} costing you time or material every cycle: "
            + "; ".join(f.title.lower() for f in warn) + ".")
    if not crit and not warn and readiness == "ready":
        paras.append(
            "No station is starved, overloaded or piling up work, and the weights balance. "
            "That is a line running as drawn — the next gains come from changing the design "
            "rather than the execution.")
    if tips:
        paras.append(
            f"{_plural(len(tips), 'further observation').capitalize()} worth a look when "
            "the bigger items are done.")

    wastes = sorted({f.waste for f in findings if f.waste})
    if wastes:
        paras.append("In the language of the seven wastes, what shows up here is "
                     + _english_list(wastes) + ".")
    return paras


_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight",
          "nine", "ten", "eleven", "twelve"]


def _words(n: int) -> str:
    """Small counts as words, the way a person writes a sentence.

    Only COUNTS — three stations, two problems. Measurements keep their
    numerals, because "forty-one metres" and "two minutes ten seconds" are
    worse than 41 m and 2m 10s in a report somebody reads standing on a floor.
    Past twelve the numeral wins for everything.
    """
    return _WORDS[n] if 0 <= n < len(_WORDS) else f"{n:,}"


def _plural(n: int, one: str, many: str = "") -> str:
    return f"{_words(n)} {one if n == 1 else (many or one + 's')}"


def _english_list(items: list) -> str:
    """a, b and c — because a report reads aloud in a production meeting."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
