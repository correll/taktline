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
