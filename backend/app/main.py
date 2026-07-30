import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from .core.ws_events import set_broadcast as set_card_event_broadcast
from .core.config import settings
from .core.csrf import CSRFMiddleware
from .core.ratelimit import limiter
from .core.security import hash_token
from .core.security_headers import SecurityHeadersMiddleware
from .db.connection import close_db, connect_db, parse_uuid, SessionLocal
from .db.tables import AuthSession, Membership, Station as StationRow
from .models.common import utcnow
from .models.machine_state import MachineState
from .plugins.registry import plugin_registry
from .routers import (
    admin, api_keys, auth, cards, companies, global_settings, invitations, lot_templates,
    export_xlsx, map_settings, members, merge, orders, platform, processes, reports, routes, sessions,
    client_errors, map_io, stations, stats,
)
from .core import sandbox_gc, usage
from .core.traffic import traffic
from .db.tables import SupportGrant


# ─── WebSocket broadcast manager (per-company) ───────────────────────────────

class ConnectionManager:
    """Sockets are bucketed by companyId so events never cross tenants."""

    def __init__(self) -> None:
        self._by_company: dict[uuid.UUID, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, company_id: uuid.UUID) -> None:
        await ws.accept()
        self._by_company.setdefault(company_id, []).append(ws)

    def disconnect(self, ws: WebSocket, company_id: uuid.UUID) -> None:
        conns = self._by_company.get(company_id)
        if conns:
            self._by_company[company_id] = [c for c in conns if c is not ws]

    async def broadcast(self, company_id: uuid.UUID, payload: dict) -> None:
        msg = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        delivered = 0
        for ws in list(self._by_company.get(company_id, [])):
            try:
                await ws.send_text(msg)
                delivered += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, company_id)
        usage.bump_ws(company_id, delivered)


ws_manager = ConnectionManager()


async def _broadcast_machine_state(state: MachineState) -> None:
    """Resolve the emitting station's company, then broadcast only to it."""
    station_uuid = parse_uuid(state.stationId)
    if station_uuid is None:
        return
    async with SessionLocal() as session:
        station = await session.get(StationRow, station_uuid)
    if station is None:
        return
    await ws_manager.broadcast(
        station.companyId,
        {"type": "machine_state", "payload": state.model_dump(mode="json")},
    )


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    plugin_registry.set_broadcast(_broadcast_machine_state)
    set_card_event_broadcast(ws_manager.broadcast)
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(StationRow).where(StationRow.adapterType.isnot(None))
        )).scalars().all()
        for st in rows:
            try:
                await plugin_registry.register(str(st.id), st.adapterType, st.adapterConfig or {})
            except Exception as exc:
                print(f"[warn] adapter start failed for station {st.name!r}: {exc}")
    usage.start_flush_task()
    sandbox_gc.start()
    yield
    sandbox_gc.stop()
    await usage.stop_flush_task()
    await plugin_registry.stop_all()
    await close_db()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Taktline Systems API", version="0.2.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(members.router)
app.include_router(invitations.router)
app.include_router(api_keys.router)

app.include_router(stations.router)
app.include_router(routes.router)
app.include_router(processes.router)
app.include_router(lot_templates.router)
app.include_router(cards.router)
app.include_router(stats.router)
app.include_router(sessions.router)
app.include_router(map_settings.router)
app.include_router(global_settings.router)
app.include_router(merge.router)
app.include_router(orders.router)
app.include_router(reports.router)
app.include_router(export_xlsx.router)
app.include_router(admin.router)
app.include_router(platform.router)
app.include_router(client_errors.router)
app.include_router(map_io.router)


# ── Traffic counter (feeds the platform dashboard) ────────────────────────────
# Global request volume only. Per-company usage is NOT counted here: the
# X-Company-Id header is unauthenticated client input, so counting it would let
# anyone inflate another tenant's meter. Attribution happens in the auth
# dependency once membership is verified (deps/auth.get_active_company).
@app.middleware("http")
async def _count_traffic(request, call_next):
    traffic.hit()
    return await call_next(request)

# Uploaded floor plans: Postgres is the source of truth, disk is a read-through
# cache (map_settings.uploads_router) — survives disk-less free-tier redeploys.
app.include_router(map_settings.uploads_router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "service": "taktline-api"}


def _origin_allowed(origin: str, websocket: WebSocket) -> bool:
    """CSWSH guard: is this handshake's Origin one of ours?

    An explicitly configured origin always passes (that is the cross-origin
    deployment: SPA on one host, API on another). **Same-origin** is also
    accepted — when the page that opened the socket is served by this very
    service, the request is by definition not cross-site, so there is nothing
    for CORS_ORIGINS to authorize. Without that, single-service hosting (the
    recommended shape: one container serving API + SPA) would silently lose
    every live board unless the operator remembered to restate their own URL in
    CORS_ORIGINS — a misconfiguration whose only symptom is a permanently amber
    connection light.

    The scheme comes from ``websocket.url``, which honours X-Forwarded-Proto
    only when uvicorn runs with --proxy-headers; behind a TLS-terminating load
    balancer without it the scheme reads ``ws`` while the browser sends
    ``https``, so both spellings of our own host are accepted.
    """
    if origin in settings.cors_origin_list:
        return True
    host = websocket.headers.get("host")
    return bool(host) and origin in (f"https://{host}", f"http://{host}")


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """Authenticated, company-scoped event stream.

    The session cookie is sent automatically on the same-origin handshake;
    the target company arrives as ?companyId=. Membership is verified before
    the socket is accepted.
    """
    # Reject cross-site WebSocket connections (CSWSH) — a browser always sends
    # Origin; only our configured app origins are allowed. Non-browser clients
    # (no Origin header) are permitted.
    origin = websocket.headers.get("origin")
    if origin is not None and not _origin_allowed(origin, websocket):
        await websocket.close(code=4403)
        return

    raw = websocket.cookies.get(settings.session_cookie_name)
    company_uuid = parse_uuid(websocket.query_params.get("companyId"))
    if not raw or company_uuid is None:
        await websocket.close(code=4401)
        return

    async with SessionLocal() as session:
        sess_row = (await session.execute(
            select(AuthSession).where(AuthSession.tokenHash == hash_token(raw))
        )).scalars().first()
        if sess_row is None or sess_row.expiresAt <= utcnow():
            await websocket.close(code=4401)
            return
        membership = (await session.execute(
            select(Membership).where(
                Membership.companyId == company_uuid,
                Membership.userId == sess_row.userId,
            )
        )).scalars().first()
        if membership is None:
            # Impersonating platform staff may stream this company's events too.
            grant = (await session.execute(
                select(SupportGrant).where(
                    SupportGrant.userId == sess_row.userId,
                    SupportGrant.companyId == company_uuid,
                    SupportGrant.endedAt.is_(None),
                    SupportGrant.expiresAt > utcnow(),
                )
            )).scalars().first()
            if grant is None:
                await websocket.close(code=4403)
                return

    await ws_manager.connect(websocket, company_uuid)
    try:
        while True:
            await websocket.receive_text()   # keep-alive / client ping
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, company_uuid)


# ─── Optional: serve the built SPA from this service (same-origin hosting) ─────
# Registered last so it never shadows the API routers, /docs, or /uploads. Only
# active when FRONTEND_DIST points at a built frontend.
if settings.frontend_dist:
    from fastapi.responses import FileResponse

    _DIST = Path(settings.frontend_dist).resolve()
    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        candidate = (_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_DIST):
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
