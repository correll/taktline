import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db.connection import connect_db, close_db, get_db
from .routers import stations, routes, processes, lot_templates, cards, stats, sessions, map_settings, global_settings, merge
from .plugins.registry import plugin_registry
from .models.machine_state import MachineState


# ─── WebSocket broadcast manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]

    async def broadcast(self, payload: dict) -> None:
        msg = json.dumps(payload, default=str)
        dead: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def _broadcast_machine_state(state: MachineState) -> None:
    await ws_manager.broadcast({"type": "machine_state", "payload": state.model_dump(mode="json")})


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    plugin_registry.set_broadcast(_broadcast_machine_state)
    db = get_db()
    async for doc in db.stations.find({"adapterType": {"$ne": None}}):
        try:
            await plugin_registry.register(
                str(doc["_id"]),
                doc["adapterType"],
                doc.get("adapterConfig", {}),
            )
        except Exception as exc:
            print(f"[warn] adapter start failed for station {doc.get('name')!r}: {exc}")
    yield
    await plugin_registry.stop_all()
    await close_db()


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Veridion Systems API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Serve uploaded floor plan files
_UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
_UPLOADS_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "service": "veridion-api"}


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive / client ping
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
