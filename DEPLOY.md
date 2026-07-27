# Deploying Taktline (free tier)

Taktline is a FastAPI backend + Postgres + a React (Vite) SPA. It can be hosted
for free with **Neon** (Postgres), a container/web host (**Render**, **Fly.io**,
**Railway**), and **SendGrid** (email). Two topologies are supported; pick one.

> Security note: whichever you choose, set a strong `SECRET_KEY`, `COOKIE_SECURE=1`,
> `TAKTLINE_DEV=0`, and change the default admin password before going live.
> Also set `PLATFORM_OWNER_EMAILS` to the operator's email (customer-service
> dashboard at /platform).

Floor-plan uploads are stored **in Postgres** and served through a disk
read-through cache, so hosts without a persistent disk (Render free tier)
work fine — a fresh instance repopulates its cache from the database on the
first request per image.

---

## Option A — Single service, same origin (recommended)

The backend serves the built SPA, so the API and app share one origin. This is
the simplest and safest setup: `SameSite=Lax` cookies, **no CORS**, no
cross-site cookie handling.

1. **Database — Neon.** Create a free project; copy the connection string and
   convert the driver prefix to `postgresql+asyncpg://…`.
2. **Build the frontend** with a same-origin API base:
   ```bash
   cd frontend && VITE_API_URL= npm run build   # empty → calls the current origin
   ```
   (Or set `VITE_API_URL=""` in the host's build env.)
3. **Deploy the backend** (Render "Web Service" from this repo, or the Dockerfile
   pattern below) with env:
   ```
   DATABASE_URL=postgresql+asyncpg://…neon…/taktline
   SECRET_KEY=<64+ random chars>
   TAKTLINE_DEV=0
   COOKIE_SECURE=1
   FRONTEND_BASE_URL=https://your-app.onrender.com
   FRONTEND_DIST=/opt/render/project/src/frontend/dist   # path to the built SPA
   SENDGRID_API_KEY=SG.xxxx
   SMTP_FROM=Taktline <no-reply@yourdomain.com>
   ```
4. **Start command:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`

   `--proxy-headers` is **required behind a platform load balancer**: without it
   every request appears to come from the proxy's IP, so the per-IP rate limits
   (login, password reset, the public `/auth/sandbox`) collapse into one shared
   bucket that a single abuser can exhaust for everyone.
5. Open the service URL, **Create account → verify (SendGrid) → create a company**.

`CORS_ORIGINS` and `COOKIE_SAMESITE` can stay at their defaults here (same origin).

---

## Option B — Split hosting (SPA on Vercel, API on Render)

The SPA and API live on different origins, so cookies must be cross-site.

1. **Database — Neon** (as above).
2. **API on Render** with env:
   ```
   DATABASE_URL=postgresql+asyncpg://…neon…/taktline
   SECRET_KEY=<64+ random chars>
   TAKTLINE_DEV=0
   COOKIE_SECURE=1
   COOKIE_SAMESITE=none                     # required for cross-site cookies
   CORS_ORIGINS=https://your-app.vercel.app
   FRONTEND_BASE_URL=https://your-app.vercel.app
   SENDGRID_API_KEY=SG.xxxx
   SMTP_FROM=Taktline <no-reply@yourdomain.com>
   ```
   Start: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **SPA on Vercel** — root `frontend/`, build `npm run build`, output `dist`, env:
   ```
   VITE_API_URL=https://your-api.onrender.com
   ```
   The frontend sends the API/WebSocket to that origin; the backend's CORS +
   WebSocket-Origin checks are already restricted to `CORS_ORIGINS`.

---

## Analytics (optional)

Conversion events (`cta_click`, `sandbox_start`, `signup_completed`,
`outbound_click`) are emitted through `frontend/src/analytics.ts`. They go
nowhere unless you build with `VITE_PLAUSIBLE_DOMAIN=taktline.com`, which
injects the Plausible script; self-hosted instances stay silent by default.
Swap the two lines in that file for any other provider.

## SendGrid

SendGrid is just SMTP, so no code is needed — set `SENDGRID_API_KEY` and a
**verified** `SMTP_FROM` sender. Free tier is ~100 emails/day (enough for
verification + invites). Locally, leave it unset and links print to the console.

## Dockerfile (single-service)

```dockerfile
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL= npm run build            # same-origin build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Production checklist

- [ ] `SECRET_KEY` set to a long random value
- [ ] `TAKTLINE_DEV=0` (disables dev links + `/auth/dev/bootstrap`)
- [ ] `COOKIE_SECURE=1` (+ `COOKIE_SAMESITE=none` only for split hosting)
- [ ] `CORS_ORIGINS` limited to your real frontend origin(s)
- [ ] `SENDGRID_API_KEY` + a verified `SMTP_FROM`
- [ ] Default admin password rotated / that account removed
- [ ] `alembic upgrade head` runs on deploy
- [ ] Tests pass: `createdb taktline_test && python -m pytest`
- [ ] `--proxy-headers` on the uvicorn command (real client IPs → working rate limits)
- [ ] Rate limiting is in-memory per instance (`app/core/ratelimit.py`); with more
      than one instance, point slowapi at Redis so limits are shared
- [ ] Public sandbox (`/auth/sandbox`): accounts self-expire after 7 days
      (`app/core/sandbox_gc.py`) and are row-capped (`deps/auth.SANDBOX_LIMITS`).
      Set `PLATFORM_OWNER_EMAILS` so you can inspect/delete them from `/platform`.
