from fastapi import APIRouter, Depends
from ..db.connection import get_db
from ..models.global_settings import GlobalSettings, GlobalSettingsUpdate
from ..models.common import utcnow

router = APIRouter(prefix="/global-settings", tags=["global-settings"])


@router.get("/", response_model=GlobalSettings)
async def get_global_settings(db=Depends(get_db)):
    doc = await db.global_settings.find_one()
    if not doc:
        return GlobalSettings()
    return GlobalSettings(**{**doc, "_id": str(doc["_id"])})


@router.put("/", response_model=GlobalSettings)
async def update_global_settings(body: GlobalSettingsUpdate, db=Depends(get_db)):
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    existing = await db.global_settings.find_one()
    if existing:
        await db.global_settings.update_one({"_id": existing["_id"]}, {"$set": update})
        doc = await db.global_settings.find_one({"_id": existing["_id"]})
    else:
        defaults = GlobalSettings().model_dump(exclude={"id"})
        defaults.update(update)
        result = await db.global_settings.insert_one(defaults)
        doc = await db.global_settings.find_one({"_id": result.inserted_id})
    return GlobalSettings(**{**doc, "_id": str(doc["_id"])})
