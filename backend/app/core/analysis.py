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


@dataclass
class Snapshot:
    stations: list
    routes: list
    processes: list
    templates: list
    wip: dict                       # stationId → units standing there now
    metrics: dict                   # stationId → StationMetrics
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

        need: dict = {}
        for n in reversed(_topo(routes, nodes)):
            branch = outs[n]
            if not branch:
                need[n] = 1                     # a sink: one per cycle
                continue
            per = [math.ceil(consumes(r) * need.get(r.unload, 1) / produces(r)) for r in branch]
            if n in choice and len(branch) >= 2:
                # Each unit goes down exactly one branch, so the demands of the
                # branches that PULL add up — a branch to storage pulls nothing.
                need[n] = max(1, sum(p for r, p in zip(branch, per)
                                     if r.unload not in storage))
            else:
                need[n] = max([1] + per)

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
                d, r = max(far)
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


def _timing_findings(s: Snapshot) -> list:
    names = {st.id: st.name for st in s.stations}
    procs = {p.id: p for p in s.processes}
    worked = _worked(s)
    out: list = []
    if not worked:
        return out

    # Where work ENTERS the line. A station nothing feeds does not set its own
    # exit rate — releases do. Calling it the constraint is the commonest way
    # to misread a line: it sends people to speed up the one station whose
    # pace is not theirs to change, when the line is simply waiting for orders.
    incoming, _out = _degrees(_real_routes(s))
    entries = {st.id for st in s.stations
               if not incoming.get(st.id) and not st.provider and not st.is_storage}

    # ── The constraint. Everything else on a line is subordinate to it: an
    #    hour saved anywhere else is not an hour gained.
    all_exits = {sid: m.line_cycle_sec for sid, m in worked.items() if m.line_cycle_sec}
    exits = {sid: v for sid, v in all_exits.items() if sid not in entries}

    # The line is fed more slowly than it can work: every bench is quicker than
    # the material arriving. That is not a bottleneck to attack, it is capacity
    # nobody is paying for — and the answer is the opposite of the usual one.
    if len(all_exits) >= 3 and exits:
        feeder = max(all_exits, key=lambda k: all_exits[k])
        if feeder in entries:
            downstream = statistics.median(exits.values())
            if downstream and all_exits[feeder] > 1.3 * downstream:
                out.append(Finding(
                    rule="demand-limited", severity=INSIGHT, basis="timing",
                    title=f"The line is faster than the work arriving at "
                          f"{names.get(feeder, 'the front')}",
                    detail=f"A piece enters at {names.get(feeder, 'the first station')} every "
                           f"{_mmss(all_exits[feeder])}, while the stations downstream turn one "
                           f"round every {_mmss(downstream)}. Nothing here is a bottleneck — the "
                           "line is over-dimensioned for the orders it is getting, and the idle "
                           "capacity is paid for either way. Rather than speeding anything up, "
                           "consider combining steps so that fewer stations each do more: a "
                           "longer cycle time at fewer benches, matched to the rate work actually "
                           "arrives, frees people and floor without slowing anything down.",
                    stations=[feeder], waste="Waiting", manual="timing",
                    metrics={"entrySec": round(all_exits[feeder], 1),
                             "downstreamSec": round(downstream, 1)}))

    if len(exits) >= 2:
        slowest = max(exits, key=lambda k: exits[k])
        rest = sorted(v for k, v in exits.items() if k != slowest)
        typical = statistics.median(rest) if rest else 0
        if typical and exits[slowest] > 1.3 * typical:
            out.append(Finding(
                rule="bottleneck", severity=WARNING, basis="timing",
                title=f"{names.get(slowest, '?')} is the constraint",
                detail=f"A piece leaves {names.get(slowest, 'it')} every "
                       f"{_mmss(exits[slowest])}, against {_mmss(typical)} elsewhere. That is the "
                       "rate of the whole line, whatever the other stations manage — time saved "
                       "anywhere else is not time gained. Improve here first, and only here, "
                       "until something else becomes the slowest.",
                stations=[slowest], manual="timing",
                metrics={"lineCycleSec": round(exits[slowest], 1),
                         "typicalSec": round(typical, 1)}))

    # ── The gap between doing the work and the work leaving. The manual's own
    #    framing: that difference is where the waste lives.
    for sid, m in sorted(worked.items(), key=lambda kv: -(kv[1].line_cycle_sec or 0)):
        if not m.line_cycle_sec or not m.cycle_sec:
            continue
        if m.line_cycle_sec > 1.5 * m.cycle_sec:
            gap = m.line_cycle_sec - m.cycle_sec
            out.append(Finding(
                rule="waiting-gap", severity=WARNING, basis="timing",
                title=f"{names.get(sid, '?')} spends {_mmss(gap)} per piece not working",
                detail=f"The work takes {_mmss(m.cycle_sec)}, but a piece only leaves every "
                       f"{_mmss(m.line_cycle_sec)}. The other {_mmss(gap)} is queueing, blocking "
                       "or transport — not operator pace. A faster machine here buys nothing; "
                       "the queue in front of it is the thing to remove.",
                stations=[sid], waste="Waiting", manual="timing",
                metrics={"cycleSec": round(m.cycle_sec, 1),
                         "lineCycleSec": round(m.line_cycle_sec, 1),
                         "gapSec": round(gap, 1)}))
            break                    # name the worst one; a list of six is noise

    # ── Against the beat the customer sets.
    for pid, p in procs.items():
        if not p.desired_takt_sec:
            continue
        over = [(sid, m.cycle_sec) for sid, m in worked.items()
                if m.cycle_sec and m.cycle_sec > p.desired_takt_sec]
        if over:
            worst = max(over, key=lambda t: t[1])
            out.append(Finding(
                rule="over-takt", severity=CRITICAL, basis="timing",
                title=f"{names.get(worst[0], '?')} cannot hold the takt for {p.name}",
                detail=f"Takt is {_mmss(p.desired_takt_sec)} — one unit must leave that often to "
                       f"meet demand — but the work at {names.get(worst[0], 'this station')} takes "
                       f"{_mmss(worst[1])} per piece. A station whose cycle time exceeds takt "
                       "cannot keep up however well it is run: it needs another operator, another "
                       "machine, or less work in the step.",
                stations=[sid for sid, _ in over], process=pid,
                waste="Waiting", manual="timing",
                metrics={"taktSec": p.desired_takt_sec, "cycleSec": round(worst[1], 1),
                         "stationsOverTakt": len(over)}))

    # ── Balance. A line is balanced when every station's cycle time is close.
    cycles = {sid: m.cycle_sec for sid, m in worked.items() if m.cycle_sec}
    if len(cycles) >= 3:
        fastest = min(cycles, key=lambda k: cycles[k])
        slowest = max(cycles, key=lambda k: cycles[k])
        ratio = cycles[slowest] / cycles[fastest] if cycles[fastest] else 0
        if ratio >= 2:
            out.append(Finding(
                rule="line-imbalance", severity=WARNING, basis="timing",
                title=f"The line is unbalanced — {ratio:.1f}× between fastest and slowest",
                detail=f"{names.get(slowest, '?')} takes {_mmss(cycles[slowest])} a piece while "
                       f"{names.get(fastest, '?')} takes {_mmss(cycles[fastest])}. Everyone paces "
                       "to the slowest step, so the fast stations are waiting — that idle time is "
                       "paid for whether or not it appears anywhere. Moving work from the slow "
                       "step to the fast one costs nothing and raises the whole line.",
                stations=[slowest, fastest], waste="Waiting", manual="timing",
                metrics={"ratio": round(ratio, 2),
                         "slowestSec": round(cycles[slowest], 1),
                         "fastestSec": round(cycles[fastest], 1)}))

    # ── Where the work-in-process actually is, right now.
    # Count only what is standing on the FLOOR. Gating on total WIP instead let
    # a full warehouse open the question and then answer it about the two units
    # actually in production — "50% of your work in process is at Cut", where
    # Cut holds one shirt.
    shelves = {st.id for st in s.stations if st.is_storage}
    floor = {sid: n for sid, n in s.wip.items() if sid not in shelves and n > 0}
    if sum(floor.values()) >= 8:
        if floor:
            worst = max(floor, key=lambda k: floor[k])
            share = floor[worst] / max(1, sum(floor.values()))
            if share >= 0.4 and len(floor) >= 2:
                out.append(Finding(
                    rule="wip-concentration", severity=WARNING, basis="timing",
                    title=f"{int(share * 100)}% of the work in process is at "
                          f"{names.get(worst, '?')}",
                    detail=f"{_words(floor[worst])} of {_words(sum(floor.values()))} units on the "
                           "floor are "
                           f"waiting at {names.get(worst, 'one station')}. WIP piling up in front "
                           "of a station is the signature of a bottleneck, and by Little's law it "
                           "is also lead time: halve the queue and you halve how long an order "
                           "takes to cross the shop.",
                    stations=[worst], waste="Inventory", manual="waste",
                    metrics={"units": floor[worst], "floorUnits": sum(floor.values()),
                             "share": round(share, 2)}))

    # ── Repeatability. Mura — unevenness — is the waste that hides the others.
    for sid, m in worked.items():
        if len(m.samples) < 6:
            continue
        mean = statistics.fmean(m.samples)
        if mean <= 0:
            continue
        cv = statistics.pstdev(m.samples) / mean
        if cv >= 0.6:
            out.append(Finding(
                rule="uneven-work", severity=INSIGHT, basis="timing",
                title=f"The work at {names.get(sid, '?')} is not repeatable",
                detail=f"Cycle times there range from {_mmss(min(m.samples))} to "
                       f"{_mmss(max(m.samples))} around a mean of {_mmss(mean)}. That spread is "
                       "unevenness, and it is the waste that hides the others: you cannot see a "
                       "bottleneck, judge a takt or trust an average until the same job takes "
                       "about the same time twice. Usually it means the step is really several "
                       "different jobs, or that there is no standard way of doing it.",
                stations=[sid],
                metrics={"cv": round(cv, 2), "meanSec": round(mean, 1),
                         "minSec": round(min(m.samples), 1), "maxSec": round(max(m.samples), 1)}))
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
                       f"{_mmss(vals[-1])}, at the same station. That is rarely about effort — it "
                       "is the sign that there is no standard work, so everyone has invented their "
                       "own method. Write down the best one and teach it; it is the cheapest "
                       "improvement on this list.",
                stations=[sid],
                metrics={"fastestSec": round(vals[0], 1), "slowestSec": round(vals[-1], 1)}))
            break

    # ── A station idle while the line is busy is starved, not lazy.
    oees = {sid: m.oee for sid, m in worked.items() if m.oee is not None}
    if len(oees) >= 3:
        median = statistics.median(oees.values())
        low = min(oees, key=lambda k: oees[k])
        if median > 0.25 and oees[low] < median / 2:
            out.append(Finding(
                rule="starved-station", severity=INSIGHT, basis="timing",
                title=f"{names.get(low, '?')} is idle most of the time",
                detail=f"It runs {oees[low] * 100:.0f}% of open hours against a line median of "
                       f"{median * 100:.0f}%. A station that is idle while the rest of the line is "
                       "busy is usually starved by something upstream rather than slow itself — "
                       "look at what feeds it before adding capacity here.",
                stations=[low], waste="Waiting", manual="statistics",
                metrics={"oee": round(oees[low], 3), "medianOee": round(median, 3)}))
    return out


# ─── The report ───────────────────────────────────────────────────────────────

_ORDER = {CRITICAL: 0, WARNING: 1, INSIGHT: 2}


def analyse(s: Snapshot) -> Report:
    """Read the line and say what is wrong with it."""
    readiness, coverage = _readiness(s)
    findings = _topology_findings(s)
    if readiness != "no-data":
        findings += _timing_findings(s)
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
    incoming, outgoing = _degrees(real)
    merges = [n for n in outgoing.keys() | incoming.keys() if len(incoming.get(n, ())) >= 2]
    splits = [n for n in outgoing.keys() | incoming.keys() if len(outgoing.get(n, ())) >= 2]
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
