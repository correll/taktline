"""`POST /undo` and `POST /redo`, plus `GET /undo/state` for the buttons."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import undo as undo_core
from ..core.ws_events import queue_event
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import Card as CardRow
from ..deps.auth import CompanyContext, get_active_company

router = APIRouter(tags=["undo"])


class UndoState(BaseModel):
    canUndo: bool
    canRedo: bool
    undoLabel: str | None = None
    redoLabel: str | None = None


class UndoResult(BaseModel):
    label: str
    direction: str


@router.get("/undo/state", response_model=UndoState)
async def undo_state(ctx: CompanyContext = Depends(get_active_company),
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What the two buttons should say. Cheap enough to poll after every
    mutation, which is how they stay honest on a board several people share."""
    nxt = await undo_core.latest(session, ctx, undone=False)
    prev = await undo_core.latest(session, ctx, undone=True)
    return UndoState(canUndo=nxt is not None, canRedo=prev is not None,
                     undoLabel=nxt.label if nxt else None,
                     redoLabel=prev.label if prev else None)


async def _run(direction: str, ctx: CompanyContext, session: AsyncSession) -> UndoResult:
    try:
        entry, ids, alive = await undo_core.step(session, ctx, direction)
    except ValueError as exc:
        # 409, not 400: the request was reasonable and the floor moved. The
        # message says so, because "Bad Request" tells a worker nothing.
        raise HTTPException(409, str(exc))

    # Every other screen has to follow, exactly as it would for the move this
    # is reversing — an undo is a mutation like any other.
    rows = {str(r.id): r for r in (await session.execute(
        select(CardRow).where(CardRow.companyId == ctx.company_id))).scalars().all()}
    from .cards import _to_card
    for cid in ids:
        row = rows.get(cid)
        if row is not None:
            queue_event(session, ctx.company_id, {
                "type": "card_update",
                "payload": _to_card(row).model_dump(by_alias=True, mode="json")})
        else:
            queue_event(session, ctx.company_id,
                        {"type": "card_delete", "payload": {"id": cid}})
    return UndoResult(label=entry.label, direction=direction)


@router.post("/undo", response_model=UndoResult)
async def undo(ctx: CompanyContext = Depends(get_active_company),
               session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Reverse this person's last lot movement.

    Open to any member: an operator who mis-taps at their own bench should be
    able to put it back without finding a super-admin. They can only reverse
    their OWN last action, and only while nothing else has touched those lots.
    """
    return await _run("undo", ctx, session)


@router.post("/redo", response_model=UndoResult)
async def redo(ctx: CompanyContext = Depends(get_active_company),
               session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return await _run("redo", ctx, session)
