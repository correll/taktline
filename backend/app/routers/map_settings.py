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


def _image_size(data: bytes):
    """(width, height) of a PNG, JPEG or GIF, straight from the header bytes.

    Deliberately not a new dependency: only the raster formats the upload
    whitelist already allows are read, and anything unrecognised returns
    (None, None) so the caller falls back to what it did before.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:3] == b"GIF" and len(data) >= 10:
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if data[:2] == b"\xff\xd8":                       # JPEG: walk the segments
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker, seg = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    return (int.from_bytes(data[i + 7:i + 9], "big"),
                            int.from_bytes(data[i + 5:i + 7], "big"))
                i += 2 + seg
    except Exception:
        pass
    return None, None


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
    # Fail loudly. Swallowing the write meant a full or read-only disk answered
    # 200 with a URL, the settings page showed a saved floor plan, and the map
    # drew nothing — the same empty canvas as a missing sprite rect, from a
    # cause nothing reported.
    try:
        (UPLOADS_DIR / fname).write_bytes(data)
    except OSError as exc:
        raise HTTPException(507, f"Could not store the floor plan: {exc.strerror or exc}")

    # Read the real pixel dimensions here rather than trusting the browser to
    # measure a preview it may not have finished loading. `pixelsPerUnit` is
    # defined against these numbers, so a floor plan whose size depends on
    # whether an <img> had decoded before someone pressed Save is a scale that
    # silently varies.
    width, height = _image_size(data)

    url = f"/uploads/{fname}"
    row = await _get_or_create(session, ctx.company_id)
    row.floorPlanUrl = url
    if width and height:
        row.mapWidthPx, row.mapHeightPx = width, height
    row.updatedAt = utcnow()
    await session.flush()
    return {"url": url}


async def _localise_remote_image(url: str) -> tuple:
    """Fetch an external floor-plan URL once and keep it as our own file.

    A pasted image URL is a perfectly reasonable thing to give this field, and
    it did not work: WebGL refuses to upload a cross-origin image as a texture
    unless the host sends `Access-Control-Allow-Origin`, and image CDNs
    generally do not. The floor plan silently never appeared — the load threw,
    the loader swallowed it, and the canvas was simply blank. Copying the image
    to our own origin fixes it for good, and it also means the plan keeps
    working when that URL rots, which pasted links do.

    Fetching a user-supplied URL from the server is an SSRF surface, so it is
    fenced: http(s) only, no credentials in the URL, the resolved address must
    be public (no loopback, link-local, private range or metadata endpoint),
    one redirect hop at most re-checked the same way, a hard byte cap, and the
    bytes must actually begin like one of the raster formats we allow.
    Returns (relative_url, width, height).
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    import httpx

    def _vet(target: str) -> str:
        u = urlparse(target)
        if u.scheme not in ("http", "https"):
            raise HTTPException(400, "A floor-plan URL must be http or https.")
        if u.username or u.password:
            raise HTTPException(400, "A floor-plan URL may not carry credentials.")
        if not u.hostname:
            raise HTTPException(400, "That floor-plan URL has no host.")
        try:
            infos = socket.getaddrinfo(u.hostname, None)
        except OSError:
            raise HTTPException(400, f"Could not resolve {u.hostname}.")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                raise HTTPException(400,
                    "That address is inside a private network, so it is refused.")
        return target

    _vet(url)
    data = b""
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            target = url
            for _hop in range(2):
                resp = await client.get(target, headers={"Accept": "image/*"})
                if resp.status_code in (301, 302, 303, 307, 308):
                    nxt = resp.headers.get("location")
                    if not nxt:
                        raise HTTPException(400, "That URL redirected nowhere.")
                    target = _vet(str(httpx.URL(target).join(nxt)))
                    continue
                resp.raise_for_status()
                data = resp.content
                break
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not fetch that floor-plan image: {exc}")

    if not data:
        raise HTTPException(400, "That URL returned no image.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "That floor-plan image is too large.")

    # Trust the bytes, not the URL or the content-type header.
    kind = _sniff_image(data)
    if kind is None:
        raise HTTPException(400,
            "That URL does not point at a PNG, JPEG, GIF or WebP image.")

    fname = f"floor_plan_{int(time.time())}_{uuid.uuid4().hex[:8]}{kind}"
    try:
        (UPLOADS_DIR / fname).write_bytes(data)
    except OSError as exc:
        raise HTTPException(507, f"Could not store the floor plan: {exc.strerror or exc}")
    w, h = _image_size(data)
    return f"/uploads/{fname}", w, h


def _sniff_image(data: bytes):
    """The extension this data really is, from its magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:3] == b"GIF":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return None


@router.put("/", response_model=MapSettings)
async def update_map_settings(body: MapSettingsUpdate,
                              ctx: CompanyContext = Depends(require_super_admin),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    row = await _get_or_create(session, ctx.company_id)
    patch = body.model_dump(exclude_unset=True)

    # An external image is copied to our own origin, because a cross-origin one
    # cannot be used as a WebGL texture without CORS headers the host usually
    # does not send.
    url = patch.get("floorPlanUrl")
    if isinstance(url, str) and url.strip().lower().startswith(("http://", "https://")):
        local, w, h = await _localise_remote_image(url.strip())
        patch["floorPlanUrl"] = local
        patch.setdefault("mapWidthPx", w)
        patch.setdefault("mapHeightPx", h)

    for k, v in patch.items():
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
