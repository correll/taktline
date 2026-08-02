"""`/o/{order}/{token}` — where a shop's own customer follows their order.

The only page in Taktline written for somebody who is not a customer of ours.
That shapes every decision in it: it must load with no account, say one useful
thing, leak nothing else, and make clear whose software it is without getting in
the way of the answer the visitor came for.

Server-rendered for the same reason `/i/<slug>` is: these get pasted into
emails, WhatsApp and Teams, all of which fetch the URL and show a preview from
`<meta property="og:…">` before any browser runs. A tracking link whose preview
says "Taktline" and nothing else is a worse answer than the one the shop already
gives on the phone.
"""

from __future__ import annotations

import html
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import tracking
from ..core.config import settings
from ..db.connection import SESSION_SCOPE, get_session, require_uuid

router = APIRouter(tags=["tracking"])


def _base() -> str:
    return settings.frontend_base_url.rstrip("/")


async def _load(session: AsyncSession, order: str, token: str) -> tracking.Tracked:
    """404 for every refusal.

    Unknown order, wrong token and tracking-switched-off are deliberately
    indistinguishable: a different answer for a real order would turn this into
    a way to find out whether a company has one.
    """
    found = await tracking.resolve(session, require_uuid(order, "Not found"), token)
    if found is None:
        raise HTTPException(404, "Not found")
    return found


# NOT "/api/track/...": the `/api` prefix exists only in the Vite dev proxy,
# which strips it before the request arrives. In production the client's
# baseURL is empty and it calls this origin directly (see the Dockerfile
# note on VITE_API_URL), so the path here is what both reach.
@router.get("/track/{order}/{token}")
async def track_json(order: str, token: str,
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The same data as the page, for the SPA to render once it has booted."""
    t = await _load(session, order, token)
    return {
        "reference": t.reference,
        "product": t.product,
        "quantity": t.quantity,
        "quantityDone": t.quantity_done,
        "status": t.status,
        "percent": t.percent,
        "showSteps": t.show_steps,
        "stepIndex": t.step_index,
        "stepTotal": t.step_total,
        "steps": ([{"name": s.name, "units": s.units, "done": s.done,
                    "current": s.current} for s in t.steps]
                  if t.steps is not None else None),
        "updatedAt": t.updated_at.isoformat() if t.updated_at else None,
    }


def _headline(t: tracking.Tracked) -> str:
    if t.status == "completed":
        return f"{t.product} · {t.reference} is complete"
    if t.status == "cancelled":
        return f"{t.product} · {t.reference} was cancelled"
    return f"{t.product} · {t.reference} is {t.percent}% through the line"


def _summary(t: tracking.Tracked) -> str:
    # Same reasoning as the page: "0 of 24 complete" under a headline saying 50%
    # reads as a contradiction to the person the link was sent to.
    parts = [f"{t.quantity} in production" if t.quantity_done == 0
             else f"{t.quantity_done} of {t.quantity} complete"]
    if t.show_steps and t.step_index is not None and t.step_total:
        parts.append(f"step {t.step_index + 1} of {t.step_total}")
    return " · ".join(parts) + "."


@router.get("/o/{order}/{token}", include_in_schema=False)
async def track_page(order: str, token: str,
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    t = await _load(session, order, token)
    e = html.escape
    url = f"{_base()}/o/{order}/{token}"
    title = _headline(t)
    description = _summary(t)

    meta = (
        f'<meta name="description" content="{e(description)}" />'
        f'<meta name="robots" content="noindex, nofollow" />'
        f'<meta property="og:type" content="website" />'
        f'<meta property="og:site_name" content="Taktline" />'
        f'<meta property="og:url" content="{e(url)}" />'
        f'<meta property="og:title" content="{e(title)}" />'
        f'<meta property="og:description" content="{e(description)}" />'
        f'<meta name="twitter:card" content="summary" />'
        f'<meta name="twitter:title" content="{e(title)}" />'
        f'<meta name="twitter:description" content="{e(description)}" />'
    )
    # noindex is deliberate. The token makes the URL unguessable, but a customer
    # who forwards it into a public forum should not also be handing a search
    # engine a permanent copy of somebody's production status.

    noscript = (
        f"<noscript><article><h1>{e(title)}</h1><p>{e(description)}</p>"
        f'<p><a href="{e(_base())}/">Tracking by Taktline</a></p></article></noscript>'
    )

    from .share import _DIST

    index = _DIST / "index.html" if _DIST else None
    if index is not None and index.is_file():
        from .share import _STRIP, _TITLE

        doc = index.read_text(encoding="utf-8")
        doc = _STRIP.sub("", doc)
        doc = _TITLE.sub(f"<title>{e(title)}</title>", doc, count=1)
        doc = doc.replace("<head>", "<head>" + meta, 1)
        doc = doc.replace("</body>", noscript + "</body>", 1)
        return Response(doc, media_type="text/html")

    return Response(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{e(title)}</title>{meta}</head>"
        f'<body style="font-family:system-ui;margin:0;padding:48px">{noscript}</body></html>',
        media_type="text/html",
    )
