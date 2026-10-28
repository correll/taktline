"""What if? A discrete-event model of the line, built from its own history.

The question an automation decision turns on is not "which station is slowest"
but "how much shorter does the lead time get if this station gets faster, less
variable, or stops breaking down". A snapshot map cannot answer it: it has one
stopwatch reading per process. Taktline has every session, every stoppage and
every move, so it can replay the period it observed with one thing changed and
report the difference.

The model is deliberately the line as recorded, not a line as designed:

* **Arrivals are replayed**, not fitted: every lot that left an entry station
  in the window enters the model at the same moment, with the same quantity.
  The release rhythm, the batches and the gaps are the real ones.
* **Work times are resampled** from the station's own sessions (seconds per
  unit, sessions closed by the operator or by the lot leaving; a session closed
  only by the next Start is not a reading).
* **Breakdowns and changeovers** come from recorded stoppages: breakdowns as a
  rate per working second with the recorded repair times, changeovers as a
  probability per lot with the recorded durations. A station that is never
  paused never breaks down in the model, which is the honest reading of what
  it was told.
* **Routing** follows the process graph: a single route is followed, a choice
  is taken in the proportions the moves show, a split mints its pieces, and a
  merge assembles matched sets in the lot size it was seen to make.
* **Time is open time**. Every station shares the work-hours calendar, so the
  model runs on a clock that only ticks while the plant is open; lead times
  are in open hours.

Its idealisations are first-in-first-out queues, unlimited buffers, stations
staffed independently of each other at a constant number of servers, and
breakdowns that accrue with work. Each can be replaced where the record shows
the line works otherwise (`Assumptions`): a station holding at most so many
lots (the station feeding it then blocks), stations sharing operators,
breakdowns that accrue on open hours, idle or not, and staffing that changes
over the day. None is on unless asked for, and with none the model is exactly
the one described above.

Every scenario is compared with a baseline run of the same model on the same
random numbers (one stream per station and purpose), so the difference
reflects the change rather than the dice. The baseline's own lead time is
reported next to the observed one, so a reader can see how well the model
reproduces the line before trusting what it says about a change.

Pure: no database. `core/whatif_data.py` builds the inputs.
"""
from __future__ import annotations

import heapq
import math
import random
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StationModel:
    id: str
    name: str
    rates: list = field(default_factory=list)       # seconds per unit, one per lot worked
    # The same samples by value stream. A shared station does different work
    # for different products (a paint booth: 300 s a widget, 150 s a bracket),
    # and drawing a bracket's time for a widget lot is a different line.
    rates_by: dict = field(default_factory=dict)
    servers: int = 1
    fail_rate: float = 0.0                          # breakdowns per working second
    repairs: list = field(default_factory=list)     # seconds
    co_prob: float = 0.0                            # changeover per lot (or per product change)
    changeovers: list = field(default_factory=list)  # seconds
    # A changeover happens when the product changes, not at random: with
    # co_on_change, co_prob is the chance of one at a change of product.
    co_on_change: bool = False

    @property
    def worked(self) -> bool:
        return bool(self.rates)


@dataclass
class ArrivalIn:
    t: float            # open seconds from the start of the window
    qty: int
    process: str
    station: str        # where the lot goes first (downstream of an entry station)
    feed: str = ""      # the entry station it left
    product: str = ""   # what it is, for changeovers at a change of product


@dataclass
class Assumptions:
    """Where the line works otherwise than the model's idealisations. Empty
    means none of them is replaced."""
    # station -> most lots it holds at once (waiting and in work); a station
    # whose finished lot is bound there keeps it, and its server, until room
    buffers: dict = field(default_factory=dict)
    # groups of stations worked by one crew: (stations, operators); a lot
    # starts only while the group has an operator free
    shared: list = field(default_factory=list)
    # station -> breakdowns per OPEN second: failures accrue on the calendar,
    # idle time included, and a repair holds the station whether or not a lot
    # is on it
    open_failures: dict = field(default_factory=dict)
    # station -> [(open second from the window start, servers), ...]: the
    # crew changes over the day (a shift, a team, a lunch)
    staffing: dict = field(default_factory=dict)

    def any(self) -> bool:
        return bool(self.buffers or self.shared or self.open_failures or self.staffing)


@dataclass
class LineModel:
    stations: dict                                   # id -> StationModel
    # (process, station) -> list of (to, probability, kind) where kind is
    # 'move' (whole lot), 'piece' (a split branch: qty * weight pieces)
    routing: dict
    # (process, station) -> {feed station: units consumed per assembly}
    merges: dict
    merge_lot: dict                                  # (process, station) -> assemblies per merge
    endpoints: set                                   # (process, station) where a lot is finished
    arrivals: list
    horizon: float                                   # open seconds in the window
    observed_lead_sec: Optional[float] = None
    observed_n: int = 0
    # process -> (observed mean lead time in open seconds, units)
    observed_by_process: dict = field(default_factory=dict)
    assumptions: Assumptions = field(default_factory=Assumptions)
    # what the record says about the idealisations (core/whatif_record.py);
    # read by whoever decides which to replace, never by the simulation
    record: dict = field(default_factory=dict)


@dataclass
class Change:
    station: str
    speed: float = 1.0            # multiplies work time (0.75 = 25% faster)
    cv: Optional[float] = None    # piece-time CV of the new process (None: as measured)
    breakdowns: bool = True       # False: the new process does not break down
    changeovers: bool = True      # False: changeovers eliminated (SMED)
    servers: Optional[int] = None


@dataclass
class Scenario:
    name: str
    changes: list = field(default_factory=list)
    demand: float = 1.0           # 1.1 = the same work arriving 10% faster


@dataclass
class _Lot:
    qty: int
    process: str
    entry: float
    station: str = ""
    feed: str = ""
    product: str = ""
    queued: float = 0.0


class _Sim:
    def __init__(self, m: LineModel, sc: Scenario, seed: int):
        self.m, self.sc = m, sc
        self.ch = {c.station: c for c in sc.changes}
        self.ev: list = []
        self.n = 0
        self.queue = defaultdict(deque)
        self.busy = defaultdict(int)
        self.busy_time = defaultdict(float)
        self.down_time = defaultdict(float)
        self.feeds = defaultdict(lambda: defaultdict(deque))   # (p, merge) -> feed -> lots
        self.done: list = []
        self.last_product: dict = {}
        order = sorted(m.stations)
        # String seeds are hashed deterministically by `random` (unlike hash()),
        # so a scenario is reproducible across processes and restarts.
        self.rng = {(sid, k): random.Random(f"{seed}:{sid}:{k}")
                    for sid in order for k in ("work", "fail", "co")}
        self.rng_route = random.Random(f"{seed}:route")
        a = m.assumptions
        self.A = a if a.any() else None
        if self.A is not None:
            self.group_of = {}
            self.group_cap, self.group_busy = [], []
            for g, (members, ops) in enumerate(a.shared):
                for sid in members:
                    self.group_of[sid] = g
                self.group_cap.append(max(1, int(ops)))
                self.group_busy.append(0)
            self.blocked = defaultdict(deque)        # station -> [(source, lot)] waiting for room
            self.held = defaultdict(int)             # station -> servers holding a blocked lot
            # open-clock failures, drawn lazily in time order from the
            # station's own stream so baseline and scenario meet the same ones
            self.next_fail, self.down_until = {}, defaultdict(float)
            for sid, lam in a.open_failures.items():
                if lam > 0 and sid in m.stations and m.stations[sid].repairs:
                    self.next_fail[sid] = self.rng[(sid, "fail")].expovariate(lam)

    def push(self, t, kind, payload):
        self.n += 1
        heapq.heappush(self.ev, (t, self.n, kind, payload))

    def servers(self, sid, t=None):
        c = self.ch.get(sid)
        st = self.m.stations[sid]
        if self.A is not None and sid in self.A.staffing and t is not None:
            base = st.servers
            for t0, n in self.A.staffing[sid]:
                if t0 <= t:
                    base = n
                else:
                    break
            extra = (c.servers - st.servers) if c and c.servers else 0
            return max(0, base + extra)
        return (c.servers if c and c.servers else st.servers) or 1

    def _failures_until(self, sid, t):
        """Open-clock breakdowns up to time t: each holds the station for its
        repair, starting when it occurs or when the previous repair ends."""
        lam = self.A.open_failures.get(sid, 0.0)
        rf = self.rng[(sid, "fail")]
        st = self.m.stations[sid]
        while sid in self.next_fail and self.next_fail[sid] <= t:
            f = self.next_fail[sid]
            rep = rf.choice(st.repairs)
            self.down_until[sid] = max(self.down_until[sid], f) + rep
            self.down_time[sid] += rep
            self.next_fail[sid] = self.down_until[sid] + rf.expovariate(lam)

    def service(self, sid, lot: _Lot) -> tuple[float, float]:
        st = self.m.stations[sid]
        c = self.ch.get(sid)
        rw, rf, rc = self.rng[(sid, "work")], self.rng[(sid, "fail")], self.rng[(sid, "co")]
        # A stream's own samples when there are enough of them to be a
        # distribution rather than an anecdote; the station's pool otherwise.
        own = st.rates_by.get(lot.process)
        pool = own if own and len(own) >= max(5, 0.2 * len(st.rates) / max(1, len(st.rates_by))) else st.rates
        rate = rw.choice(pool)                           # drawn even when replaced: keeps streams aligned
        if c is not None and c.cv is not None:
            mean = statistics.fmean(pool)
            sd = c.cv / math.sqrt(max(1, lot.qty))
            s2 = math.log(1 + sd * sd)
            rate = mean * math.exp(rw.gauss(-s2 / 2, math.sqrt(s2)))
        work = lot.qty * rate * (c.speed if c is not None else 1.0)
        down = 0.0
        fails = c is None or c.breakdowns
        if self.A is not None and sid in self.A.open_failures:
            pass                                       # accrued on the calendar, in start()
        elif fails and st.fail_rate > 0 and st.repairs:
            # failures accrue on working time: a faster process runs fewer
            # hours and so meets fewer of them
            k = _poisson(rf, st.fail_rate * work)
            down += sum(rf.choice(st.repairs) for _ in range(k))
        if st.co_on_change:
            prev = self.last_product.get(sid)
            self.last_product[sid] = lot.product
            draw = rc.random()                       # drawn every lot: keeps streams aligned
            changed = prev is not None and lot.product != prev
            if st.changeovers and changed and draw < st.co_prob:
                co = rc.choice(st.changeovers)
                if c is None or c.changeovers:
                    down += co
        elif st.changeovers and rc.random() < st.co_prob:
            co = rc.choice(st.changeovers)
            if c is None or c.changeovers:
                down += co
        return work, down

    def arrive(self, t, sid, lot: _Lot):
        p = lot.process
        if (p, sid) in self.m.endpoints:
            self.done.append((lot.entry, t, lot.qty))
            return
        if (p, sid) in self.m.merges:
            self.feeds[(p, sid)][lot.feed].append(lot)
            self.try_merge(t, p, sid)
            return
        if not self.m.stations.get(sid) or not self.m.stations[sid].worked:
            self.route(t, sid, lot)                     # a pass-through: nothing is done here
            return
        lot.queued = t
        self.queue[sid].append(lot)
        self.start(t, sid)

    def try_merge(self, t, p, sid):
        need = self.m.merges[(p, sid)]
        q = self.m.merge_lot.get((p, sid), 1)
        buf = self.feeds[(p, sid)]
        while all(sum(l.qty for l in buf[f]) >= w * q for f, w in need.items()):
            entries, units = 0.0, 0
            for f, w in need.items():
                want = w * q
                while want > 0:
                    head = buf[f][0]
                    take = min(head.qty, want)
                    entries += head.entry * take
                    units += take
                    head.qty -= take
                    want -= take
                    if head.qty == 0:
                        buf[f].popleft()
            asm = _Lot(qty=q, process=p, entry=entries / max(1, units), station=sid,
                       product=f"assembly:{p}:{sid}")
            if self.m.stations.get(sid) and self.m.stations[sid].worked:
                asm.queued = t
                self.queue[sid].append(asm)
                self.start(t, sid)
            else:
                self.route(t, sid, asm)

    def start(self, t, sid):
        if self.A is not None:
            return self._start_a(t, sid)
        while self.queue[sid] and self.busy[sid] < self.servers(sid):
            lot = self.queue[sid].popleft()
            self.busy[sid] += 1
            work, down = self.service(sid, lot)
            self.busy_time[sid] += work
            self.down_time[sid] += down
            self.push(t + work + down, "finish", (sid, lot))

    def _open_clock_service(self, sid, t, work) -> float:
        """Time beyond the work itself for a lot started at t on a station
        whose breakdowns accrue on open hours: any repair under way when it
        arrives, and every breakdown that strikes while it is worked. (With
        several servers the station is treated as one machine: a breakdown
        holds all of them.)"""
        self._failures_until(sid, t)
        begin = max(t, self.down_until[sid])
        end = begin + work
        lam = self.A.open_failures[sid]
        rf = self.rng[(sid, "fail")]
        st = self.m.stations[sid]
        while self.next_fail.get(sid, math.inf) <= end:
            f = self.next_fail[sid]
            rep = rf.choice(st.repairs)
            end += rep
            self.down_time[sid] += rep
            self.down_until[sid] = max(self.down_until[sid], f) + rep
            self.next_fail[sid] = self.down_until[sid] + rf.expovariate(lam)
        return end - t - work

    def _can_start(self, t, sid):
        if not self.queue[sid] or self.busy[sid] >= self.servers(sid, t):
            return False
        g = self.group_of.get(sid)
        return g is None or self.group_busy[g] < self.group_cap[g]

    def _start_a(self, t, sid):
        g = self.group_of.get(sid)
        members = [x for x in self.A.shared[g][0] if x in self.m.stations] if g is not None else [sid]
        while True:
            ready = [x for x in members if self._can_start(t, x)]
            if not ready:
                return
            # one crew, first come first served across its stations
            x = min(ready, key=lambda y: (self.queue[y][0].queued, y))
            lot = self.queue[x].popleft()
            self.busy[x] += 1
            if g is not None:
                self.group_busy[g] += 1
            work, down = self.service(x, lot)     # down: changeovers (and work-clock failures)
            self.down_time[x] += down                 # open-clock repairs are counted as they occur
            if x in self.A.open_failures and x in self.next_fail \
                    and (self.ch.get(x) is None or self.ch[x].breakdowns):
                # a breakdown can strike during a changeover as well as the work
                down += self._open_clock_service(x, t, work + down)
            self.busy_time[x] += work
            self.push(t + work + down, "finish", (x, lot))

    def route(self, t, sid, lot: _Lot):
        opts = self.m.routing.get((lot.process, sid), [])
        if not opts:
            self.done.append((lot.entry, t, lot.qty))
            return
        if opts[0][2] == "piece":
            for to, w, _ in opts:
                self.arrive(t, to, _Lot(qty=max(1, int(round(lot.qty * w))), process=lot.process,
                                        entry=lot.entry, feed=sid, product=lot.product))
            return
        x = self.rng_route.random()
        acc = 0.0
        to = opts[-1][0]
        for cand, prob, _ in opts:
            acc += prob
            if x <= acc:
                to = cand
                break
        lot.feed = sid
        self.arrive(t, to, lot)

    def _bound_for(self, sid, lot):
        """The one station a finished whole lot goes to next, when that
        station holds a limited number of lots; None otherwise."""
        opts = self.m.routing.get((lot.process, sid), [])
        if not opts or opts[0][2] == "piece" or len(opts) != 1:
            return None
        to = opts[0][0]
        if to not in self.A.buffers or (lot.process, to) in self.m.merges \
                or (lot.process, to) in self.m.endpoints:
            return None
        return to

    def _occupied(self, sid):
        return len(self.queue[sid]) + self.busy[sid]

    def _release(self, t, sid):
        """A server at sid lets go of its lot: room may open at sid for a lot
        blocked upstream, and the crew may start the next one."""
        self.busy[sid] -= 1
        g = self.group_of.get(sid)
        if g is not None:
            self.group_busy[g] -= 1
        if self.blocked[sid] and self._occupied(sid) < self.A.buffers.get(sid, math.inf):
            src, lot = self.blocked[sid].popleft()
            lot.feed = src
            self.arrive(t, sid, lot)
            self._release(t, src)
        self.start(t, sid)

    def _finish_a(self, t, sid, lot):
        to = self._bound_for(sid, lot)
        if to is not None and self._occupied(to) >= self.A.buffers[to]:
            self.blocked[to].append((sid, lot))          # keeps the lot and the server
            return
        if to is not None:
            lot.feed = sid
            self.arrive(t, to, lot)
            self._release(t, sid)
            return
        self.route(t, sid, lot)
        self._release(t, sid)

    def run(self) -> dict:
        f = self.sc.demand or 1.0
        for a in self.m.arrivals:
            self.push(a.t / f, "arrive", (a.station, _Lot(qty=a.qty, process=a.process,
                                                          entry=a.t / f, feed=a.feed,
                                                          product=a.product)))
        if self.A is not None:
            for sid, sched in self.A.staffing.items():
                for t0, _n in sched:
                    if sid in self.m.stations:
                        self.push(t0, "staff", sid)
        guard = 0
        while self.ev and guard < 2_000_000:
            guard += 1
            t, _, kind, payload = heapq.heappop(self.ev)
            if kind == "arrive":
                sid, lot = payload
                self.arrive(t, sid, lot)
            elif kind == "staff":
                self.start(t, payload)
            elif self.A is None:
                sid, lot = payload
                self.busy[sid] -= 1
                self.route(t, sid, lot)
                self.start(t, sid)
            else:
                self._finish_a(t, *payload)
        units = sum(q for _, _, q in self.done)
        lead = (sum((b - a) * q for a, b, q in self.done) / units) if units else None
        span = (self.m.horizon / f) or 1.0
        # What an observer of the window would have seen: only lots finished
        # by its end. The observed lead time is censored that way, so the
        # calibration compares like with like; gains use every lot.
        seen = [(a, b, q) for a, b, q in self.done if b <= span]
        seen_units = sum(q for _, _, q in seen)
        lead_seen = (sum((b - a) * q for a, b, q in seen) / seen_units) if seen_units else None
        # The spread of individual units' lead times (unit-weighted standard
        # deviation and 90th percentile): what a customer waiting for one
        # order feels, and what a change in variability moves even when the
        # mean barely does. And work in process, by Little's law: the units
        # in the system, averaged over the period the lots were in it.
        spread = p90 = wip = None
        if units:
            sq = sum(((b - a) - lead) ** 2 * q for a, b, q in self.done)
            spread = math.sqrt(sq / units)
            flat = sorted((b - a, q) for a, b, q in self.done)
            acc, cut = 0, 0.9 * units
            for d, q in flat:
                acc += q
                if acc >= cut:
                    p90 = d
                    break
            end = max(span, max(b for _, b, _ in self.done))
            wip = sum((b - a) * q for a, b, q in self.done) / end
        return {"lead_sec": lead, "units": units, "lead_seen_sec": lead_seen,
                "spread_sec": spread, "p90_sec": p90, "wip": wip,
                "busy": {k: v / span for k, v in self.busy_time.items()},
                "down": {k: v / span for k, v in self.down_time.items()}}


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    k, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def run(model: LineModel, scenarios: list, replications: int = 20, seed: int = 1) -> dict:
    """Baseline and every scenario, on common random numbers, with the paired
    difference in mean lead time and a 95% interval across replications."""
    base_runs = [_Sim(model, Scenario("baseline"), seed + r).run() for r in range(replications)]
    base_lead = [b["lead_sec"] for b in base_runs if b["lead_sec"] is not None]
    out = {"baseline": _summary(base_lead, base_runs, model), "scenarios": []}
    for sc in scenarios:
        runs = [_Sim(model, sc, seed + r).run() for r in range(replications)]
        deltas = [b["lead_sec"] - s["lead_sec"] for b, s in zip(base_runs, runs)
                  if b["lead_sec"] is not None and s["lead_sec"] is not None]
        lead = [s["lead_sec"] for s in runs if s["lead_sec"] is not None]
        row = {"name": sc.name, **_summary(lead, runs, model)}
        if deltas:
            m, lo, hi = _mean_ci(deltas)
            row.update({"gainSec": m, "gainCi95": [lo, hi],
                        "gainShare": m / out["baseline"]["leadTimeSec"]
                        if out["baseline"]["leadTimeSec"] else None})
        for key, out_key in (("wip", "wipReduction"), ("spread_sec", "spreadReductionSec"),
                             ("p90_sec", "p90ReductionSec")):
            d = [b[key] - s_[key] for b, s_ in zip(base_runs, runs)
                 if b.get(key) is not None and s_.get(key) is not None]
            if d:
                m, lo, hi = _mean_ci(d)
                row[out_key] = m
                row[out_key + "Ci95"] = [lo, hi]
        out["scenarios"].append(row)
    seen = [b["lead_seen_sec"] for b in base_runs if b["lead_seen_sec"] is not None]
    out["calibration"] = {"observedLeadTimeSec": model.observed_lead_sec,
                          "observedUnits": model.observed_n,
                          "modelLeadTimeSec": statistics.fmean(seen) if seen else None}
    return out


def _mean_ci(xs: list) -> tuple:
    m = statistics.fmean(xs)
    h = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
    return m, m - h, m + h


def _summary(lead: list, runs: list, model: LineModel) -> dict:
    busy = defaultdict(list)
    down = defaultdict(list)
    for r in runs:
        for k in model.stations:
            busy[k].append(r["busy"].get(k, 0.0))
            down[k].append(r["down"].get(k, 0.0))
    mean = lambda key: (statistics.fmean([r[key] for r in runs if r.get(key) is not None])
                        if any(r.get(key) is not None for r in runs) else None)
    return {"leadTimeSec": statistics.fmean(lead) if lead else None,
            "leadTimeSdSec": statistics.stdev(lead) if len(lead) > 1 else 0.0,
            "leadSpreadSec": mean("spread_sec"), "leadP90Sec": mean("p90_sec"),
            "wip": mean("wip"),
            "stations": {k: {"busy": statistics.fmean(busy[k]), "down": statistics.fmean(down[k])}
                         for k in model.stations if model.stations[k].worked}}


def automation_candidates(model: LineModel, speed: float = 0.75, cv: Optional[float] = 0.05,
                          breakdowns: bool = True, replications: int = 20, seed: int = 1) -> dict:
    """The same robot tried at every station that is worked by hand, ranked by
    how much shorter it makes the lead time."""
    # Only stations the modelled flow passes through: an entry station's own
    # work happens before a lot enters the model, so a machine there would
    # show no gain for a reason that has nothing to do with the machine.
    reached = {a.station for a in model.arrivals}
    for opts in model.routing.values():
        reached |= {to for to, _, _ in opts}
    scen = [Scenario(name=sid, changes=[Change(station=sid, speed=speed, cv=cv,
                                               breakdowns=breakdowns)])
            for sid, st in sorted(model.stations.items()) if st.worked and sid in reached]
    res = run(model, scen, replications, seed)
    res["scenarios"].sort(key=lambda r: -(r.get("gainSec") or 0))
    return res
