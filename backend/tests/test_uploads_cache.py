"""Floor-plan storage: Postgres source of truth + disk read-through cache."""

from app.routers.map_settings import UPLOADS_DIR
from tests.helpers import Actor, bootstrap_admin, png_bytes


def _upload(a: Actor, filename: str, content: bytes):
    return a.req("POST", "/map-settings/upload-floor-plan",
                 files={"file": (filename, content, "image/png")})


def test_upload_survives_disk_loss():
    a = Actor()
    bootstrap_admin(a)
    r = _upload(a, "floor.png", png_bytes())
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    fname = url.rsplit("/", 1)[1]

    # Served normally (from the disk cache), with immutable caching.
    r = a.req("GET", url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]

    # Simulate a redeploy on disk-less hosting: the cache file vanishes…
    cached = UPLOADS_DIR / fname
    assert cached.is_file()
    cached.unlink()

    # …but the image still serves (from Postgres) and the cache is rebuilt.
    r = a.req("GET", url)
    assert r.status_code == 200 and r.content == png_bytes()
    assert cached.is_file()


def test_upload_serving_rejects_traversal_and_unknown():
    a = Actor()
    bootstrap_admin(a)
    assert a.req("GET", "/uploads/%2e%2e%2fapp%2fmain.py").status_code == 404
    assert a.req("GET", "/uploads/nope.png").status_code == 404
    assert a.req("GET", "/uploads/evil.html").status_code == 404


def test_new_upload_prunes_previous_image_row():
    a = Actor()
    bootstrap_admin(a)
    first = _upload(a, "one.png", png_bytes()).json()["url"]
    second = _upload(a, "two.png", png_bytes()).json()["url"]
    assert first != second
    # Old DB row is gone; the new one serves even without its cache file.
    (UPLOADS_DIR / second.rsplit("/", 1)[1]).unlink(missing_ok=True)
    assert a.req("GET", second).status_code == 200
    (UPLOADS_DIR / first.rsplit("/", 1)[1]).unlink(missing_ok=True)
    assert a.req("GET", first).status_code == 404


# ── A pasted image URL has to actually work ─────────────────────────────────

STATION_M = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
             "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _png(w: int, h: int) -> bytes:
    import struct, zlib
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * ((w * 3 + 1) * h)))
            + chunk(b"IEND", b""))


def test_an_external_floor_plan_url_is_copied_to_our_own_origin(actor, monkeypatch):
    """Reported on a real line: a floor plan pasted as an image URL never
    appeared. WebGL refuses to use a cross-origin image as a texture unless the
    host sends Access-Control-Allow-Origin, and image CDNs generally do not —
    so the load threw and the canvas stayed blank. Copying it to our origin
    makes it work, and outlives the link."""
    import httpx
    from app.routers import map_settings as ms

    async def fake_localise(url):
        assert url.startswith("https://")
        data = _png(640, 480)
        kind = ms._sniff_image(data)
        assert kind == ".png"
        w, h = ms._image_size(data)
        return "/uploads/copied.png", w, h

    monkeypatch.setattr(ms, "_localise_remote_image", fake_localise)
    a = actor(); bootstrap_admin(a)
    r = a.req("PUT", "/map-settings/",
              {"floorPlanUrl": "https://cdn.example.com/plan.png"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["floorPlanUrl"] == "/uploads/copied.png", \
        "an external URL was stored as-is and will never render"
    assert body["mapWidthPx"] == 640 and body["mapHeightPx"] == 480


def test_a_local_upload_path_is_left_alone(actor):
    a = actor(); bootstrap_admin(a)
    r = a.req("PUT", "/map-settings/", {"floorPlanUrl": "/uploads/mine.png"})
    assert r.status_code == 200
    assert r.json()["floorPlanUrl"] == "/uploads/mine.png"


def test_the_fetcher_refuses_to_reach_inside_the_network(actor):
    """Fetching a user-supplied URL from the server is an SSRF surface."""
    import asyncio
    from fastapi import HTTPException
    from app.routers.map_settings import _localise_remote_image

    for bad in ("http://127.0.0.1/plan.png", "http://localhost:8000/plan.png",
                "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
                "http://user:pw@example.com/x.png"):
        try:
            asyncio.get_event_loop().run_until_complete(_localise_remote_image(bad))
            raise AssertionError(f"{bad} was fetched")
        except HTTPException as exc:
            assert exc.status_code == 400, (bad, exc.detail)
        except RuntimeError:
            asyncio.run(_assert_refused(bad))


async def _assert_refused(url: str):
    from fastapi import HTTPException
    from app.routers.map_settings import _localise_remote_image
    try:
        await _localise_remote_image(url)
    except HTTPException as exc:
        assert exc.status_code == 400, (url, exc.detail)
        return
    raise AssertionError(f"{url} was fetched")


def test_bytes_that_are_not_an_image_are_refused():
    from app.routers.map_settings import _sniff_image
    assert _sniff_image(b"<html><body>nope") is None
    assert _sniff_image(_png(2, 2)) == ".png"
    assert _sniff_image(b"\xff\xd8\xff\xe0stuff") == ".jpg"


def test_floor_plan_opacity_round_trips(actor):
    """A busy CAD drawing at full strength competes with the stations and
    routes drawn over it; fading it turns the plan back into a backdrop."""
    a = actor(); bootstrap_admin(a)
    assert a.req("GET", "/map-settings/").json()["floorPlanOpacity"] == 1.0, \
        "an existing map must not change appearance"

    r = a.req("PUT", "/map-settings/", {"floorPlanOpacity": 0.35})
    assert r.status_code == 200, r.text
    assert r.json()["floorPlanOpacity"] == 0.35
    assert a.req("GET", "/map-settings/").json()["floorPlanOpacity"] == 0.35


def test_an_opacity_outside_the_range_is_refused(actor):
    """Clamped server-side, not merely on the slider: out of range renders as
    an invisible or over-bright plan with no error anywhere, and the value can
    arrive from a script that never saw the slider."""
    a = actor(); bootstrap_admin(a)
    for bad in (-0.5, 1.5, 42):
        r = a.req("PUT", "/map-settings/", {"floorPlanOpacity": bad})
        assert r.status_code == 422, f"{bad} was accepted: {r.text[:120]}"
    assert a.req("GET", "/map-settings/").json()["floorPlanOpacity"] == 1.0


def test_the_extremes_are_allowed(actor):
    a = actor(); bootstrap_admin(a)
    for good in (0.0, 1.0):
        assert a.req("PUT", "/map-settings/",
                     {"floorPlanOpacity": good}).status_code == 200
