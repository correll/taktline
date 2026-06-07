# Veridion

Browser-based digital Kanban / Manufacturing Execution System (MES) that models production flow as a directed graph. Lot-cards travel with physical lots through locations, operators log work at stations via a mobile dashboard, and the system collects real-time OEE and takt-time statistics.

---

## Architecture

```
veridion/
├── backend/        FastAPI + MongoDB (async via Motor)
│   └── app/
│       ├── main.py             App entry-point, CORS, WebSocket broadcast, plugin lifespan
│       ├── db/                 Motor async connection helpers
│       ├── models/             Pydantic v2 models with domain validators
│       ├── routers/            REST endpoints (one file per domain object)
│       └── plugins/            Machine adapter plugin system (mock + base class)
└── frontend/       React 18 + TypeScript + Vite
    └── src/
        ├── api/                Axios wrappers for each backend resource
        ├── components/         Reusable UI — lot cards, map nodes, modals
        ├── domain/             Domain logic: graph.ts (DAG utils), invariants.ts (assertions)
        ├── store/              Zustand stores with immer + devtools middleware
        ├── theme/              Design tokens (colors, spacing, typography)
        └── views/              Full-page views
            ├── lots/           Kanban view — columns per location, topological order
            ├── dashboard/      Location selector (portrait / phone / iPad mode)
            ├── operator/       Single-station timer view with session recording
            ├── statistics/     OEE and takt-time per station
            └── settings/       Map config, processes/routes, stations, templates
```

### Domain model

| Concept | Description |
|---|---|
| **Location (Station)** | A physical place where manufacturing happens. Nodes in the process graph. |
| **Route** | A directed edge between two locations. `quantity` = units of upstream product consumed per assembly cycle. |
| **Process** | A named collection of routes forming a DAG. Multiple processes can coexist. |
| **Lot template** | Per-product card template. `startStationId` pins it to a source node (queue origin). |
| **Lot card (Card)** | Travels with a lot of physical products. Carries `totalQuantity` units distributed across `bins` (one bin per current location). Bin totals ≤ `totalQuantity` is a hard invariant. |
| **Session** | An operator's work timer at a station. Records `durationSec` and `quantity` processed; feeds OEE and takt-time aggregation. |
| **Queue / source node** | A location with no incoming routes — the origin point where new lot cards are injected. |
| **Merge node** | A location with 2+ incoming routes — where precursor lots are consumed and a new assembly lot card is created. |

### Key design decisions

- **Process graph is a DAG** — cycle detection runs at every route create/update (backend DFS + frontend pre-flight check). The topological sort that drives Kanban column order relies on this.
- **Quantity conservation** — `sum(card.bins) ≤ card.totalQuantity` is enforced by a Pydantic `model_validator` at creation; the `/move` endpoint preserves the invariant structurally.
- **Real-time sync** — the backend pushes all state changes over a single WebSocket (`/ws/events`); the frontend Zustand stores apply patches on receipt.
- **Plugin system** — each station can have a `adapterType` that maps to a plugin class. The mock adapter simulates machine state; real adapters (OPC-UA, Modbus, etc.) can be added without changing core logic.

### API surface

All endpoints are prefixed by resource:

| Prefix | Resource |
|---|---|
| `/stations` | Location CRUD + position updates |
| `/routes` | Route CRUD (with cycle/self-loop validation) |
| `/processes` | Process and lot-template CRUD |
| `/lot_templates` | Lot card template CRUD |
| `/cards` | Lot card CRUD + `/cards/{id}/move` |
| `/sessions` | Work session start/end + per-station stats |
| `/map_settings` | Floor plan URL, pixels-per-unit, unit calibration |
| `/global_settings` | App-wide settings |
| `/stats` | OEE and takt-time aggregation |
| `/uploads` | Static file serving for uploaded floor plan images |
| `/ws/events` | WebSocket broadcast channel |

Interactive docs: `http://localhost:8000/docs`

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| MongoDB | 6+ (local or Atlas) |

---

## Setup

### 1. Backend

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the API server (reload on file changes)
uvicorn app.main:app --reload --port 8000
```

MongoDB is expected at `mongodb://localhost:27017` by default. Set `MONGO_URI` in a `.env` file or as an environment variable to override.

### 2. Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The app is served at `http://localhost:3000` and proxies API calls to `http://localhost:8000`.

### 3. Production build

```bash
cd frontend
npm run build          # outputs to frontend/dist/
```

Serve `frontend/dist/` as static files, or point the FastAPI `StaticFiles` mount at it.

---

## Development notes

- **Hooks before early returns** — React function components must call all hooks unconditionally before any `return null` guard. This is enforced by the `react-hooks/rules-of-hooks` ESLint rule and is a documented invariant in `src/domain/invariants.ts`.
- **Domain assertions** — `src/domain/invariants.ts` exports typed `assert*` helpers that throw in development and log in production. Call them at store boundaries and in critical computation paths.
- **Graph utilities** — `src/domain/graph.ts` provides `hasCycle`, `wouldCreateCycle`, `sourceNodes`, `mergeNodes`, and `topoSort`. Use these instead of duplicating graph traversal logic.
- **Passive wheel events** — the map canvas attaches its wheel handler with `{ passive: false }` via an imperative `addEventListener` in a `useEffect`. Do not convert it to a React `onWheel` prop; React 17+ registers those as passive, which silently drops `preventDefault` and can cause scroll-induced layout shifts that break the hooks count.
