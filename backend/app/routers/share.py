"""Public share pages and card images, plus the improvement card's own API.

`GET /i/{id}` is the only public, unauthenticated HTML this service serves, and
it exists because a share is a URL pasted into a post: what appears under it is
decided by `<meta property="og:…">` in the *first* response, fetched by a
crawler that runs no JavaScript. The SPA cannot do it, so this route serves the
built `index.html` with the item's own tags swapped in — the crawler gets the
right preview, the human gets the full animated page.

Registered before the SPA catch-all in `main.py`, which is what lets it win.
"""

from __future__ import annotations

import html
import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import share as share_core
from ..core.analysis import _mmss
from ..core.config import settings
from ..db.connection import SESSION_SCOPE, get_session
from ..db.tables import ShareCard
from ..deps.auth import CompanyContext, get_active_company
from ..models.common import utcnow
from .sessions import _TREND_WINDOWS, _station_metrics, _work_schedule

router = APIRouter(tags=["share"])

_DIST = Path(settings.frontend_dist).resolve() if settings.frontend_dist else None


# ─── The public page ─────────────────────────────────────────────────────────

def _site_base() -> str:
    return settings.frontend_base_url.rstrip("/")


_STRIP = re.compile(
    r"""\s*<meta\s+(?:property="og:[^"]*"|name="twitter:[^"]*"|name="description")[^>]*>""",
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)


def _meta_block(*, title: str, description: str, url: str, image: str,
                alt: str) -> str:
    e = html.escape
    return (
        f'<meta name="description" content="{e(description)}" />'
        f'<meta property="og:type" content="article" />'
        f'<meta property="og:site_name" content="Taktline" />'
        f'<meta property="og:url" content="{e(url)}" />'
        f'<meta property="og:title" content="{e(title)}" />'
        f'<meta property="og:description" content="{e(description)}" />'
        f'<meta property="og:image" content="{e(image)}" />'
        f'<meta property="og:image:width" content="1200" />'
        f'<meta property="og:image:height" content="630" />'
        f'<meta property="og:image:alt" content="{e(alt)}" />'
        f'<meta name="twitter:card" content="summary_large_image" />'
        f'<meta name="twitter:title" content="{e(title)}" />'
        f'<meta name="twitter:description" content="{e(description)}" />'
        f'<meta name="twitter:image" content="{e(image)}" />'
        f'<link rel="canonical" href="{e(url)}" />'
    )


def _page(*, title: str, description: str, url: str, image: str, alt: str,
          noscript: str) -> HTMLResponse:
    """The item's meta tags on the SPA shell, or a standalone page when this
    service isn't hosting the frontend (dev, where Vite serves it)."""
    meta = _meta_block(title=title, description=description, url=url,
                       image=image, alt=alt)
    e = html.escape
    body = (
        f'<noscript><article><h1>{e(title)}</h1><p>{e(noscript)}</p>'
        f'<p><a href="{e(_site_base())}/">Taktline — digital kanban for small '
        f'manufacturers</a></p></article></noscript>'
    )

    index = _DIST / "index.html" if _DIST else None
    if index is not None and index.is_file():
        doc = index.read_text(encoding="utf-8")
        doc = _STRIP.sub("", doc)
        doc = _TITLE.sub(f"<title>{e(title)} · Taktline</title>", doc, count=1)
        doc = doc.replace("<head>", "<head>" + meta, 1)
        doc = doc.replace("</body>", body + "</body>", 1)
        return HTMLResponse(doc)

    return HTMLResponse(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{e(title)} · Taktline</title>{meta}</head>"
        f'<body style="background:#121110;color:#EFEDE7;font-family:system-ui;'
        f'margin:0;padding:48px"><img src="{e(image)}" alt="{e(alt)}" '
        f'style="max-width:100%;border-radius:12px">{body}</body></html>'
    )


def _summary(text: str, limit: int = 200) -> str:
    """OG descriptions are truncated hard by every network, so cut on a word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-") + "…"


async def _stored(session: AsyncSession, slug: str) -> Optional[ShareCard]:
    return (await session.execute(
        select(ShareCard).where(ShareCard.slug == slug)
    )).scalars().first()


def _improvement_of(row: ShareCard) -> share_core.Improvement:
    return share_core.Improvement(**row.payload)


@router.get("/i/{item_id}", include_in_schema=False)
async def share_page(item_id: str,
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    if not share_core.ID_RE.match(item_id):
        raise HTTPException(404, "No such card")
    url = f"{_site_base()}/i/{item_id}"
    image = f"{_site_base()}/i/{item_id}/card.png"

    item = share_core.find(item_id)
    if item is not None:
        title = item.headline if item.kind == "concept" else item.eyebrow
        return _page(
            title=title,
            description=_summary(item.headline if item.kind == "tip" else item.body),
            url=url, image=image, alt=_summary(item.headline, 110),
            noscript=item.headline if item.kind == "tip"
                     else f"{item.headline} {item.body}",
        )

    row = await _stored(session, item_id)
    if row is None:
        raise HTTPException(404, "No such card")
    imp = _improvement_of(row)
    return _page(
        title=imp.headline,
        description=f"{imp.metric}: {imp.before} → {imp.after} ({imp.delta}). {imp.caption}.",
        url=url, image=image, alt=f"{imp.metric} {imp.before} to {imp.after}",
        noscript=f"{imp.headline}. {imp.metric} went from {imp.before} to "
                 f"{imp.after} — {imp.delta}. {imp.caption}.",
    )


@router.get("/i/{item_id}/card.png", include_in_schema=False)
async def share_card_png(item_id: str,
                         session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    if not share_core.ID_RE.match(item_id):
        raise HTTPException(404, "No such card")
    item = share_core.find(item_id)
    if item is not None:
        png = share_core.render_card(item)
    else:
        row = await _stored(session, item_id)
        if row is None:
            raise HTTPException(404, "No such card")
        png = share_core.render_improvement(_improvement_of(row))
    # Long cache: the catalogue is immutable per deploy and a stored card never
    # changes. Crawlers refetch the image for years after the post.
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400, immutable"})


# ─── The improvement card ────────────────────────────────────────────────────

# What "an improvement" is allowed to mean. Each entry says which way is better
# and how to phrase it, so the card cannot congratulate a line for getting
# slower. Deliberately line-level: a single station improving while the line
# does not is not a result worth posting, and picking the best station would
# make it trivially game-able.
_METRICS = [
    ("lineCycle", "Line cycle time", False,
     "We cut the time between finished pieces by {pct}%"),
    ("cycle", "Cycle time", False,
     "We cut the work time per product by {pct}%"),
    ("oee", "Utilisation", True,
     "We raised utilisation by {pct}%"),
]

_LABEL = {"1h": "hour", "1d": "day", "1w": "week", "1m": "30 days"}

# Below this, the difference is noise dressed as an achievement.
_MIN_UNITS = 20
_MIN_PCT = 8.0


class ImprovementOut(BaseModel):
    available: bool
    reason: Optional[str] = None
    metric: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    delta: Optional[str] = None
    caption: Optional[str] = None
    headline: Optional[str] = None
    improved: Optional[bool] = None
    window: Optional[str] = None


class ImprovementPublish(BaseModel):
    window: str = Field(default="1w")


def _aggregate(metrics: dict) -> dict:
    """Roll per-station metrics up to the line.

    Weighted by units, because a station that ran three lots must not swing the
    plant's number as hard as one that ran three hundred. Warehouses are
    excluded for the same reason they are excluded everywhere else: shelf time
    is not utilisation.
    """
    units = 0
    working = 0.0
    lc_num = 0.0
    lc_den = 0
    oee_num = 0.0
    oee_den = 0
    for row in metrics.values():
        if row.get("isWarehouse"):
            continue
        u = row.get("totalUnits") or 0
        units += u
        working += row.get("totalWorkingSec") or 0.0
        if row.get("lineCycleTimeSec") is not None and u > 0:
            lc_num += row["lineCycleTimeSec"] * u
            lc_den += u
        if row.get("oee") is not None and u > 0:
            oee_num += row["oee"] * u
            oee_den += u
    return {
        "units": units,
        "cycle": (working / units) if units else None,
        "lineCycle": (lc_num / lc_den) if lc_den else None,
        "oee": (oee_num / oee_den) if oee_den else None,
    }


def _best(now: dict, before: dict, window: str) -> ImprovementOut:
    if now["units"] < _MIN_UNITS or before["units"] < _MIN_UNITS:
        return ImprovementOut(
            available=False,
            reason=f"Not enough finished work yet to compare two {_LABEL[window]} "
                   f"periods — {_MIN_UNITS} products in each is the minimum.",
        )

    best: Optional[ImprovementOut] = None
    best_pct = 0.0
    for key, label, higher_is_better, headline in _METRICS:
        a, b = now.get(key), before.get(key)
        if a is None or b is None or b == 0:
            continue
        change = (a - b) / b * 100.0
        pct = change if higher_is_better else -change
        if pct < _MIN_PCT or pct <= best_pct:
            continue
        fmt = (lambda v: f"{v * 100:.0f}%") if key == "oee" else _mmss
        best_pct = pct
        best = ImprovementOut(
            available=True, metric=label, before=fmt(b), after=fmt(a),
            delta=f"{pct:.0f}% better" if key == "oee" else f"{pct:.0f}% faster",
            caption=f"Measured in Taktline · last {_LABEL[window]} against the one before",
            headline=headline.format(pct=round(pct)), improved=True, window=window,
        )

    if best is None:
        return ImprovementOut(
            available=False,
            reason=f"Nothing moved by more than {_MIN_PCT:.0f}% against the previous "
                   f"{_LABEL[window]}. Come back once a change has had time to show.",
        )
    return best


async def _measure(session: AsyncSession, ctx: CompanyContext, window: str) -> ImprovementOut:
    span = _TREND_WINDOWS.get(window)
    if span is None:
        raise HTTPException(400, f"window must be one of {sorted(_TREND_WINDOWS)}")
    schedule, tzname = await _work_schedule(session, ctx.company_id)
    now = utcnow()
    current = await _station_metrics(session, ctx.company_id, schedule, tzname,
                                     now - span, now)
    prior = await _station_metrics(session, ctx.company_id, schedule, tzname,
                                   now - span * 2, now - span)
    return _best(_aggregate(current), _aggregate(prior), window)


@router.get("/share/improvement", response_model=ImprovementOut)
async def preview_improvement(window: str = "1w",
                              ctx: CompanyContext = Depends(get_active_company),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """What this line could honestly claim right now. Nothing is published."""
    return await _measure(session, ctx, window)


@router.post("/share/improvement", response_model=dict, status_code=201)
async def publish_improvement(body: ImprovementPublish,
                              request: Request,
                              ctx: CompanyContext = Depends(get_active_company),
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """Publish the before/after at a permanent public URL.

    Recomputed here rather than accepted from the client: the numbers on a card
    that says "measured, not estimated" must come from the database, not from a
    request body anyone could edit. The window is the only input.
    """
    result = await _measure(session, ctx, body.window)
    if not result.available:
        raise HTTPException(409, result.reason or "Nothing to share yet")

    row = ShareCard(
        slug=secrets.token_hex(9),
        companyId=ctx.company_id,
        createdBy=ctx.user.id,
        payload={
            "metric": result.metric, "before": result.before, "after": result.after,
            "delta": result.delta, "caption": result.caption,
            "headline": result.headline, "improved": True,
        },
    )
    session.add(row)
    await session.flush()
    return {"id": row.slug, "url": f"{_site_base()}/i/{row.slug}", **row.payload}
