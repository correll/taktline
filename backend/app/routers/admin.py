from fastapi import APIRouter, Depends
from ..db.connection import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset", status_code=204)
async def reset_all(db=Depends(get_db)):
    """Delete all application data (stations, routes, processes, templates, cards, sessions)."""
    await db.sessions.delete_many({})
    await db.cards.delete_many({})
    await db.lot_templates.delete_many({})
    await db.routes.delete_many({})
    await db.processes.delete_many({})
    await db.stations.delete_many({})
