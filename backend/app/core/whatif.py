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
    co_prob: float = 0.0                            # changeover per lot
    changeovers: list = field(default_factory=list)  # seconds

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
        order = sorted(m.stations)
        # String seeds are hashed deterministically by `random` (unlike hash()),
        # so a scenario is reproducible across processes and restarts.
        self.rng = {(sid, k): random.Random(f"{seed}:{sid}:{k}")
                    for sid in order for k in ("work", "fail", "co")}
        self.rng_route = random.Random(f"{seed}:route")

    def push(self, t, kind, payload):
        self.n += 1
        heapq.heappush(self.ev, (t, self.n, kind, payload))

    def servers(self, sid):
        c = self.ch.get(sid)
        st = self.m.stations[sid]
        return (c.servers if c and c.servers else st.servers) or 1

    def service(self, sid, lot: _Lot) -> tuple[float, float]:
        st = self.m.stations[sid]
        c = self.ch.get(sid)
        rw, rf, rc = self.rng[(sid, "work")], self.rng[(sid, "fail")], self.rng[(sid, "co")]
        pool = st.rates_by.get(lot.process) or st.rates
        rate = rw.choice(pool)                           # drawn even when replaced: keeps streams aligned
        if c is not None and c.cv is not None:
            mean = statistics.fmean(pool)
            sd = c.cv / math.sqrt(max(1, lot.qty))
            s2 = math.log(1 + sd * sd)
            rate = mean * math.exp(rw.gauss(-s2 / 2, math.sqrt(s2)))
        work = lot.qty * rate * (c.speed if c is not None else 1.0)
        down = 0.0
        fails = c is None or c.breakdowns
        if fails and st.fail_rate > 0 and st.repairs:
            # failures accrue on working time: a faster process runs fewer
            # hours and so meets fewer of them
            k = _poisson(rf, st.fail_rate * work)
            down += sum(rf.choice(st.repairs) for _ in range(k))
        if st.changeovers and rc.random() < st.co_prob:
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
            asm = _Lot(qty=q, process=p, entry=entries / max(1, units), station=sid)
            if self.m.stations.get(sid) and self.m.stations[sid].worked:
                self.queue[sid].append(asm)
                self.start(t, sid)
            else:
                self.route(t, sid, asm)

    def start(self, t, sid):
        while self.queue[sid] and self.busy[sid] < self.servers(sid):
            lot = self.queue[sid].popleft()
            self.busy[sid] += 1
            work, down = self.service(sid, lot)
            self.busy_time[sid] += work
            self.down_time[sid] += down
            self.push(t + work + down, "finish", (sid, lot))

    def route(self, t, sid, lot: _Lot):
        opts = self.m.routing.get((lot.process, sid), [])
        if not opts:
            self.done.append((lot.entry, t, lot.qty))
            return
        if opts[0][2] == "piece":
            for to, w, _ in opts:
                self.arrive(t, to, _Lot(qty=max(1, int(round(lot.qty * w))), process=lot.process,
                                        entry=lot.entry, feed=sid))
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

    def run(self) -> dict:
        f = self.sc.demand or 1.0
        for a in self.m.arrivals:
            self.push(a.t / f, "arrive", (a.station, _Lot(qty=a.qty, process=a.process,
                                                          entry=a.t / f, feed=a.feed)))
        guard = 0
        while self.ev and guard < 2_000_000:
            guard += 1
            t, _, kind, payload = heapq.heappop(self.ev)
            if kind == "arrive":
                sid, lot = payload
                self.arrive(t, sid, lot)
            else:
                sid, lot = payload
                self.busy[sid] -= 1
                self.route(t, sid, lot)
                self.start(t, sid)
        units = sum(q for _, _, q in self.done)
        lead = (sum((b - a) * q for a, b, q in self.done) / units) if units else None
        span = (self.m.horizon / f) or 1.0
        # What an observer of the window would have seen: only lots finished
        # by its end. The observed lead time is censored that way, so the
        # calibration compares like with like; gains use every lot.
        seen = [(a, b, q) for a, b, q in self.done if b <= span]
        seen_units = sum(q for _, _, q in seen)
        lead_seen = (sum((b - a) * q for a, b, q in seen) / seen_units) if seen_units else None
        return {"lead_sec": lead, "units": units, "lead_seen_sec": lead_seen,
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
            m = statistics.fmean(deltas)
            h = 1.96 * statistics.stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
            row.update({"gainSec": m, "gainCi95": [m - h, m + h],
                        "gainShare": m / out["baseline"]["leadTimeSec"]
                        if out["baseline"]["leadTimeSec"] else None})
        out["scenarios"].append(row)
    seen = [b["lead_seen_sec"] for b in base_runs if b["lead_seen_sec"] is not None]
    out["calibration"] = {"observedLeadTimeSec": model.observed_lead_sec,
                          "observedUnits": model.observed_n,
                          "modelLeadTimeSec": statistics.fmean(seen) if seen else None}
    return out


def _summary(lead: list, runs: list, model: LineModel) -> dict:
    busy = defaultdict(list)
    down = defaultdict(list)
    for r in runs:
        for k in model.stations:
            busy[k].append(r["busy"].get(k, 0.0))
            down[k].append(r["down"].get(k, 0.0))
    return {"leadTimeSec": statistics.fmean(lead) if lead else None,
            "leadTimeSdSec": statistics.stdev(lead) if len(lead) > 1 else 0.0,
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
