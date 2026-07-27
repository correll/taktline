# Overview

Taktline is a browser-based digital Kanban system that allows model manufacturing flow as a graph. We are using the following conventions:

Locations: this is where manufacturing activities happen. 

Lot-cards (Kanban cards): are attached to physical products. One lot card can also be attached to a lot of products, i.e. it carries the number of products. Lot-cards travel with the lots through the stations. 

Process: manufacturing is organized as a graph with locations as nodes, and transfer between locations as edges.

Products: products can be both final products as well as intermediate product. The user can create templates for the lot cards that go with the different products. Each product has an origination location that is paired with a queue. 

Queues: the leafs of the manufacturing graph serve as queues where products either originate or end up. Each location at a leaf of a tree that has no incoming edges can serve as originating location, which is tied to the product template. Each location at a leaf of a tree that has no outgoing edges doubles as a warehouse.

Splitting: the mirror of merging. Within a process, a location with **two or more outgoing routes** is a split — a disassembly. Advancing a lot out of it consumes the source units and mints one new lot per branch, each pinned to that branch's originating template and inheriting the lot code, with the branch's edge weight saying how many pieces it yields (one steel bar → four tubes + one offcut). Alternative "either/or" routing is **not** a split: it is modelled as a **separate process**, so branches only ever count within the card's own process. Pulling through a split recombines demand — four tubes order one bar, and a diamond (one source feeding two branches that merge again) pulls a single source lot.

Merging: some products are made from precursors. These result from merging two or or more precursor products. In this case, the precursor product lot cards are discarded (or optionally put back into the queue), and a new lot card is created. Only locations at ßwhich multiple branches come together can serve as originating stations for such lot cards. Conversely, such lot cards can not be created directly, and attempting to do so will create precursor lot cards in the queues that lead up to this location.

Edge weight: a weight only means something where the graph branches. On a **merge feed** (a route into a station with 2+ incoming routes) it is how many precursor units one assembly consumes — a final assembly might need one of product A, three of product B and 10 of product C. On a **split branch** (a route out of a station with 2+ outgoing routes) it is the mirror image: how many pieces one upstream unit becomes, so advancing a lot along it multiplies the card (one steel bar cut into four tubes) and pulling four tubes orders exactly one bar. Elsewhere a lot moves 1:1 and the weight is forced to 1. 

Map view: the map view shows all the locations and the process graph overlaid on a PNG image of a factory floor. A "heatmap" shows how busy individual stations are. The map is either in meters or in feet and the user can specify how many pixels correspond to a unit. A scale in the lower left corner indicates the actual scale. 

Kanban view: the kanban view shows a flattened version of the process graph. with one column per location. Each column shows all the lot-cards at this location. 

Dashboards: if the browser window is in vertical orientation such as on a phone or ipad, a dashboard view is shown. The dashboard view shows all available locations and allows a user to "log in". The user then sees a single column with all the lot cards that are at this location. The user can select a lot card, chose the number of products that they work on and press start. Then, a timer starts recording the time, until the user presses stop.

Statistics: the process collects timing based on lot and per product on each station. Relevant metrics are: Takt-Time, the average time per product at each station, Overall Equipment Efficiency (OEE) as the ratio of time where the timer at a location is running vs. total time, number of transport events when lot cards travel from one location to another and overal transport in meters. 

# Engineering conventions

## Persistence layer (PostgreSQL + SQLAlchemy async)

The backend uses **PostgreSQL** via **SQLAlchemy 2.0 async ORM + asyncpg**, with **Alembic** for migrations. (It was previously MongoDB/Motor.)

- **ORM tables** live in `app/db/tables.py`; **Pydantic models** in `app/models/` remain the API request/response schemas. Each router has small `_to_*(row)` helpers that map an ORM row to its Pydantic model.
- **IDs** are UUID primary keys (app-generated via `uuid.uuid4`), serialized to the API as opaque `_id` strings. The frontend treats them as opaque, so nothing there changed. Router path params / FK fields arrive as strings and are parsed with `parse_uuid` / `require_uuid` / `optional_uuid` from `app/db/connection.py`.
- **Transactions**: `get_session` (the FastAPI dependency) wraps each request in one transaction — commit on success, rollback on any exception. This is what makes multi-write endpoints (`/merge`, `/cards/{id}/move`, session start auto-close) atomic. Endpoints `session.add(...)` / mutate ORM objects and `await session.flush()`; the commit happens once at request end.
- **Constraints move into the DB**: FKs with `ON DELETE CASCADE`/`SET NULL`, `CHECK` constraints (`quantity >= 1`, route `load <> unload`, card `totalQuantity >= 1`, status/unit enums), and a unique `(processId, load, unload)` route edge. The one invariant still enforced only in Pydantic is `sum(card.bins) <= totalQuantity` (a `CHECK` can't sum JSONB without a subquery).
- **Audit log exception**: `card_events.cardId` is a plain indexed string with **no FK** — it must retain the `'deleted'` event recorded *after* a card is removed.
- **Schema changes**: edit `app/db/tables.py`, then `alembic revision --autogenerate -m "..."` and `alembic upgrade head`. `DATABASE_URL` (env, default `postgresql+asyncpg://localhost:5432/taktline`) drives both the app and Alembic.

## Production orders & ERP integration (outbox)

`ProductionOrder` is the anchor for external integration and the completion loop; **connectors** map ERP/store orders onto it — no ERP code lives in the core. The integration surface is a **frozen canonical contract** so connectors stay thin: `POST /orders` (release), `GET /orders/outbox?status=pending` + `POST /orders/outbox/{id}/ack` (drain completions), `POST /orders/cancel` (cancel by `{source, externalRef}`).

- **Release** (`POST /orders`): wraps the merge **pull** — for an assembled product it seeds precursor lots at the leaf source queues; for a single-source product it creates one lot at the origin. Every created lot is tagged with `card.orderId` and stamped with a **lot code** (`card.lotNum`) taken from the order: an explicit `lotCode` if the connector sent one (a human ERP reference like Shopify `#1001` / Odoo `MO/00042`), else the `externalRef`, so every physical Kanban card traces back to its ERP order (bare manual releases with neither get a generated code). The code carries through the merge — when every consumed precursor shares one code the finished assembly keeps it. **Idempotent** on `(companyId, source, externalRef)` — a redelivered ERP webhook returns the existing order, never a second run. Core release/cancel logic is factored into `orders._release_order` / `orders._cancel_order` (reused by the endpoints, CSV import, and cancel-by-ref).
- **Attribution through merges**: `merge.perform_merge` propagates `orderId` onto the new assembly card when all consumed precursors agree on one order (ambiguous → null). This is how a finished good stays attributed across multi-level merges.
- **Completion**: `cards._record_order_progress` (called from `move_card` and `advance_card`) fires when order-tagged units arrive at a **finished-goods leaf** (a station with no outgoing routes). It credits `quantityDone`, flips status to `completed`, and writes an **`IntegrationOutbox`** row — in the *same transaction* as the move (transactional outbox = no lost/duplicate "done" events, which in an ERP means double inventory posting).
- **Delivery**: a connector polls `GET /orders/outbox?status=pending`, delivers to the ERP, then `POST /orders/outbox/{id}/ack`. `/orders/{id}/cancel` (or `/orders/cancel` by ref) scraps in-flight lots and emits `order.cancelled`; ack is idempotent and re-cancelling is a no-op, so redelivered webhooks are safe.

### Scoped API keys & the auth model for integrations

`ApiKey` rows (`tk_…`, SHA-256 hashed at rest, prefix shown for display, revocable, company-scoped) authenticate integrations — no admin login. `deps/auth.require_scope(scope, session_role=…)` is the dependency factory: it accepts a Bearer/`X-Api-Key` key carrying `scope`, **or** a session (a key resolves its own company, so `X-Company-Id` is ignored and tenant isolation is automatic). A key with no cookie skips CSRF. Scope catalog (`models/apikey.AVAILABLE_SCOPES`, surfaced at `GET /api-keys/scopes`):
- `orders` — release / drain / cancel (`require_orders_access` = `require_scope("orders")`).
- `cards:advance` — `POST /cards/{id}/advance` (**scan-to-advance**: a scanner/print station hits it after reading a lot label) and `GET /cards/{id}/label` (ZPL with a Code128 of the card id).
- `reports` — read-only BI feeds `GET /reports/orders` + `/reports/throughput` (Power BI/Grafana).

Other on-ramps: **CSV import** (`POST /orders/import`, multipart) releases a batch from a spreadsheet — each row in its own SAVEPOINT so one bad row is reported, not fatal; idempotent per `(source, externalRef)`.

### Connectors (`connectors/taktline_connect/`)

A standalone package (its own venv; only `requests` + `requests-oauthlib`), **not** imported by the backend. `core.Connector` is ERP-agnostic: each cycle it **releases** (`list_orders` → `POST /orders`), **cancels** (optional `list_cancellations` → `POST /orders/cancel`, the Shopify/Woo refund path), then **drains** completions. An ERP client is one file implementing `list_orders` (+ optional `list_cancellations`/`mark_done`/`cancel`) and a `build(cfg)`; parsing is factored into a pure `orders_from_*` for unit tests. Shipped: `odoo`, `netsuite`, `shopify`, `woocommerce`, `qbo`, `xero`, `shipstation`, `generic` (poll any JSON endpoint) — run `python -m taktline_connect <name>`. Products map by config (`PRODUCT_MAPPING`: ERP ref → Taktline template **id**), so a key only ever needs the `orders` scope. Tests: `tests/test_core.py` (orchestration), `test_clients.py` (parsing), `test_integration_http.py` (real clients + `Connector` over a live in-process mock of the ERP + Taktline, incl. OAuth refresh/401-retry).

- **Boundaries**: the ERP owns the BoM + inventory; Taktline owns the flow graph + execution. Keep them joined only through the product→template mapping (in the connector), not by auto-generating the graph from the BoM.

## Datetime / timezone handling

Postgres `TIMESTAMP WITH TIME ZONE` columns come back **tz-aware** through asyncpg, so the naive-datetime normalization the old Motor code needed (`.replace(tzinfo=timezone.utc)` in every `_to_*()` helper) is **no longer required** — datetime arithmetic and Pydantic serialization (`+00:00` suffix) just work.

**Rule**: keep datetime columns as `DateTime(timezone=True)` and generate values with `utcnow()` (`datetime.now(timezone.utc)`) so everything stays UTC-aware end to end.

**Frontend rule (belt-and-suspenders)**: when parsing a datetime string from the API, append `Z` if no timezone suffix is present. With tz-aware backend datetimes this is now a no-op, but it costs nothing and guards against any bare string:

```ts
const iso = raw.endsWith('Z') || raw.includes('+') ? raw : raw + 'Z'
const date = new Date(iso)
```

## Authentication & multi-tenancy

The app is authenticated and multi-tenant. Users belong to one or more **companies** with a per-company **role**, one of three tiers ordered by privilege — `user` < `admin` < `super_admin` (see `deps/auth.ROLE_RANK`); every domain row carries a `companyId`.

- **Sessions**: httpOnly cookie (`taktline_session`) holding an opaque token; only its SHA-256 hash is stored (`auth_sessions`). Rotated on login, revoked on logout/password-reset. Config, hashing (argon2id), the mailer, CSRF, and rate limiting live in `app/core/`.
- **CSRF**: double-submit. `app/core/csrf.py` middleware requires header `X-CSRF-Token` to equal the readable `taktline_csrf` cookie on unsafe methods **when a session cookie is present** (public auth calls are exempt). The frontend axios interceptor (`src/api/client.ts`) attaches it automatically.
- **Request dependencies** (`app/deps/auth.py`), composed with `get_session`:
  - `get_current_user` — resolves the session cookie → `User` (401).
  - `get_active_company` — validates the `X-Company-Id` header against membership → `CompanyContext(company_id, role, user)` (403 non-member).
  - `require_admin` — `CompanyContext` but 403 unless `role ≥ 'admin'` (admin **or** super_admin); `require_super_admin` — 403 unless `role == 'super_admin'`. Both delegate to `ctx.at_least(role)` over `ROLE_RANK`.
  - `load_membership(session, user, company_id, min_role=)` — same rank check for endpoints whose company comes from the URL path (companies/members/invitations); member management passes `min_role="super_admin"`.
- **Scoping pattern** (every domain router): reads use `Depends(get_active_company)` + `.where(Row.companyId == ctx.company_id)`; path fetches also verify `row.companyId == ctx.company_id` → **404 on mismatch** (no cross-tenant probing). Writes use `Depends(require_super_admin)` for config / structural ops, `Depends(require_admin)` for lot & order management, or `get_active_company` for operator actions; new rows set `companyId=ctx.company_id`.
- **Role matrix** (three tiers):
  - **super_admin** — all config (stations/routes/processes/templates/floorplan/settings/API keys) + member management, card create/**delete**/**update**, unconstrained `POST /cards/{id}/move` (the lot-board drag, forward **or** backward), and `POST /cards/{id}/unmerge` (backward-dragging a merged assembly dissolves it into precursors — recreated at each direct-upstream station's originating template, or, if it has none, at the leaf source queues feeding that branch). The company creator is the super_admin.
  - **admin** (middle) — everything a user can do **plus** create lots (`POST /cards`), pull precursors (`POST /merge/{station}/pull`), and release/cancel production orders (`POST /orders`, `/orders/cancel`, `/orders/import`). No config, no member management, no structural lot ops (move/unmerge/delete). A production-planner / line-lead tier.
  - **user** — read-only on the Lots board (cards aren't draggable; attempting a drag flashes the lock) but on the **Operator** view may run work sessions (`/sessions/*`), set a card's working/done state (`PATCH /cards/{id}/status`, status-only), **merge** (`POST /merge/{station}` — assembling precursors is the first step of working at a merge station; the worker selects the precursor lot cards to consume (`cardIds` in the body) or presses AUTO to let the system pick — no body), and **advance a lot forward** along a defined route via `POST /cards/{id}/advance` (route-constrained). The operator lot picker also lists lots still at the stations **feeding** the current one; tapping one switches the view to that station (finished lots land straight on the MOVE panel) so a worker can go fetch material themselves.
  - A company-scoped **API key** authenticates as the `admin` tier (release orders / reports / scan-to-advance), never super_admin. **Server-side checks are authoritative** — frontend gating (`useRole()` → `isSuperAdmin` / `canManageLots` / `canEdit`) is UX only.
- **Guards**: the last **super_admin** can't be removed or demoted; `admin/reset` and all deletes are company-scoped.
- **Input hardening**: all queries are SQLAlchemy-parameterized (no raw SQL with user input) and the React frontend has no `dangerouslySetInnerHTML` (user text is auto-escaped). Floor-plan uploads are restricted to a raster-image extension whitelist (`map_settings._ALLOWED_IMAGE_EXT`, no `.svg`/`.html`) so a spoofed content-type can't get served as active content (stored XSS) from `/uploads`. Outbound-email subjects strip CR/LF to prevent header injection via user-controlled values (e.g. company name).
- **card_events**: carries `companyId` set at write time (still no FK to the card, so audit rows survive deletion — see [[persistence-layer]] note above).
- **Dev flow**: `TAKTLINE_DEV=1` returns verification/invite links in API responses and enables `POST /auth/dev/bootstrap` (a verified admin + company in one call), used by `seed_demo.py` and tests. Never enable in production.
- **Frontend**: `AuthProvider` bootstraps `/auth/me`; `RequireAuth`/`RequireAdmin` guard routes; the active company is a header (persisted to `localStorage['taktline.activeCompanyId']`, read by the client + WS). The `/ws/events` handshake authenticates via the session cookie + `?companyId=` and broadcasts per company.

### Public sandbox (landing-page "five-minute tutorial")

`POST /auth/sandbox` (unauthenticated, rate-limited) mints a throwaway user + company so a visitor can try Taktline without signing up. The account is flagged `users.isSandbox` and is **permanently restricted server-side** — `deps/auth.ensure_full_account` 403s floor-plan uploads, invitations, API keys, order release/import, and creating further companies; `deps/auth.ensure_sandbox_quota` caps rows per sandbox company (`SANDBOX_LIMITS`: stations/cards/templates/processes) so the public endpoint can't be used as free storage. Accounts self-expire after 7 days (`core/sandbox_gc.py`, swept at startup + daily). Frontend: a standing "create a free account" chip in the topbar, and locked Settings tabs (Map / Members / Integrations) that route to `/signup` — UX only, the server is authoritative.

### Offline resilience (reads only — never writes)

Tri-state connection indicator (live / amber reconnecting / off) with backoff retry. Company-scoped **read** snapshots go to `localStorage` (`store/offlineCache.ts`) and are served when a fetch fails at the network level (or 502/503/504), with a banner naming the snapshot's age; a service worker (`public/sw.js`) caches the app shell + hashed assets so a reload during an outage still renders. **Mutations are never queued or replayed** — they fail loudly, because silent replay would reorder lot movements. Snapshots (and cached floor plans) are wiped whenever the server confirms the session is gone (logout or a real 401) but kept through network failures — that's the whole feature.

### Per-company usage metering

`usage_counters` (API requests + WS messages per calendar month) is accumulated in memory and flushed every 30 s (`core/usage.py`). **Attribution happens in `deps/auth` after membership/API-key verification, never from the raw `X-Company-Id` header** — otherwise anyone could inflate another tenant's meter (regression-tested in `tests/test_sandbox.py`).

### Platform staff (customer service) — orthogonal to tenant roles

Instance-level tier for support, entirely separate from company roles: **owner** (emails in the `PLATFORM_OWNER_EMAILS` env / `backend/.env` — deliberately env-only, no API can mint one) and **support** (`users.platformRole`, grantable only by an owner via `PUT /platform/users/{id}/platform-role`). All `/platform/*` endpoints (`routers/platform.py`) are session-only (never API keys) and return **404 to non-staff**; deps are `require_platform_staff` / `require_platform_owner`.

- **Impersonation** is an explicit time-boxed `SupportGrant` (default 60 min, max 8 h): `get_active_company`, `load_membership`, and the WS handshake fall back to an active grant with role `super_admin` when membership is missing. `/auth/me` surfaces grant companies flagged `impersonated: true` so the switcher/banner ("Supporting <name> · End") just work.
- **Destructive ops**: `DELETE /platform/companies/{id}` needs the exact name in `confirmName`; `DELETE /platform/users/{id}` may remove a company super_admin (deliberately bypassing the tenant-side last-super-admin guard) but never an owner or yourself.
- **Everything is audited** in `platform_audit` (no FKs — rows survive actor/target deletion).
- **Metrics**: `GET /platform/status` (uptime, req/min ring buffer from `core/traffic.py`, live WS connections, session/work/event counts); `GET /platform/companies` adds per-company activeUsers, devices (live sockets), and monthly `usage_counters` (API requests + WS messages, accumulated in-memory in `core/usage.py`, flushed every 30 s).
- Frontend: `/platform` route (`RequirePlatformStaff`, UX-only), nav entry appears when `user.platformRole` is set.

## Map scale calibration

The map view renders the floor plan sprite at its **raw image pixel dimensions** (`naturalWidth × naturalHeight`). Station positions are stored in real-world units (meters or feet). The `pixelsPerUnit` setting tells the map how many raw image pixels equal one real-world unit.

**Rule**: `pixelsPerUnit` must equal the scale factor `M` used when generating the floor plan PNG — i.e. how many pixels per meter (or foot) the image was drawn at.

For the E-Bike demo floor plan (`generate_floorplan.py`):

```
M = 36  →  pixelsPerUnit = 36  (36 image pixels = 1 meter)
```

**How `mapWidthPx` / `mapHeightPx` are captured**: `MapConfigTab` reads `img.naturalWidth` / `img.naturalHeight` on image load and stores them as `mapWidthPx` / `mapHeightPx` in the database. `MapCanvas` then sizes the PixiJS sprite at exactly those pixel dimensions in world coordinates. This makes `pixelsPerUnit` screen-independent — it must match the generator's `M`, not any CSS or display size.

**Station position units**: `station.position.x` / `.y` are stored in **image pixels** (= world coordinates), **not** in meters. `MapCanvas` renders stations at `position.x` directly with no conversion. To place a station at `(x_m, y_m)` meters, store `position.x = x_m * M` (e.g. 35 m × 36 = 1260 px). `seed_demo.py` reads `M` from `GET /map-settings/` at startup (`pixelsPerUnit`) so positions stay correct for any floor plan scale.

**Common mistake**: storing positions in meters (small values like 5–97) causes all stations to appear packed in the top-left corner of the canvas. If stations cluster near the origin after a seed run, check that positions are multiplied by `M` before being sent to the API.

