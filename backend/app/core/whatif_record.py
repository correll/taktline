"""What the record says about the what-if model's idealisations.

The model assumes unlimited buffers, stations staffed independently at a
constant number of servers, and breakdowns that accrue with work
(`core/whatif.py`). Each assumption leaves a trace in the record when a line
works otherwise, and each can be replaced by what the record shows:

* **a buffer that fills.** A station that never holds more than so many units,
  while the lots finished in front of it wait to be moved on, is held to that
  number: the station feeding it blocks.
* **a shared crew.** Two stations that are each busy much of the time but are
  never worked at the same moment are worked by the same people.
* **breakdowns on the calendar.** Breakdowns that begin while a station is idle
  accrue on open hours, not on working hours.
* **a crew that changes over the day.** The operators present at a station
  (from each one's first Start to last Stop in an opening) vary: the model can
  replay the crew as recorded, the way it replays arrivals.

Pure: given rows already read by `whatif_data.build_model`, it measures, it
does not decide. Which replacement to make is the caller's question; the
numbers here are what that decision rests on.
"""
from __future__ import annotations

import bisect
from collections import defaultdict


def _merge(iv: list) -> list:
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _overlap(x: list, y: list) -> float:
    """Total overlap of two sorted, merged interval lists."""
    i = j = 0
    tot = 0.0
    while i < len(x) and j < len(y):
        a, b = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if b > a:
            tot += b - a
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return tot


def measure(*, clock, openings: list, stations: list, work: list, stops: list,
            events: list, routes: list, horizon: float) -> dict:
    """Everything in open seconds from the start of the window.

    `openings` are the window's open intervals (wall-clock datetimes);
    `work` sessions, `stops` stoppages and `events` lot events are ORM rows."""
    T = max(horizon, 1.0)
    sids = [str(s.id) for s in stations]
    # Busy intervals (any session running), per station, in open time.
    busy = defaultdict(list)
    for w in work:
        if w.startedAt and w.endedAt:
            busy[str(w.stationId)].append((clock(w.startedAt), clock(w.endedAt)))
    busy = {k: _merge(v) for k, v in busy.items()}
    busy_share = {k: sum(b - a for a, b in v) / T for k, v in busy.items()}

    # ── a shared crew: pairs of stations each busy, never at once ──
    pairs = []
    ks = sorted(k for k in busy if busy_share.get(k, 0) > 0)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            expected = busy_share[a] * busy_share[b] * T      # overlap if independent
            seen = _overlap(busy[a], busy[b])
            pairs.append({"stations": [a, b], "overlapSec": round(seen, 1),
                          "expectedSec": round(expected, 1),
                          "ratio": round(seen / expected, 3) if expected > 0 else None})

    # ── breakdowns on the calendar: how many begin while the station is idle ──
    clockrate = {}
    for sid in sids:
        bd = [st for st in stops if str(st.stationId) == sid and st.reason == "breakdown"]
        if not bd:
            continue
        iv = busy.get(sid, [])
        starts = [a for a, _ in iv]
        idle_bd = 0
        for st in bd:
            t = clock(st.startedAt)
            k = bisect.bisect_right(starts, t) - 1
            inside = k >= 0 and iv[k][0] <= t <= iv[k][1]
            idle_bd += 0 if inside or st.sessionId is not None else 1
        idle_share = max(0.0, 1 - busy_share.get(sid, 0.0))
        clockrate[sid] = {"breakdowns": len(bd), "idleBreakdowns": idle_bd,
                          "idleShare": round(idle_share, 3),
                          # share of breakdowns begun while idle over the idle
                          # share of open time: 0 on a work clock, about 1 on
                          # the calendar
                          "ratio": round((idle_bd / len(bd)) / idle_share, 3) if idle_share > 0.01 else None,
                          "perOpenSec": len(bd) / T}

    # ── a buffer that fills: lots at each station over time, and how long
    #    finished lots wait to leave ──
    present = defaultdict(lambda: defaultdict(int))     # station -> card -> units
    lots_now, units_now = defaultdict(int), defaultdict(int)
    max_lots, max_units = defaultdict(int), defaultdict(int)
    for e in events:
        q = int(e.quantity or 0)
        if e.fromStation and e.type in ("moved", "deleted", "updated"):
            s, c = e.fromStation, e.cardId
            before = present[s][c]
            present[s][c] = max(0, before - q)
            units_now[s] -= before - present[s][c]
            if before > 0 and present[s][c] == 0:
                lots_now[s] -= 1
        if e.toStation and e.type in ("moved", "created"):
            s, c = e.toStation, e.cardId
            if present[s][c] == 0:
                lots_now[s] += 1
                max_lots[s] = max(max_lots[s], lots_now[s])
            present[s][c] += q
            units_now[s] += q
            max_units[s] = max(max_units[s], units_now[s])
    last_stop = {}
    for w in sorted(work, key=lambda x: x.endedAt or x.startedAt):
        if w.cardId and w.endedAt:
            last_stop[(str(w.stationId), str(w.cardId))] = w.endedAt
    waits = defaultdict(list)
    for e in events:
        if e.type == "moved" and e.fromStation:
            t_end = last_stop.get((e.fromStation, e.cardId))
            if t_end is not None and t_end <= e.timestamp:
                waits[e.fromStation].append(max(0.0, clock(e.timestamp) - clock(t_end)))
    feeders = defaultdict(set)
    for r in routes:
        feeders[str(r.unload)].add(str(r.load))
    buffers = {}
    for sid in sids:
        w_up = [x for f in feeders.get(sid, ()) for x in waits.get(f, [])]
        buffers[sid] = {"maxLots": max_lots.get(sid, 0), "maxUnits": max_units.get(sid, 0),
                        "feederFinishedWaitSec": round(sum(w_up) / len(w_up), 1) if w_up else None}

    # ── a crew that changes over the day: operators present, as recorded ──
    crew = defaultdict(lambda: defaultdict(lambda: [None, None]))   # station -> (op, opening) -> span
    starts_o = [clock(a) for a, _ in openings]
    for w in work:
        if not (w.startedAt and w.endedAt and w.operatorId):
            continue
        t0, t1 = clock(w.startedAt), clock(w.endedAt)
        k = max(0, bisect.bisect_right(starts_o, t0) - 1)
        span = crew[str(w.stationId)][(w.operatorId, k)]
        span[0] = t0 if span[0] is None else min(span[0], t0)
        span[1] = t1 if span[1] is None else max(span[1], t1)
    staffing = {}
    for sid, spans in crew.items():
        edges = []
        for a, b in spans.values():
            edges += [(a, 1), (b, -1)]
        edges.sort()
        sched, n = [], 0
        for t, d in edges:
            n += d
            if sched and sched[-1][0] == t:
                sched[-1] = (t, n)
            else:
                sched.append((t, n))
        counts = [c for _, c in sched]
        staffing[sid] = {"schedule": sched, "min": min(counts) if counts else 0,
                         "max": max(counts) if counts else 0}

    return {"busyShare": {k: round(v, 4) for k, v in busy_share.items()},
            "sharedCrew": pairs, "breakdownClock": clockrate,
            "buffers": buffers, "staffing": staffing}
