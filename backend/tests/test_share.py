"""Share cards: the catalogue, the rendered PNGs, the public page, and the
before/after a company publishes.

The failure this file exists to prevent is a *dead or wrong link in someone
else's LinkedIn post* — which we cannot fix after the fact and never find out
about. So: every id in the catalogue must render, the page must carry the tags
a crawler reads, and a published improvement must keep saying what its author
approved.
"""

import asyncio
import io
import re
import uuid
from datetime import timedelta

import pytest
from PIL import Image

from app.core import share as share_core
from app.models.common import utcnow
from tests.helpers import Actor, add_member, bootstrap_admin


# ─── The catalogue ───────────────────────────────────────────────────────────

def test_catalogue_has_both_kinds():
    items = share_core.catalog()
    assert sum(1 for i in items.values() if i.kind == "tip") >= 90
    # Flow science plus the improvement toolkit — the exact count moves as the
    # manual grows, so this checks the shape rather than pinning a number the
    # frontend already asserts per chapter.
    assert sum(1 for i in items.values() if i.kind == "concept") >= 20


def test_every_catalogue_item_renders_a_valid_card():
    """All of them, not a sample.

    The renderer shrinks type until the text fits, and the tips run from 90 to
    520 characters — a single entry that overflows or divides by zero would only
    surface when somebody shared exactly that one.
    """
    for item in share_core.catalog().values():
        png = share_core.render_card(item)
        img = Image.open(io.BytesIO(png))
        assert img.size == (1200, 630), item.id
        assert img.format == "PNG"


def test_no_catalogue_id_can_be_mistaken_for_a_published_card():
    """Stored improvement slugs are 18 hex characters and live in the same URL
    namespace. `/i/<id>` checks the catalogue first, so an overlap would shadow
    somebody's published card rather than 404 — silently serving the wrong
    content."""
    for item_id in share_core.catalog():
        assert not re.fullmatch(r"[0-9a-f]{18}", item_id), item_id


def test_ids_are_url_safe():
    for item_id in share_core.catalog():
        assert share_core.ID_RE.match(item_id), item_id


def test_the_card_does_not_render_tofu():
    """Pillow's built-in face has no em dash, no ÷ and no ρ — all of which are
    in this copy, and all of which came out as notdef boxes. The bundled Inter
    is what fixes it, so check the glyphs actually exist rather than trusting
    that the file is present."""
    font = share_core._font(40)
    for ch in "—÷≈ρ²×≤’“”":
        assert font.getmask(ch).size[0] > 0, ch
    # A .notdef box is one fixed advance for every character; real glyphs are not.
    widths = {font.getlength(ch) for ch in "—÷≈ρ²×≤"}
    assert len(widths) > 1


# ─── The public page ─────────────────────────────────────────────────────────

@pytest.fixture
def anon():
    return Actor()


def test_share_page_carries_the_items_own_open_graph_tags(anon):
    r = anon.req("GET", "/i/kingman")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # LinkedIn reads these and nothing else — it does not run the SPA.
    assert 'property="og:title" content="At 90% utilisation' in body
    assert 'property="og:image" content="' in body
    assert "/i/kingman/card.png" in body
    assert 'name="twitter:card" content="summary_large_image"' in body


def test_share_page_has_content_without_javascript(anon):
    """A crawler that renders nothing still gets the claim in plain HTML."""
    body = anon.req("GET", "/i/littles-law").text
    assert "<noscript>" in body
    assert "Halve the work on your floor" in body


def test_card_png_is_served_and_cacheable(anon):
    r = anon.req("GET", "/i/monuments/card.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers.get("cache-control", "")
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)


def test_share_pages_need_no_session(anon):
    """The whole point is that a stranger can open it."""
    assert anon.tc.cookies.get("taktline_session") is None
    assert anon.req("GET", "/i/matched-sets").status_code == 200


@pytest.mark.parametrize("bad", ["nope-nope-nope", "UPPER", "has..dots", "a", "x" * 90])
def test_unknown_or_malformed_ids_are_404(anon, bad):
    assert anon.req("GET", f"/i/{bad}").status_code == 404
    assert anon.req("GET", f"/i/{bad}/card.png").status_code == 404


def test_share_routes_win_over_the_spa_catch_all():
    """`/i/<id>` must be resolved by the share router, not by the SPA fallback.

    The fallback is registered last precisely so this holds; a future
    `include_router` placed after it would send every crawler the generic
    landing card, and every preview would silently become wrong.
    """
    from app.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/i/{item_id}" in paths
    if "/{full_path:path}" in paths:
        assert paths.index("/i/{item_id}") < paths.index("/{full_path:path}")


# ─── The improvement card ────────────────────────────────────────────────────

def _station(a: Actor, name: str) -> str:
    r = a.req("POST", "/stations/", {"name": name, "position": {"x": 0, "y": 0}})
    assert r.status_code == 201, r.text
    return r.json()["_id"]


def _seed_sessions(company_id: str, station_id: str, *, days_ago: float,
                   count: int, quantity: int, duration: float) -> None:
    """Write finished work sessions directly, backdated.

    The API can only close a session at `now`, and this metric is defined as one
    window against the window before it — so there is no way to exercise it
    through the endpoints alone.
    """
    from app.db.connection import SessionLocal
    from app.db.tables import WorkSession

    async def go():
        async with SessionLocal() as s:
            for i in range(count):
                ended = utcnow() - timedelta(days=days_ago) + timedelta(minutes=i)
                s.add(WorkSession(
                    companyId=uuid.UUID(company_id), stationId=uuid.UUID(station_id),
                    operatorId="tester", quantity=quantity,
                    startedAt=ended - timedelta(seconds=duration),
                    endedAt=ended, durationSec=duration,
                ))
            await s.commit()

    asyncio.run(go())


def test_a_quiet_line_has_nothing_to_boast_about(actor):
    a = actor()
    bootstrap_admin(a, "Quiet co")
    r = a.req("GET", "/share/improvement?window=1w")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "enough" in (body["reason"] or "")


def test_publishing_before_there_is_anything_to_publish_is_refused(actor):
    a = actor()
    bootstrap_admin(a, "Quiet co 2")
    assert a.req("POST", "/share/improvement", {"window": "1w"}).status_code == 409


def test_a_real_improvement_is_measured_published_and_rendered(actor):
    a = actor()
    bootstrap_admin(a, "Improving co")
    st = _station(a, "Assembly")

    # Last week: 30 lots of 2, 120 s each → 60 s per product.
    _seed_sessions(a.company, st, days_ago=9, count=30, quantity=2, duration=120)
    # This week: same work, 40 s per product — a third faster.
    _seed_sessions(a.company, st, days_ago=2, count=30, quantity=2, duration=80)

    r = a.req("GET", "/share/improvement?window=1w")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["available"] is True, preview
    assert preview["improved"] is True
    assert preview["before"] and preview["after"] and preview["delta"]

    r = a.req("POST", "/share/improvement", {"window": "1w"})
    assert r.status_code == 201, r.text
    card = r.json()
    slug = card["id"]
    assert re.fullmatch(r"[0-9a-f]{18}", slug)

    # The published card says exactly what the preview said.
    assert card["before"] == preview["before"]
    assert card["after"] == preview["after"]
    assert card["headline"] == preview["headline"]

    # And it is now a public page anybody can open.
    anon = Actor()
    page = anon.req("GET", f"/i/{slug}")
    assert page.status_code == 200
    assert preview["headline"] in page.text
    img = anon.req("GET", f"/i/{slug}/card.png")
    assert img.status_code == 200
    assert Image.open(io.BytesIO(img.content)).size == (1200, 630)


def test_a_line_that_got_slower_is_never_congratulated(actor):
    """The card may only ever say something got better. A metric moving the
    wrong way must fall through, not be reported with a flipped sign."""
    a = actor()
    bootstrap_admin(a, "Slowing co")
    st = _station(a, "Assembly")
    _seed_sessions(a.company, st, days_ago=9, count=30, quantity=2, duration=80)
    _seed_sessions(a.company, st, days_ago=2, count=30, quantity=2, duration=200)

    body = a.req("GET", "/share/improvement?window=1w").json()
    assert body["available"] is False, body


def test_noise_is_not_an_achievement(actor):
    """A 2% wobble between two weeks is not a result, and posting it as one is
    how a company embarrasses itself with our logo on the card."""
    a = actor()
    bootstrap_admin(a, "Steady co")
    st = _station(a, "Assembly")
    _seed_sessions(a.company, st, days_ago=9, count=30, quantity=2, duration=100)
    _seed_sessions(a.company, st, days_ago=2, count=30, quantity=2, duration=98)

    body = a.req("GET", "/share/improvement?window=1w").json()
    assert body["available"] is False, body


def test_the_numbers_come_from_the_database_not_the_request(actor):
    """Publishing takes a window and nothing else. If a body could carry the
    figures, "measured, not estimated" would be a lie the product tells for
    whoever asked."""
    a = actor()
    bootstrap_admin(a, "Honest co")
    st = _station(a, "Assembly")
    _seed_sessions(a.company, st, days_ago=9, count=30, quantity=2, duration=120)
    _seed_sessions(a.company, st, days_ago=2, count=30, quantity=2, duration=80)

    r = a.req("POST", "/share/improvement",
              {"window": "1w", "before": "99 h", "after": "1s", "headline": "We are gods"})
    assert r.status_code == 201, r.text
    assert r.json()["headline"] != "We are gods"
    assert r.json()["before"] != "99 h"


def test_improvement_is_company_scoped(actor):
    """One company's work must never show up in another's card."""
    a, b = actor(), actor()
    bootstrap_admin(a, "Busy co")
    bootstrap_admin(b, "Empty co")
    st = _station(a, "Assembly")
    _seed_sessions(a.company, st, days_ago=9, count=30, quantity=2, duration=120)
    _seed_sessions(a.company, st, days_ago=2, count=30, quantity=2, duration=80)

    assert a.req("GET", "/share/improvement?window=1w").json()["available"] is True
    assert b.req("GET", "/share/improvement?window=1w").json()["available"] is False


def test_improvement_requires_a_session(anon):
    assert anon.req("GET", "/share/improvement").status_code == 401
    assert anon.req("POST", "/share/improvement", {"window": "1w"}).status_code == 401


def test_an_operator_may_share_the_lines_result(actor):
    """Deliberately not admin-only: the people who made the number better are
    the ones with a reason to post it."""
    admin, worker = actor(), actor()
    bootstrap_admin(admin, "Crew co")
    add_member(admin, worker, role="user")
    st = _station(admin, "Assembly")
    _seed_sessions(admin.company, st, days_ago=9, count=30, quantity=2, duration=120)
    _seed_sessions(admin.company, st, days_ago=2, count=30, quantity=2, duration=80)

    assert worker.req("GET", "/share/improvement?window=1w").json()["available"] is True
    assert worker.req("POST", "/share/improvement", {"window": "1w"}).status_code == 201


def test_a_bad_window_is_rejected(actor):
    a = actor()
    bootstrap_admin(a, "Window co")
    assert a.req("GET", "/share/improvement?window=1y").status_code == 400


# ─── The path production actually takes ──────────────────────────────────────

def test_meta_tags_are_swapped_into_the_real_index_html():
    """In production the share page IS the SPA shell with its head rewritten.

    The tests above exercise the standalone fallback, because `FRONTEND_DIST`
    is unset here — so the branch that runs on taktline.com would otherwise be
    the only untested one. This runs the rewrite against the checked-in
    `index.html`, which is what the build emits a hashed-asset copy of.

    The specific failure it guards: the landing page's own `og:` block staying
    in the document. Both would then be present, the crawler would take one of
    them, and every shared link would sometimes show the generic cover.
    """
    import pathlib
    from app.routers import share as share_router

    index = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend" / "index.html").read_text(encoding="utf-8")

    stripped = share_router._STRIP.sub("", index)
    assert "og:image" not in stripped
    assert "twitter:card" not in stripped
    assert 'name="description"' not in stripped
    # Only the meta tags go: the app must still boot.
    assert "<div id=\"root\">" in stripped
    assert "/src/main.tsx" in stripped or "assets/" in stripped

    retitled = share_router._TITLE.sub("<title>X</title>", stripped, count=1)
    assert retitled.count("<title>") == 1
    assert "digital kanban &amp; MES" not in retitled

    doc = retitled.replace("<head>", "<head>" + share_router._meta_block(
        title="T", description="D", url="U", image="I", alt="A"), 1)
    assert doc.count('property="og:title"') == 1
    assert doc.count('property="og:image"') == 1


def test_the_meta_block_escapes_its_values():
    """Every value on this page is our own copy today. It stops being ours the
    moment a card carries a company's own text, and an unescaped quote there
    would break out of the attribute."""
    from app.routers.share import _meta_block
    out = _meta_block(title='He said "go" & <b>left</b>', description="d", url="u",
                      image="i", alt="a")
    assert "<b>" not in out
    assert 'content="He said &quot;go&quot; &amp; &lt;b&gt;left&lt;/b&gt;"' in out
