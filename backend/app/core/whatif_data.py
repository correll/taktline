"""Build the what-if model (`core/whatif.py`) from what the line recorded.

Everything comes from the company's own history in a window: sessions for
work times, stoppages for breakdowns and changeovers, lot events for arrivals,
routing proportions and merge lot sizes, and the process graph for where lots
may go. The observed lead time is computed from the same events, so the model
can be checked against the line before it is asked about a change.
"""
from __future__ import annotations

import bisect
import statistics
from collections import defaultdict, deque
from datetime import datetime

from sqlalchemy import select

from ..db.tables import (
    CardEvent as CardEventRow, Route as RouteRow, Station as StationRow,
    Stoppage as StoppageRow, WorkSession as SessionRow,
)
from .schedule import open_intervals
from .whatif import ArrivalIn, LineModel, StationModel


class OpenClock:
    """Wall time -> open seconds since the start of the window."""

    def __init__(self, intervals: list):
        self.starts = [a for a, _ in intervals]
        self.ivs = intervals
        self.cum = []
        acc = 0.0
        for a, b in intervals:
            self.cum.append(acc)
            acc += (b - a).total_seconds()
        self.total = acc

    def __call__(self, t: datetime) -> float:
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0:
            return 0.0
        a, b = self.ivs[i]
        return self.cum[i] + (min(t, b) - a).total_seconds()


def _max_concurrency(intervals: list) -> int:
    pts = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
    cur = best = 0
    for _, d in pts:
        cur += d
        best = max(best, cur)
    return best


async def build_model(session, company_id, since: datetime, until: datetime,
                      schedule, tzname) -> tuple[LineModel, dict]:
    """The model, and station names for presenting its answers."""
    stations = (await session.execute(
        select(StationRow).where(StationRow.companyId == company_id))).scalars().all()
    partners = {str(s.id) for s in stations if s.integrationProvider}
    storage = {str(s.id) for s in stations if s.isStorage}
    choice = {str(s.id) for s in stations if s.branchMode == "choice"}
    names = {str(s.id): s.name for s in stations}
    routes = [r for r in (await session.execute(
        select(RouteRow).where(RouteRow.companyId == company_id))).scalars().all()
        if str(r.load) not in partners and str(r.unload) not in partners]

    # ── the record: lot events, stoppages, sessions ──
    events = (await session.execute(
        select(CardEventRow).where(CardEventRow.companyId == company_id,
                                   CardEventRow.timestamp >= since,
                                   CardEventRow.timestamp <= until)
        .order_by(CardEventRow.timestamp.asc())
    )).scalars().all()
    # The model's period is the one the record covers: from the first event
    # in the window, not the window's nominal start, or averages over it
    # (WIP, utilisation) are diluted by days nothing was recorded.
    if events:
        since = max(since, events[0].timestamp)
    clock = OpenClock(open_intervals(since, until, schedule, tzname))
    stops = (await session.execute(
        select(StoppageRow).where(StoppageRow.companyId == company_id,
                                  StoppageRow.endedAt.isnot(None),
                                  StoppageRow.startedAt >= since, StoppageRow.startedAt <= until)
    )).scalars().all()
    work = (await session.execute(
        select(SessionRow).where(SessionRow.companyId == company_id,
                                 SessionRow.endedAt.isnot(None),
                                 SessionRow.endedAt >= since, SessionRow.startedAt <= until)
    )).scalars().all()

    def open_span(a_, b_):
        return max(0.0, clock(min(b_, until)) - clock(max(a_, since)))

    # Stoppages in OPEN time: a changeover begun at 21:58 and ended the next
    # morning was eight hours on the wall clock and two minutes of the
    # plant's time. Sampled as wall time it stalls the model's station
    # overnight, and a station near its capacity never recovers.
    repairs, cos = defaultdict(list), defaultdict(list)
    paused_open = defaultdict(float)
    for st in stops:
        d = open_span(st.startedAt, st.endedAt)
        if st.sessionId is not None:
            paused_open[st.sessionId] += d
        if d <= 0:
            continue
        if st.reason == "breakdown":
            repairs[str(st.stationId)].append(d)
        elif st.reason == "changeover":
            cos[str(st.stationId)].append(d)

    # When each lot left each station: a lot card may visit a station many
    # times (a stamping campaign's card passes every bench once per tray), and
    # each visit, ended by a departure, is one piece of work.
    deps = defaultdict(list)
    for e in events:
        if e.fromStation and e.type in ("moved", "created", "deleted", "updated"):
            deps[(e.fromStation, e.cardId)].append(e.timestamp)

    # One sample per VISIT of a lot to a station, of how long the lot
    # occupied it: from the visit's first Start to its last Stop, in open
    # time, minus its pauses (breakdowns are modelled separately). A lot
    # worked across a break is two sessions; summing only their work time
    # would let the model's stations work through every break the real ones
    # took.
    per_visit = defaultdict(lambda: [None, None, 0.0, 0])
    rates = defaultdict(list)
    spans = defaultdict(list)
    working = defaultdict(float)
    for w in work:
        sid = str(w.stationId)
        if w.durationSec and w.quantity and w.quantity > 0 and w.closedBy != "next_start":
            if w.cardId and w.startedAt and w.endedAt:
                dl = deps.get((sid, str(w.cardId)), [])
                k = bisect.bisect_left(dl, w.endedAt)
                acc = per_visit[(sid, str(w.cardId), k)]
                acc[0] = w.startedAt if acc[0] is None else min(acc[0], w.startedAt)
                acc[1] = w.endedAt if acc[1] is None else max(acc[1], w.endedAt)
                acc[2] += paused_open.get(w.id, 0.0)
                acc[3] += w.quantity
            else:
                rates[sid].append(w.durationSec / w.quantity)
        working[sid] += w.durationSec or 0.0
        if w.startedAt and w.endedAt:
            spans[sid].append((w.startedAt, w.endedAt))
    visits = defaultdict(int)
    for (sid, _, _) in per_visit:
        visits[sid] += 1

    model_st = {}
    for s in stations:
        sid = str(s.id)
        if sid in partners or sid in storage:
            continue
        model_st[sid] = StationModel(
            id=sid, name=s.name,
            servers=max(1, _max_concurrency(spans.get(sid, []))),
            fail_rate=(len(repairs.get(sid, [])) / working[sid]) if working[sid] > 0 else 0.0,
            repairs=repairs.get(sid, []),
            co_prob=min(1.0, len(cos.get(sid, [])) / max(1, visits.get(sid, 0) or len(rates.get(sid, [])))),
            changeovers=cos.get(sid, []))

    # ── graph ──
    by_p = defaultdict(list)
    for r in routes:
        by_p[str(r.processId)].append(r)
    route_proc = defaultdict(set)
    for r in routes:
        route_proc[(str(r.load), str(r.unload))].add(str(r.processId))
    move_counts = defaultdict(int)
    for e in events:
        if e.type == "moved" and e.fromStation and e.toStation:
            move_counts[(e.fromStation, e.toStation)] += int(e.quantity or 0)

    # Which value stream each lot belongs to, from the routes its moves took
    # (a finished or merged lot no longer exists in the cards table).
    card_proc: dict = {}
    for e in events:
        if e.type == "moved" and e.fromStation and e.toStation and e.cardId not in card_proc:
            ps = route_proc.get((e.fromStation, e.toStation))
            if ps and len(ps) == 1:
                card_proc[e.cardId] = next(iter(ps))
    rates_by = defaultdict(lambda: defaultdict(list))
    for (sid, card, _), (first, last, paused, units) in per_visit.items():
        secs = max(0.0, clock(last) - clock(first) - paused)
        if units <= 0 or secs <= 0:
            continue
        rates[sid].append(secs / units)
        pid = card_proc.get(card)
        if pid:
            rates_by[sid][pid].append(secs / units)
    for sid, stm in model_st.items():
        stm.rates = rates.get(sid, [])
        stm.rates_by = {k: v for k, v in rates_by.get(sid, {}).items()}

    routing, merges, merge_lot, endpoints, entries = {}, {}, {}, set(), {}
    for pid, rs in by_p.items():
        outs, ins = defaultdict(list), defaultdict(list)
        for r in rs:
            outs[str(r.load)].append(r)
            ins[str(r.unload)].append(r)
        members = set(outs) | set(ins)

        def worked_downstream(n, seen=None):
            seen = seen or set()
            for r in outs.get(n, []):
                t = str(r.unload)
                if t in seen:
                    continue
                seen.add(t)
                if (t in model_st and model_st[t].worked) or worked_downstream(t, seen):
                    return True
            return False

        for n in members:
            if not ins.get(n):
                entries[(pid, n)] = True
            if n in storage or not outs.get(n) or (
                    not (n in model_st and model_st[n].worked) and not worked_downstream(n)):
                endpoints.add((pid, n))
            o = outs.get(n, [])
            if len(o) >= 2 and n not in choice:
                routing[(pid, n)] = [(str(r.unload), float(max(1, r.quantity or 1)), "piece") for r in o]
            elif len(o) >= 2:
                tot = sum(move_counts.get((n, str(r.unload)), 0) for r in o)
                routing[(pid, n)] = [(str(r.unload),
                                      (move_counts.get((n, str(r.unload)), 0) / tot) if tot else 1 / len(o),
                                      "move") for r in o]
            elif o:
                routing[(pid, n)] = [(str(o[0].unload), 1.0, "move")]
            if len(ins.get(n, [])) >= 2:
                split = {str(r.load) for r in rs if len(outs.get(str(r.load), [])) >= 2
                         and str(r.load) not in choice}
                merges[(pid, n)] = {str(r.load): (1 if str(r.load) in split else max(1, r.quantity or 1))
                                    for r in ins[n]}
                made = [int(e.quantity or 0) for e in events
                        if e.type == "created" and e.toStation == n and (e.note or "").startswith("merged")]
                merge_lot[(pid, n)] = max(1, int(statistics.median(made))) if made else 1

    # ── arrivals: lots leaving an entry station, replayed ──
    arrivals = []
    for e in events:
        if e.type != "moved" or not e.fromStation or not e.toStation:
            continue
        for pid in route_proc.get((e.fromStation, e.toStation), ()):
            if (pid, e.fromStation) in entries:
                arrivals.append(ArrivalIn(t=clock(e.timestamp), qty=int(e.quantity or 1),
                                          process=pid, station=e.toStation, feed=e.fromStation))
                break

    # ── what the line actually took: entry to endpoint, FIFO per lot ──
    flows = []
    fifo = defaultdict(deque)
    pending_merge = defaultdict(list)
    pending_split = defaultdict(list)

    def take(card, q):
        got, want = [], q
        dq = fifo[card]
        while want > 0 and dq:
            t0, n = dq[0]
            k = min(n, want)
            got.append((t0, k))
            want -= k
            if k == n:
                dq.popleft()
            else:
                dq[0] = (t0, n - k)
        return got

    entry_pairs = {(f, t) for (f, t), ps in route_proc.items()
                   if any((p, f) in entries for p in ps)}
    end_any = {n for (_, n) in endpoints}
    for e in events:
        q = int(e.quantity or 0)
        if e.type == "moved" and e.fromStation and e.toStation:
            if (e.fromStation, e.toStation) in entry_pairs:
                fifo[e.cardId].append((clock(e.timestamp), q))
            elif e.toStation in end_any and e.fromStation not in end_any:
                for t0, k in take(e.cardId, q):
                    flows.append((clock(e.timestamp) - t0, k, card_proc.get(e.cardId)))
        elif e.type == "deleted" and e.fromStation and q and e.fromStation not in end_any:
            for t0, k in take(e.cardId, q):
                flows.append((clock(e.timestamp) - t0, k, card_proc.get(e.cardId)))
        elif e.type == "updated" and e.fromStation and q:
            note = e.note or ""
            if note.startswith("merged"):
                pending_merge[e.fromStation] += take(e.cardId, q)
            elif note == "split":
                pending_split[e.fromStation] = take(e.cardId, q)
        elif e.type == "created" and e.toStation and q:
            note = e.note or ""
            src = (pending_merge.pop(e.toStation, None) if note.startswith("merged")
                   else pending_split.get(e.fromStation) if note == "split" else None)
            if src:
                units = sum(k for _, k in src)
                fifo[e.cardId].append((sum(t * k for t, k in src) / units, q))
    units = sum(k for _, k, _ in flows)
    observed = (sum(d * k for d, k, _ in flows) / units) if units else None
    by_p: dict = defaultdict(lambda: [0.0, 0])
    for d, k, pid in flows:
        if pid:
            by_p[pid][0] += d * k
            by_p[pid][1] += k
    return LineModel(stations=model_st, routing=routing, merges=merges, merge_lot=merge_lot,
                     endpoints=endpoints, arrivals=arrivals, horizon=clock.total,
                     observed_lead_sec=observed, observed_n=units,
                     observed_by_process={p_: (v[0] / v[1], v[1]) for p_, v in by_p.items() if v[1]}), names
