"""What the floor held over time, rebuilt from the lot history.

The board shows work in process as it is *now*. Read once a day, that number
is a count, and a count taken at one moment of a line's daily rhythm misses
the average by as much as a mapper's clipboard does (the paper's Acme line:
33-47%). Every unit's arrival and departure is already in the audit log, so the
average is recoverable: walk the log backwards from the present, undoing each
event, and integrate the level over open time.

Backwards, because the present is the one moment whose levels are known for
certain (the cards table). A forward walk would need the state at the start
of the window, which nothing records.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from ..db.tables import Card as CardRow, CardEvent as CardEventRow
from .schedule import open_intervals


def _deltas(ev) -> list[tuple[str, int]]:
    """Unit changes an event made, per station. A split records the source's
    consumption ('updated' from the station) and each piece's birth ('created'
    into a branch) separately, so a 'created' event only ever adds."""
    q = int(ev.quantity or 0)
    if q <= 0:
        return []
    if ev.type == "moved":
        out = []
        if ev.fromStation:
            out.append((ev.fromStation, -q))
        if ev.toStation:
            out.append((ev.toStation, q))
        return out
    if ev.type == "created":
        return [(ev.toStation, q)] if ev.toStation else []
    if ev.type in ("updated", "deleted"):
        return [(ev.fromStation, -q)] if ev.fromStation else []
    return []


async def wip_history(session, company_id, since: datetime, until: datetime):
    """Per station: the level at `since` and the (time, level) steps after it,
    up to `until`. Also returns the time of the first event in the window, so
    a caller can average only over the period the history actually covers."""
    level = defaultdict(int)
    for c in (await session.execute(
            select(CardRow).where(CardRow.companyId == company_id))).scalars().all():
        for sid, b in (c.bins or {}).items():
            level[str(sid)] += int((b or {}).get("count", 0) or 0)
    events = (await session.execute(
        select(CardEventRow).where(CardEventRow.companyId == company_id,
                                   CardEventRow.timestamp >= since)
        .order_by(CardEventRow.timestamp.desc())
    )).scalars().all()
    steps = defaultdict(list)          # station -> [(t, level after t)], built backwards
    first = None
    for ev in events:
        if ev.timestamp > until:
            for sid, d in _deltas(ev):
                level[sid] -= d
            continue
        first = ev.timestamp
        for sid, d in _deltas(ev):
            steps[sid].append((ev.timestamp, level[sid]))
            level[sid] -= d
    start_level = dict(level)
    return start_level, {k: v[::-1] for k, v in steps.items()}, first


def time_average(start: int, steps: list, intervals: list) -> float | None:
    """Average of a step function over the given (open) intervals."""
    total = 0.0
    area = 0.0
    k = 0
    cur = start
    for a, b in intervals:
        t = a
        while k < len(steps) and steps[k][0] <= a:
            cur = steps[k][1]
            k += 1
        while k < len(steps) and steps[k][0] < b:
            area += cur * (steps[k][0] - t).total_seconds()
            t = steps[k][0]
            cur = steps[k][1]
            k += 1
        area += cur * (b - t).total_seconds()
        total += (b - a).total_seconds()
    return area / total if total > 0 else None


async def average_wip(session, company_id, since, until, schedule, tzname) -> dict:
    """Time-averaged units per station over the open hours of the window the
    history covers."""
    start_level, steps, first = await wip_history(session, company_id, since, until)
    if first is None:
        return {}
    ivs = open_intervals(max(since, first), until, schedule, tzname)
    out = {}
    for sid in set(start_level) | set(steps):
        v = time_average(start_level.get(sid, 0), steps.get(sid, []), ivs)
        if v is not None:
            out[sid] = v
    return out


async def by_process(session, company_id, since, until, schedule, tzname) -> tuple[dict, dict]:
    """Per (station, process): average units over open time, and pieces that
    left per open second. A station two value streams share holds units of
    both, and a lead time per stream needs each stream's own share and its own
    exits; the live split at the moment of asking (often an empty floor)
    says nothing about the average."""
    from ..db.tables import Route as RouteRow
    routes = (await session.execute(
        select(RouteRow.load, RouteRow.unload, RouteRow.processId)
        .where(RouteRow.companyId == company_id))).all()
    pair: dict = defaultdict(set)
    for a, b, pid in routes:
        pair[(str(a), str(b))].add(str(pid))
    cards = (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all()
    card_pid = {str(c.id): str(c.processId) for c in cards if c.processId}
    events = (await session.execute(
        select(CardEventRow).where(CardEventRow.companyId == company_id,
                                   CardEventRow.timestamp >= since)
        .order_by(CardEventRow.timestamp.asc()))).scalars().all()
    for e in events:            # lots no longer on the floor: from the routes they took
        if e.cardId not in card_pid and e.type == "moved" and e.fromStation and e.toStation:
            ps = pair.get((e.fromStation, e.toStation))
            if ps and len(ps) == 1:
                card_pid[e.cardId] = next(iter(ps))
    level = defaultdict(int)
    for c in cards:
        for sid, b in (c.bins or {}).items():
            level[(str(sid), card_pid.get(str(c.id)))] += int((b or {}).get("count", 0) or 0)
    steps = defaultdict(list)
    first = None
    exits = defaultdict(int)
    for ev in reversed(events):
        pid = card_pid.get(ev.cardId)
        if ev.timestamp > until:
            for sid, d in _deltas(ev):
                level[(sid, pid)] -= d
            continue
        first = ev.timestamp
        for sid, d in _deltas(ev):
            steps[(sid, pid)].append((ev.timestamp, level[(sid, pid)]))
            level[(sid, pid)] -= d
        if ev.fromStation and ev.type in ("moved", "deleted") and ev.quantity:
            exits[(ev.fromStation, pid)] += int(ev.quantity)
    if first is None:
        return {}, {}
    ivs = open_intervals(max(since, first), until, schedule, tzname)
    open_s = sum((b - a).total_seconds() for a, b in ivs)
    avg = {}
    for key in set(level) | set(steps):
        v = time_average(level.get(key, 0), steps.get(key, [])[::-1], ivs)
        if v is not None and key[1] is not None:
            avg[key] = v
    rate = {k: v / open_s for k, v in exits.items() if k[1] is not None and open_s > 0}
    return avg, rate
