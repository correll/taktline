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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
async def _viewer_is_a_member(request, session, subject_id) -> Optional[dict]:
    """Is whoever is asking a signed-in member of the company that owns this job?

    **The token never authorises work.** It is a read capability handed to a
    customer, and a customer must not be able to start a timer on somebody's
    shop floor by opening a link twice. Working requires a real session and real
    membership, checked here from scratch — the token only decides what may be
    *read*.

    Returns the station and card to act on, or None. None is also what an
    anonymous visitor gets, so the response says nothing about whether the
    company exists.
    """
    from sqlalchemy import select

    from ..db.tables import Card as CardRow, Membership, ProductionOrder
    from ..deps.auth import get_current_user

    try:
        user = await get_current_user(request, session)
    except Exception:
        return None                       # not signed in — the normal case here

    order = await session.get(ProductionOrder, subject_id)
    card = None if order is not None else await session.get(CardRow, subject_id)
    company_id = order.companyId if order is not None else (card.companyId if card else None)
    if company_id is None:
        return None

    member = (await session.execute(
        select(Membership).where(Membership.companyId == company_id,
                                 Membership.userId == user.id)
    )).scalars().first()
    if member is None:
        return None

    # An order can have seeded several lots; a QR on one card is about that card.
    if card is None:
        card = (await session.execute(
            select(CardRow).where(CardRow.orderId == subject_id)
            .order_by(CardRow.createdAt)
        )).scalars().first()
    if card is None:
        return None

    bins = card.bins or {}
    station = max(bins, key=lambda k: (bins[k] or {}).get("count", 0), default=None)
    if station is None:
        return None
    return {"cardId": str(card.id), "stationId": str(station),
            "units": int((bins[station] or {}).get("count", 0) or 0)}


#: Readable from any origin. It is already public and token-guarded, and this
#: is what lets one company's board show a supplier's progress: the *browser*
#: fetches it, so this server never follows a URL a user typed — which is the
#: whole SSRF class, avoided rather than fenced. A cross-origin fetch sends no
#: cookies, so such a reader can only ever get the customer view: `work` comes
#: back null however signed-in they are somewhere else.
_PUBLIC_CORS = {"Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Cache-Control": "no-store"}


@router.options("/track/{order}/{token}", include_in_schema=False)
async def track_preflight(order: str, token: str):
    return Response(status_code=204, headers=_PUBLIC_CORS)


@router.get("/track/{order}/{token}")
async def track_json(order: str, token: str, request: Request, response: Response,
                     session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The same data as the page, for the SPA to render once it has booted.

    `work` is present only for a signed-in member of the owning company, so an
    operator who scans the QR on a lot card lands on the same page a customer
    would and gets a way into the Operator view — while the customer sees
    nothing at all about it.
    """
    t = await _load(session, order, token)
    work = await _viewer_is_a_member(request, session, require_uuid(order, "Not found"))
    response.headers.update(_PUBLIC_CORS)
    return {
        "work": work,
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


@router.get("/o/{order}/{token}/qr.svg", include_in_schema=False)
async def track_qr(order: str, token: str,
                   session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    """The tracking link as a QR code, for printing on the lot card itself.

    SVG rather than PNG: a lot card gets stuck to a bin and scanned across a
    shop, and vector stays sharp whether it comes out at 25mm on a label or
    100mm on a sheet of A4. Guarded exactly like the page — same token, same
    404 — so it cannot be used to discover whether a job exists.
    """
    import io

    import qrcode
    import qrcode.image.svg

    await _load(session, order, token)          # authorise before drawing
    code = qrcode.QRCode(
        # Medium correction: a label on a shop floor picks up grease and
        # scuffs, and the URL is short enough that the extra redundancy costs
        # almost nothing.
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2,
    )
    code.add_data(f"{_base()}/o/{order}/{token}")
    code.make(fit=True)
    buf = io.BytesIO()
    code.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


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
