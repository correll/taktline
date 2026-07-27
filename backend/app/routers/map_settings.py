import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.connection import SESSION_SCOPE, get_session, get_or_create_singleton
from ..db.tables import MapSettings as MapSettingsRow, UploadedImage
from ..deps.auth import CompanyContext, ensure_full_account, get_active_company, require_super_admin
from ..models.map_settings import MapSettings, MapSettingsUpdate
from ..models.common import utcnow


def _looks_like_image(data: bytes) -> bool:
    """Verify the actual bytes are a known raster image, not just a spoofed
    content-type / extension."""
    if len(data) < 12:
        return False
    return (
        data[:8] == b"\x89PNG\r\n\x1a\n"                    # PNG
        or data[:3] == b"\xff\xd8\xff"                       # JPEG
        or data[:6] in (b"GIF87a", b"GIF89a")               # GIF
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")  # WEBP
        or data[:2] == b"BM"                                 # BMP
    )

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/map-settings", tags=["map-settings"])

# Only raster image types — never .html/.svg/.php etc. The Content-Type served
# back is derived from this suffix whitelist (never from client input), so an
# uploaded file can't be served as active content (stored XSS). SVG is excluded
# because it can carry script. The declared content_type is only a weak hint.
_ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


async def _get_or_create(session: AsyncSession, company_id) -> MapSettingsRow:
    return await get_or_create_singleton(
        session, MapSettingsRow, company_id,
        floorPlanUrl=None, pixelsPerUnit=100.0,
        unit="ft", mapWidthPx=None, mapHeightPx=None, updatedAt=utcnow(),
    )


def _to_model(r: MapSettingsRow) -> MapSettings:
    return MapSettings(
        _id=str(r.id),
        floorPlanUrl=r.floorPlanUrl,
        pixelsPerUnit=r.pixelsPerUnit,
        unit=r.unit,
        stationSizeUnits=r.stationSizeUnits,
        mapWidthPx=r.mapWidthPx,
        mapHeightPx=r.mapHeightPx,
        updatedAt=r.updatedAt,
    )


@router.get("/", response_model=MapSettings)
async def get_map_settings(ctx: CompanyContext = Depends(get_active_company),
                           session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    return _to_model(await _get_or_create(session, ctx.company_id))


@router.post("/upload-floor-plan")
async def upload_floor_plan(file: UploadFile = File(...),
                            ctx: CompanyContext = Depends(require_super_admin),
                            session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    ensure_full_account(ctx)   # sandbox: no floor-plan uploads
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are accepted")
    suffix = (Path(file.filename or "floor_plan.png").suffix or ".png").lower()
    if suffix not in _ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"Unsupported image type '{suffix}'")

    # Read with a hard size cap, then verify the bytes really are an image.
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "File too large")
    if not _looks_like_image(data):
        raise HTTPException(400, "File content is not a recognized image")

    # ts + random tail: same-second uploads (even across companies) must never
    # collide — with a shared filename they'd clobber each other's floor plan.
    fname = f"floor_plan_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"

    # Source of truth is Postgres (survives redeploys on disk-less free hosting);
    # one floor plan per company, so older rows are pruned. The disk write is
    # only the local cache — best-effort by design.
    await session.execute(delete(UploadedImage).where(UploadedImage.companyId == ctx.company_id))
    session.add(UploadedImage(
        companyId=ctx.company_id, filename=fname,
        contentType=_MIME_BY_EXT[suffix], data=data, size=len(data),
    ))
    try:
        (UPLOADS_DIR / fname).write_bytes(data)
    except OSError:
        pass

    url = f"/uploads/{fname}"
    row = await _get_or_create(session, ctx.company_id)
    row.floorPlanUrl = url
    row.updatedAt = utcnow()
    await session.flush()
    return {"url": url}


@router.put("/", response_model=MapSettings)
async def update_map_settings(body: MapSettingsUpdate,
                              ctx: CompanyContext = Depends(require_super_admin),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_or_create(session, ctx.company_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updatedAt = utcnow()
    await session.flush()
    return _to_model(row)


# ── Serving uploads: disk read-through cache over Postgres ────────────────────
# Replaces the old StaticFiles mount. A hit costs one stat + sendfile; a miss
# (fresh instance / cleared disk) pulls the bytes from Postgres once, re-caches
# them, and serves. Filenames are timestamped-unique, so responses are immutable.

uploads_router = APIRouter(tags=["uploads"])

_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _safe_upload_path(filename: str) -> Path:
    """Reject anything that isn't a bare whitelisted-suffix filename."""
    if filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise HTTPException(404, "Not found")
    if Path(filename).suffix.lower() not in _ALLOWED_IMAGE_EXT:
        raise HTTPException(404, "Not found")
    return UPLOADS_DIR / filename


@uploads_router.get("/uploads/{filename}")
async def serve_upload(filename: str, session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    path = _safe_upload_path(filename)
    media_type = _MIME_BY_EXT[Path(filename).suffix.lower()]

    if path.is_file():
        return Response(path.read_bytes(), media_type=media_type, headers=_CACHE_HEADERS)

    row = (await session.execute(
        select(UploadedImage).where(UploadedImage.filename == filename)
    )).scalars().first()
    if row is None:
        raise HTTPException(404, "Not found")
    try:
        path.write_bytes(row.data)   # warm the cache; harmless if two requests race
    except OSError:
        pass
    return Response(bytes(row.data), media_type=media_type, headers=_CACHE_HEADERS)
