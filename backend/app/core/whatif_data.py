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
from datetime import datetime, timedelta

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


async def _in_flight_at(session, company_id, t: datetime, outside: set) -> dict:
    """Per lot card: units standing at `t` at stations other than `outside`,
    rebuilt backwards from the cards table as `flow.wip_history` does."""
    from ..db.tables import Card as CardRow
    from .flow import _deltas
    level: dict = defaultdict(int)
    for c in (await session.execute(
            select(CardRow).where(CardRow.companyId == company_id))).scalars().all():
        for sid, b in (c.bins or {}).items():
            level[(str(c.id), str(sid))] += int((b or {}).get("count", 0) or 0)
    for ev in (await session.execute(
            select(CardEventRow).where(CardEventRow.companyId == company_id,
                                       CardEventRow.timestamp >= t))).scalars().all():
        for sid, d in _deltas(ev):
            level[(ev.cardId, sid)] -= d
    out: dict = defaultdict(int)
    for (card, sid), n in level.items():
        if sid not in outside and n > 0:
            out[card] += n
    return out


JOIN_SPLIT_STOPPAGES = True   # one breakdown across a session close is one repair
CHANGEOVER_ON_PRODUCT = True  # changeovers follow a change of product
MIN_RELIABLE = 5        # stopped timers a station needs before the others are set aside


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
        if st.sessionId is not None:
            paused_open[st.sessionId] += open_span(st.startedAt, st.endedAt)
    # One breakdown, one repair. Closing a session ends its running pause, so
    # a machine still down at a break or a shift change is recorded as two
    # stoppages: one ended when the timer closed, one opened when the next
    # timer started on a station that was still down. Read as two repairs it
    # makes outages look more frequent and shorter than they were, and short
    # outages queue less work behind them than long ones.
    sess_by_id = {w.id: w for w in work}
    starts_at = defaultdict(list)
    for w in work:
        if w.startedAt:
            starts_at[str(w.stationId)].append(w.startedAt)
    for k in starts_at:
        starts_at[k].sort()
    near = timedelta(seconds=2)

    def continues(prev, nxt) -> bool:
        sa, sb = sess_by_id.get(prev.sessionId), sess_by_id.get(nxt.sessionId)
        if sa is None or sb is None or sa.endedAt is None or sb.startedAt is None:
            return False
        if abs(prev.endedAt - sa.endedAt) > near or abs(nxt.startedAt - sb.startedAt) > near:
            return False
        if sb.startedAt < sa.endedAt:
            return False
        lst = starts_at[str(prev.stationId)]
        i = bisect.bisect_right(lst, sa.endedAt)
        return i < len(lst) and lst[i] == sb.startedAt   # the very next timer there
    by_station = defaultdict(list)
    for st in stops:
        if st.reason in ("breakdown", "changeover"):
            by_station[(str(st.stationId), st.reason)].append(st)
    for (sid, reason), lst in by_station.items():
        lst.sort(key=lambda x: x.startedAt)
        cur, prev = None, None
        for st in lst:
            d = open_span(st.startedAt, st.endedAt)
            if (JOIN_SPLIT_STOPPAGES and reason == "breakdown" and prev is not None and cur is not None
                    and st.sessionId is not None and prev.sessionId is not None
                    and continues(prev, st)):
                cur += d
            else:
                if cur is not None and cur > 0:
                    (repairs if reason == "breakdown" else cos)[sid].append(cur)
                cur = d
            prev = st
        if cur is not None and cur > 0:
            (repairs if reason == "breakdown" else cos)[sid].append(cur)

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
    # Only timers the operator stopped are readings of the work. A timer the
    # lot's departure closed ran on past the work; one closed by the next
    # Start ran through whatever came between; and one forgotten at a shift
    # change overlaps the next shift's timer, which would read as a second
    # server. Those are used only where a station has nothing better.
    def reliable(w):
        return w.closedBy in (None, "operator")
    n_reliable = defaultdict(int)
    for w in work:
        if reliable(w) and w.durationSec and w.quantity and w.quantity > 0:
            n_reliable[str(w.stationId)] += 1

    per_visit = defaultdict(lambda: [None, None, 0.0, 0])
    rates = defaultdict(list)
    spans, spans_all = defaultdict(list), defaultdict(list)
    work_ok, units_ok, units_other, working_all = (defaultdict(float) for _ in range(4))
    for w in work:
        sid = str(w.stationId)
        ok = reliable(w) or (n_reliable[sid] < MIN_RELIABLE and w.closedBy != "next_start")
        if ok and w.durationSec and w.quantity and w.quantity > 0:
            if w.cardId and w.startedAt and w.endedAt:
                dl = deps.get((sid, str(w.cardId)), [])
                # A session the lot's departure closed ends a moment after that
                # departure is recorded; it belongs to the visit the departure
                # ended, not the next one, or two visits merge into one sample
                # that spans the wait between them.
                end = w.endedAt - timedelta(seconds=1) if w.closedBy == "move" else w.endedAt
                k = bisect.bisect_left(dl, end)
                acc = per_visit[(sid, str(w.cardId), k)]
                acc[0] = w.startedAt if acc[0] is None else min(acc[0], w.startedAt)
                acc[1] = w.endedAt if acc[1] is None else max(acc[1], w.endedAt)
                acc[2] += paused_open.get(w.id, 0.0)
                acc[3] += w.quantity
            else:
                rates[sid].append(w.durationSec / w.quantity)
        working_all[sid] += w.durationSec or 0.0
        if reliable(w):
            work_ok[sid] += w.durationSec or 0.0
            units_ok[sid] += w.quantity or 0
            if w.startedAt and w.endedAt:
                spans[sid].append((w.startedAt, w.endedAt))
        else:
            units_other[sid] += w.quantity or 0
        if w.startedAt and w.endedAt:
            spans_all[sid].append((w.startedAt, w.endedAt))
    # Working time, for the breakdown rate per working hour: the stopped
    # timers, plus the units the others carried at the stopped timers' pace.
    working = {sid: (work_ok[sid] + units_other[sid] * work_ok[sid] / units_ok[sid])
               if units_ok[sid] else working_all[sid] for sid in working_all}
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
            servers=max(1, _max_concurrency(spans.get(sid) or spans_all.get(sid, []))),
            fail_rate=(len(repairs.get(sid, [])) / working[sid]) if working.get(sid, 0) > 0 else 0.0,
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

    # Which value stream each lot belongs to: the lot card says so while it
    # exists; a lot merged away or deleted is placed by the routes its moves
    # took. Routes alone cannot place a lot whose streams share every route
    # it used, and a stream whose lots were all placed that way reported no
    # measured lead time however many of them finished.
    from ..db.tables import Card as CardRow
    card_rows = {str(c.id): c for c in (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all()}
    card_proc: dict = {k: str(c.processId) for k, c in card_rows.items() if c.processId}
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

    # What each lot is: its product where the card still exists, else its
    # value stream. Changeovers follow a change of product, which is when they
    # happen on a floor (a welder set up for left brackets is changed over for
    # the first right one); drawn at random per lot instead, they fall where
    # the line is busiest as often as where it is slack.
    def product_of(card):
        c = card_rows.get(card)
        if c is not None and c.lotTemplateId is not None:
            return str(c.lotTemplateId)
        return card_proc.get(card) or ""

    seq = defaultdict(list)
    for (sid, card, _), (first, _last, _p, _u) in per_visit.items():
        if first is not None:
            seq[sid].append((first, product_of(card)))
    for sid, stm in model_st.items():
        vs = [pr for _, pr in sorted(seq.get(sid, []), key=lambda x: x[0])]
        changes = sum(1 for a_, b_ in zip(vs, vs[1:]) if a_ != b_)
        if CHANGEOVER_ON_PRODUCT and stm.changeovers and changes and len(set(vs)) >= 2:
            stm.co_on_change = True
            stm.co_prob = min(1.0, len(stm.changeovers) / changes)

    routing, merges, merge_lot, endpoints, entries = {}, {}, {}, set(), {}
    any_worked = any(st.worked for st in model_st.values())
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
            # Where nothing is timed yet (a record of moves only), the line ends
            # where its routes end; trimming unworked tails would make every
            # station an end and leave no flow to measure.
            if n in storage or not outs.get(n) or (any_worked and
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
        # Several value streams may leave one release queue by the same route;
        # the lot card names the one this lot is in. By the route alone the
        # arrival went to whichever stream came first, and every lot of the
        # others was routed through stations it never visits.
        cands = route_proc.get((e.fromStation, e.toStation), ())
        own = card_proc.get(e.cardId)
        for pid in ([own] if own in cands else []) + sorted(p_ for p_ in cands if p_ != own):
            if (pid, e.fromStation) in entries:
                arrivals.append(ArrivalIn(t=clock(e.timestamp), qty=int(e.quantity or 1),
                                          process=pid, station=e.toStation, feed=e.fromStation,
                                          product=product_of(e.cardId)))
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
    entry_any = {n for (_, n) in entries}
    # Units already between entry and end when the record begins entered
    # before it, at a time nothing recorded. They still finish inside it, and
    # first in, first out they would take the entry times of the lots behind
    # them, so every lead time after them reads short by the gap. They queue
    # first, with no entry time, and their own flow is not counted.
    for card, n in (await _in_flight_at(session, company_id, since, entry_any | end_any)).items():
        if n > 0:
            fifo[card].append((None, n))

    def flow(t, src, pid):
        for t0, k in src:
            if t0 is not None:
                flows.append((t - t0, k, pid))

    for e in events:
        q = int(e.quantity or 0)
        if e.type == "moved" and e.fromStation and e.toStation:
            if (e.fromStation, e.toStation) in entry_pairs:
                fifo[e.cardId].append((clock(e.timestamp), q))
            elif e.toStation in end_any and e.fromStation not in end_any:
                flow(clock(e.timestamp), take(e.cardId, q), card_proc.get(e.cardId))
        elif e.type == "deleted" and e.fromStation and q and e.fromStation not in end_any:
            flow(clock(e.timestamp), take(e.cardId, q), card_proc.get(e.cardId))
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
                # An assembly of any part whose entry is unknown has no known entry.
                known = all(t is not None for t, _ in src)
                fifo[e.cardId].append(((sum(t * k for t, k in src) / units) if known else None, q))
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
