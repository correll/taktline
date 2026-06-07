import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from ..db.connection import get_db
from ..models.map_settings import MapSettings, MapSettingsUpdate
from ..models.common import utcnow

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/map-settings", tags=["map-settings"])

SINGLETON_KEY = "global"   # stored as a single document with this key


async def _get_or_create(db) -> dict:
    doc = await db.map_settings.find_one({"_key": SINGLETON_KEY})
    if not doc:
        default = {"_key": SINGLETON_KEY, "floorPlanUrl": None, "pixelsPerUnit": 100.0,
                   "unit": "ft", "mapWidthPx": None, "mapHeightPx": None, "updatedAt": utcnow()}
        await db.map_settings.insert_one(default)
        doc = await db.map_settings.find_one({"_key": SINGLETON_KEY})
    return doc


def _to_model(doc: dict) -> MapSettings:
    return MapSettings(**{**doc, "_id": str(doc["_id"])})


@router.get("/", response_model=MapSettings)
async def get_map_settings(db=Depends(get_db)):
    doc = await _get_or_create(db)
    return _to_model(doc)


@router.post("/upload-floor-plan")
async def upload_floor_plan(file: UploadFile = File(...), db=Depends(get_db)):
    """Accept a PNG/JPG upload, save to disk, store the URL in map settings."""
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are accepted")

    suffix = Path(file.filename or "floor_plan.png").suffix or ".png"
    dest = UPLOADS_DIR / f"floor_plan{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    url = f"/uploads/floor_plan{suffix}"
    await _get_or_create(db)
    await db.map_settings.update_one(
        {"_key": SINGLETON_KEY},
        {"$set": {"floorPlanUrl": url, "updatedAt": utcnow()}},
    )
    return {"url": url}


@router.put("/", response_model=MapSettings)
async def update_map_settings(body: MapSettingsUpdate, db=Depends(get_db)):
    await _get_or_create(db)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["updatedAt"] = utcnow()
    result = await db.map_settings.find_one_and_update(
        {"_key": SINGLETON_KEY},
        {"$set": patch},
        return_document=True,
    )
    return _to_model(result)
