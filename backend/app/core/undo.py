"""Undo and redo for lot movements, server-side.

**Why the server.** A client-side action stack is fine for a text editor with
one author. This is a line: eight tablets on one websocket, and the lot you
moved a minute ago may since have been merged by somebody at the next bench.
Undo has to be judged against the state of the floor, and only the server knows
that.

**Why a snapshot rather than an inverse per operation.** Writing "the inverse of
a merge" and "the inverse of a split" by hand would be a second implementation
of the domain, and this codebase has already paid twice for that shape of
duplication — the preview that disagreed with the merge, the editor that
disagreed with the engine about what a merge is. A recorded state cannot drift
from the operation that produced it. The cost is that a restore is a blunt
instrument, which is exactly what the staleness check below is for.

**The rule that makes it safe:** an operation may only be undone while the
cards it touched are *still as it left them*. If anything has moved, merged or
consumed them since, the undo is refused rather than guessed at. That is the
same discipline as refusing a partial move back down a split branch: better to
say no than to invent a plausible answer about material.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.tables import Card as CardRow, UndoEntry as UndoRow
from ..models.common import utcnow

# How deep a person's stack goes. Undo is for the mis-tap you just made, not an
# audit trail — `card_events` is the audit trail, and it is never rewritten.
STACK_DEPTH = 25

_FIELDS = ("lotTemplateId", "processId", "lotNum", "totalQuantity",
           "bins", "fields", "flagged", "description", "status", "orderId")


def _state(row: CardRow) -> dict:
    out = {}
    for f in _FIELDS:
        v = getattr(row, f)
        out[f] = str(v) if f.endswith("Id") and v is not None else v
    return out


async def snapshot(session: AsyncSession, company_id) -> dict:
    """Every lot in the company, by id. Taken either side of an operation and
    diffed, so no endpoint has to declare which cards it is about to touch —
    a declaration that would be wrong the first time somebody added a branch."""
    rows = (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all()
    return {str(r.id): _state(r) for r in rows}


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
    """Are exactly these cards in exactly this state right now?"""
    rows = (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all()
    live = {str(r.id): _state(r) for r in rows if str(r.id) in ids}
    return live == {cid: st for cid, st in expected.items() if cid in ids}


async def apply_state(session: AsyncSession, company_id, target: dict, ids: set) -> list:
    """Put these cards back the way `target` says, creating and deleting as
    needed. Returns the ids that now exist, for the caller to broadcast."""
    import uuid as _uuid

    rows = {str(r.id): r for r in (await session.execute(
        select(CardRow).where(CardRow.companyId == company_id))).scalars().all()
        if str(r.id) in ids}

    alive = []
    for cid in ids:
        want = target.get(cid)
        row = rows.get(cid)
        if want is None:
            if row is not None:
                await session.delete(row)
            continue
        if row is None:
            # The operation destroyed it; put it back under its own id so any
            # other reference to the lot still resolves.
            row = CardRow(id=_uuid.UUID(cid), companyId=company_id)
            session.add(row)
        for f, v in want.items():
            if f.endswith("Id") and v is not None:
                v = _uuid.UUID(v)
            setattr(row, f, v)
        row.updatedAt = utcnow()
        alive.append(cid)
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
