"""Undo and redo for the graph editor, server-side.

**Scope, deliberately: stations and routes. Not lots.** A lot card records a
physical fact — where the material actually is. Undoing a move does not carry
the material back down the shop, so the board would start lying about the floor,
and the whole value of the thing is that it does not. Drawing the line is
configuration: a mis-clicked delete destroys somebody's work with no physical
counterpart, and putting it back is simply correct.

**Why the server.** A client-side action stack is fine for a text editor with
one author. Here two people can be editing the same line from different rooms,
and the route you deleted a minute ago may since have been redrawn by somebody
else. Undo has to be judged against the state of the line, and only the server
knows that.

**Why a snapshot rather than an inverse per edit.** Hand-writing "the inverse of
deleting a station" means keeping a second description of what a station is,
which drifts the first time a field is added. A recorded state cannot. The cost
is that a restore is a blunt instrument, which is what the staleness check is
for.

**The rule that makes it safe:** an edit may only be undone while the stations
and routes it touched are *still as it left them*. If somebody has since
redrawn that route or renamed that station, the undo is refused rather than
guessed at — better to say no than to quietly overwrite a colleague.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.tables import Route as RouteRow, Station as StationRow, UndoEntry as UndoRow
from ..models.common import utcnow

# How deep a person's stack goes. Undo is for the mis-click you just made, not
# an audit trail.
STACK_DEPTH = 25

# Stations before routes on the way in, routes before stations on the way out:
# a route has foreign keys to both ends, so recreating one whose station is
# still missing fails, and deleting a station still referenced by a route fails
# the other way round.
_KINDS = (
    ("station", StationRow, ("name", "position", "description", "color", "icon",
                             "adapterType", "adapterConfig", "integrationProvider",
                             "integrationRole", "isStorage", "branchMode")),
    ("route", RouteRow, ("processId", "load", "unload", "quantity",
                         "outputTemplateId")),
)
_BY_KIND = {kind: (model, fields) for kind, model, fields in _KINDS}


def _state(row, fields) -> dict:
    out = {}
    for f in fields:
        v = getattr(row, f, None)
        out[f] = str(v) if (f in ("processId", "load", "unload", "outputTemplateId")
                            and v is not None) else v
    return out


async def snapshot(session: AsyncSession, company_id) -> dict:
    """The whole drawn line, keyed `kind:id`. Taken either side of an edit and
    diffed, so no endpoint has to declare what it is about to touch — a
    declaration that would be wrong the first time somebody added a field."""
    out: dict = {}
    for kind, model, fields in _KINDS:
        rows = (await session.execute(
            select(model).where(model.companyId == company_id))).scalars().all()
        for r in rows:
            out[f"{kind}:{r.id}"] = _state(r, fields)
    return out


def _changed(before: dict, after: dict) -> set:
    return {cid for cid in set(before) | set(after) if before.get(cid) != after.get(cid)}


async def record(session: AsyncSession, ctx, label: str, before: dict, after: dict) -> None:
    """Remember what an operation did, if it did anything."""
    touched = _changed(before, after)
    if not touched:
        return
    user_id = getattr(getattr(ctx, "user", None), "id", None)
    session.add(UndoRow(
        companyId=ctx.company_id, userId=user_id, label=label,
        beforeState={cid: before[cid] for cid in touched if cid in before},
        afterState={cid: after[cid] for cid in touched if cid in after},
        undone=False, createdAt=utcnow(),
    ))
    await session.flush()

    # Anything the person has undone is no longer redoable once they do
    # something new — the branch they were on is gone, which is how every undo
    # stack anybody has used behaves.
    stale = (await session.execute(
        select(UndoRow).where(UndoRow.companyId == ctx.company_id,
                              UndoRow.userId == user_id,
                              UndoRow.undone.is_(True)))).scalars().all()
    for row in stale:
        await session.delete(row)

    keep = (await session.execute(
        select(UndoRow).where(UndoRow.companyId == ctx.company_id,
                              UndoRow.userId == user_id)
        .order_by(UndoRow.createdAt.desc()))).scalars().all()
    for row in keep[STACK_DEPTH:]:
        await session.delete(row)


async def _matches(session: AsyncSession, company_id, expected: dict, ids: set) -> bool:
    """Are exactly these stations and routes in exactly this state right now?"""
    live = {k: v for k, v in (await snapshot(session, company_id)).items() if k in ids}
    return live == {k: v for k, v in expected.items() if k in ids}


async def apply_state(session: AsyncSession, company_id, target: dict, ids: set) -> list:
    """Put these stations and routes back the way `target` says, creating and
    deleting as needed. Returns the keys that now exist, for the broadcast."""
    import uuid as _uuid

    def split(key):
        kind, _, raw = key.partition(":")
        return kind, raw

    live: dict = {}
    for kind, model, _f in _KINDS:
        for r in (await session.execute(
                select(model).where(model.companyId == company_id))).scalars().all():
            live[f"{kind}:{r.id}"] = r

    # Deletions first, routes before stations; then creations and updates,
    # stations before routes. Either order reversed trips a foreign key.
    for key in sorted(ids, key=lambda k: 0 if k.startswith("route:") else 1):
        if target.get(key) is None and key in live:
            await session.delete(live.pop(key))
    await session.flush()

    alive = []
    for key in sorted(ids, key=lambda k: 0 if k.startswith("station:") else 1):
        want = target.get(key)
        if want is None:
            continue
        kind, raw = split(key)
        model, fields = _BY_KIND[kind]
        row = live.get(key)
        if row is None:
            # Put it back under its own id, so anything still pointing at it —
            # a lot template's start station, another route's end — resolves.
            row = model(id=_uuid.UUID(raw), companyId=company_id)
            session.add(row)
        for f in fields:
            v = want.get(f)
            if f in ("processId", "load", "unload", "outputTemplateId") and v is not None:
                v = _uuid.UUID(v)
            setattr(row, f, v)
        if hasattr(row, "updatedAt"):
            row.updatedAt = utcnow()
        alive.append(key)
        await session.flush()
    return alive


async def latest(session: AsyncSession, ctx, undone: bool):
    user_id = getattr(getattr(ctx, "user", None), "id", None)
    order = UndoRow.createdAt.asc() if undone else UndoRow.createdAt.desc()
    return (await session.execute(
        select(UndoRow).where(UndoRow.companyId == ctx.company_id,
                              UndoRow.userId == user_id,
                              UndoRow.undone.is_(undone))
        .order_by(order).limit(1))).scalars().first()


async def step(session: AsyncSession, ctx, direction: str):
    """Undo the last thing this person did, or redo the last thing they undid.

    Returns (entry, ids) or raises ValueError with a message meant for a human
    standing at a bench.
    """
    entry = await latest(session, ctx, undone=(direction == "redo"))
    if entry is None:
        raise ValueError("Nothing to undo" if direction == "undo" else "Nothing to redo")

    ids = set(entry.beforeState) | set(entry.afterState)
    expect = entry.afterState if direction == "undo" else entry.beforeState
    target = entry.beforeState if direction == "undo" else entry.afterState

    if not await _matches(session, ctx.company_id, expect, ids):
        raise ValueError(
            f"Those lots have moved on since — “{entry.label}” can no longer be "
            f"{'undone' if direction == 'undo' else 'redone'} without overwriting "
            "somebody else's work.")

    alive = await apply_state(session, ctx.company_id, target, ids)
    entry.undone = (direction == "undo")
    await session.flush()
    return entry, ids, alive
