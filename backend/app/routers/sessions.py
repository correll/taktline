from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone
from ..db.connection import get_db
from ..models.session import WorkSession, SessionCreate, SessionEnd
from ..models.common import utcnow

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _to_session(doc: dict) -> WorkSession:
    return WorkSession(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=List[WorkSession])
async def list_sessions(stationId: Optional[str] = None, open_only: bool = False, db=Depends(get_db)):
    query: dict = {}
    if stationId:
        query["stationId"] = stationId
    if open_only:
        query["endedAt"] = None
    docs = await db.sessions.find(query).sort("startedAt", -1).limit(200).to_list(None)
    return [_to_session(d) for d in docs]


@router.post("/", response_model=WorkSession, status_code=201)
async def start_session(body: SessionCreate, db=Depends(get_db)):
    # Allow at most one open session per station+operator
    existing = await db.sessions.find_one({
        "stationId":  body.stationId,
        "operatorId": body.operatorId,
        "endedAt":    None,
    })
    if existing:
        # Auto-close dangling session so the operator can always start fresh
        started = existing.get("startedAt")
        now     = utcnow()
        if started:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration = (now - started).total_seconds()
        else:
            duration = None
        await db.sessions.update_one(
            {"_id": existing["_id"]},
            {"$set": {"endedAt": now, "durationSec": duration}},
        )

    doc = body.model_dump()
    doc["startedAt"] = utcnow()
    doc["endedAt"]   = None
    doc["durationSec"] = None
    result  = await db.sessions.insert_one(doc)
    created = await db.sessions.find_one({"_id": result.inserted_id})
    return _to_session(created)


@router.get("/open", response_model=List[WorkSession])
async def get_open_sessions(db=Depends(get_db)):
    docs = await db.sessions.find({"endedAt": None}).to_list(None)
    return [_to_session(d) for d in docs]


@router.post("/{session_id}/end", response_model=WorkSession)
async def end_session(session_id: str, body: SessionEnd, db=Depends(get_db)):
    doc = await db.sessions.find_one({"_id": ObjectId(session_id)})
    if not doc:
        raise HTTPException(404, "Session not found")
    if doc.get("endedAt") is not None:
        raise HTTPException(400, "Session already closed")

    ended_at    = utcnow()
    started_at  = doc["startedAt"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    patch: dict = {"endedAt": ended_at, "durationSec": duration_sec}
    if body.quantity is not None:
        patch["quantity"] = body.quantity

    result = await db.sessions.find_one_and_update(
        {"_id": ObjectId(session_id)},
        {"$set": patch},
        return_document=True,
    )
    return _to_session(result)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db=Depends(get_db)):
    result = await db.sessions.delete_one({"_id": ObjectId(session_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Session not found")


# ─── All-stations OEE / takt-time summary ────────────────────────────────────

@router.get("/stats")
async def all_station_stats(db=Depends(get_db)):
    """Aggregate OEE/takt-time for every station that has completed sessions."""
    pipeline = [
        {"$match": {"endedAt": {"$ne": None}}},
        {"$group": {
            "_id":            "$stationId",
            "sessionCount":   {"$sum": 1},
            "totalUnits":     {"$sum": "$quantity"},
            "totalWorking":   {"$sum": "$durationSec"},
            "firstStart":     {"$min": "$startedAt"},
            "lastEnd":        {"$max": "$endedAt"},
        }},
    ]
    docs = await db.sessions.aggregate(pipeline).to_list(None)
    results = []
    for d in docs:
        total_units   = d.get("totalUnits") or 0
        total_working = d.get("totalWorking") or 0.0
        takt          = total_working / total_units if total_units > 0 else None
        first_s = d.get("firstStart")
        last_e  = d.get("lastEnd")
        oee     = None
        if first_s and last_e:
            def _utc(dt):
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            span = (_utc(last_e) - _utc(first_s)).total_seconds()
            oee  = min(1.0, total_working / span) if span > 0 else None
        results.append({
            "stationId":       d["_id"],
            "sessionCount":    d.get("sessionCount", 0),
            "totalUnits":      total_units,
            "totalWorkingSec": total_working,
            "taktTimeSec":     takt,
            "oee":             oee,
        })
    return results


# ─── Per-station OEE and takt-time ───────────────────────────────────────────

@router.get("/stats/{station_id}")
async def station_session_stats(station_id: str, db=Depends(get_db)):
    """Return OEE-relevant stats for a station: completed sessions only."""
    docs = await db.sessions.find({
        "stationId": station_id,
        "endedAt":   {"$ne": None},
    }).to_list(None)

    if not docs:
        return {
            "stationId":       station_id,
            "sessionCount":    0,
            "totalUnits":      0,
            "totalWorkingSec": 0.0,
            "taktTimeSec":     None,
            "oee":             None,
        }

    total_units   = sum(d.get("quantity", 1) for d in docs)
    total_working = sum(d.get("durationSec", 0) or 0 for d in docs)
    takt_time     = total_working / total_units if total_units > 0 else None

    # OEE: working_time / (earliest_start → latest_end wall-clock span)
    starts = [d["startedAt"] for d in docs if d.get("startedAt")]
    ends   = [d["endedAt"]   for d in docs if d.get("endedAt")]
    if starts and ends:
        def to_utc(dt):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        span_sec = (max(to_utc(e) for e in ends) - min(to_utc(s) for s in starts)).total_seconds()
        oee = min(1.0, total_working / span_sec) if span_sec > 0 else None
    else:
        oee = None

    return {
        "stationId":       station_id,
        "sessionCount":    len(docs),
        "totalUnits":      total_units,
        "totalWorkingSec": total_working,
        "taktTimeSec":     takt_time,
        "oee":             oee,
    }
