# Deploying Taktline (free tier)

Taktline is a FastAPI backend + Postgres + a React (Vite) SPA. It can be hosted
for free with **Neon** (Postgres), a container/web host (**Render**, **Fly.io**,
**Railway**), and **SendGrid** (email). Two topologies are supported; pick one.

**Deploying to Render?** Jump to [Render, from the blueprint](#render-from-the-blueprint)
— `render.yaml` + `Dockerfile` in the repo root do all of this for you.

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

1. **Database — Neon.** Create a free project and copy the connection string
   as-is. `postgresql://…`, `postgres://…` and a trailing `?sslmode=require`
   (plus Neon's `channel_binding`) are all normalized to asyncpg at boot by
   `db/connection.normalize_db_url`, so there is nothing to hand-edit; the TLS
   mode you were given is preserved, not downgraded.
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

## Render, from the blueprint

The repo ships a **`render.yaml`** blueprint and a **`Dockerfile`** that build
Option A as one service. Start to finish, first deploy takes about 15 minutes,
most of it waiting for the image to build.

### 0. Point Render at the right branch

The deploy build lives on whichever branch you treat as production. A Blueprint
follows your repo's **default branch** unless you say otherwise, so either merge
your release branch into `main`, or set the branch explicitly in the Render UI
(Service → Settings → Branch) after the blueprint is created. Deploying a branch
that has no `Dockerfile` fails with a build error that does not explain itself.

### 1. Create the blueprint

In Render: **New → Blueprint** → connect the GitHub repo → **Apply**. Render
reads `render.yaml` and provisions two things: the web service `taktline` and a
Postgres database `taktline-db`. It wires `DATABASE_URL` between them and
generates `SECRET_KEY` itself, so neither ever touches your repo.

The blueprint asks for four values it cannot invent:

| Variable | What to put | If you skip it |
|---|---|---|
| `FRONTEND_BASE_URL` | your service URL — you do not know it yet, see step 2 | verification and invite emails link to `localhost` |
| `PLATFORM_OWNER_EMAILS` | your email | no access to the `/platform` support dashboard |
| `SENDGRID_API_KEY` | a SendGrid API key | email is logged instead of sent — see step 4 |
| `SMTP_FROM` | a **verified** sender, e.g. `Taktline <no-reply@taktline.com>` | SendGrid rejects the message |

Leave any of them blank for now; you can fill them in later under
Service → Environment. Saving an env var triggers a redeploy automatically.

### 2. Set `FRONTEND_BASE_URL` once you know the URL

This is the one ordering wrinkle: Render assigns the URL
(`https://<service>.onrender.com`) only after the service exists, but the app
needs it to build the links it puts in emails. So after the first deploy, copy
the URL from the top of the service page into `FRONTEND_BASE_URL` and let it
redeploy. If you plan to use a custom domain (step 5), set it to the custom
domain instead and skip a round trip.

### 3. Watch the first deploy

Two stages, both visible in **Logs**:

- **Build** (~3–5 min) — Node builds the SPA, then Python installs and the
  image assembles.
- **Boot** (~40 s on a small instance) — `alembic upgrade head` runs *before*
  the port is bound, so you will see the migrations scroll past, then
  `Uvicorn running on http://0.0.0.0:8000`. Render's health check hits
  `/health` and flips the service to **Live**.

That ~40 s is Python importing and migrating on a fraction of a CPU. It is paid
on every deploy and restart, and with one instance it is genuine downtime — so
deploy outside shift hours once you have people on the floor.

### 4. Create the first account

Open the service URL and **Create account**. Then verify the email:

- **With SendGrid configured** — the verification email arrives normally. Click
  the link.
- **Without it** — Taktline falls back to a console mailer, which prints the
  whole message *including the verification link* to stdout. Open
  Service → **Logs**, find the `===== DEV EMAIL =====` block, and paste the link
  into your browser. This is a perfectly good way to bootstrap the very first
  account, but it is not a way to run: invitations to your team go to the same
  place, so nobody but you can ever join. Configure SendGrid before inviting
  anyone.

Then **create a company**, and you are on the map. The email you put in
`PLATFORM_OWNER_EMAILS` also unlocks `/platform` for support and metrics.

### 5. Custom domain (optional)

Service → **Settings → Custom Domains → Add**. Render shows you the DNS record
it wants. At your registrar:

- **apex** (`taktline.com`) — an `ALIAS`/`ANAME` record if your DNS provider
  supports it, otherwise the A record Render gives you. GoDaddy's basic DNS has
  no ALIAS at the apex, so either use the A record or host DNS at Cloudflare.
- **subdomain** (`app.taktline.com`) — a `CNAME` to the `onrender.com` hostname.

Render issues the TLS certificate automatically once the record resolves
(usually minutes; DNS propagation can take longer). Afterwards, update
`FRONTEND_BASE_URL` to the custom domain so email links point at it.

### 6. Before you put real work on it

- [ ] `TAKTLINE_DEV` is `0` (the blueprint sets it) — confirm `/auth/dev/bootstrap` returns 404
- [ ] Sign in on a phone and confirm the connection light shows **LIVE**
- [ ] Upload a floor plan and reload — it is served from Postgres, so it survives redeploys
- [ ] Move the service and database off the free plans (see below)
- [ ] Take a first database backup (Render → database → Backups)

### What the image does

`Dockerfile` is a two-stage build: Node builds the SPA with `VITE_API_URL=""`
so the client calls its own origin, then Python serves both the API and that
build. On boot it runs `alembic upgrade head` **before** binding the port, so a
redeploy never serves traffic against a schema it doesn't match, and starts
uvicorn with `--proxy-headers --forwarded-allow-ips='*'` so per-IP rate limits
see real client IPs instead of Render's load balancer.

Floor plans need **no persistent disk**: they live in Postgres and the
container's `uploads/` directory is only a read-through cache that repopulates
itself after a redeploy.

### Three things to know before you rely on it

**Password hashing is the CPU floor.** argon2id is deliberately expensive and
is by far the heaviest thing the app does; everything else is ~90 ms. Taktline
ships the OWASP minimum profile (19 MiB, t=2, p=1) rather than argon2-cffi's
multi-core defaults, which on a 0.1-CPU instance cost 3.2 s per login and 27 s
for eight tablets signing in together. Tuned: **0.2 s** and **6 s**. On a
larger instance raise `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST_KIB` /
`ARGON2_PARALLELISM` — hashes record the cost they were made with, so existing
passwords keep working and migrate to the new cost on their next login.

**Free tier sleeps.** A free Render web service spins down after ~15 minutes of
inactivity; the next request pays a cold start of roughly 30 seconds. Fine for
a demo, wrong for a shop floor that opens at 6am — use a paid instance for
anything real. Render's free Postgres also **expires**; check Render's current
policy and move to a paid plan or Neon before you have data you care about.

**One instance, deliberately.** `numInstances: 1` is not a cost saving. The
WebSocket connection registry, the per-IP rate limiter and the usage meter all
live in process memory, so a second instance would serve boards that never
receive the other instance's events — lot moves would appear on some tablets
and not others. Measured headroom for one instance: **3200 concurrent boards**
with 100% event delivery, and ~280 writes/s. That is roughly 60 shops of 50
tablets; a single shop is nowhere near it. Scaling out requires a
cross-instance relay first (Postgres `LISTEN/NOTIFY` is the natural fit — it
needs no new infrastructure and delivers only on commit) plus a shared store
for the rate limiter.

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

## Dockerfile

The image is `Dockerfile` in the repo root — a two-stage build (Node for the
SPA, Python for the runtime). It is what Render builds, and it runs anywhere
else that takes a container:

```bash
docker build -t taktline .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host/db \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e TAKTLINE_DEV=0 -e FRONTEND_BASE_URL=https://your-host taktline
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
- [ ] Single instance only — the WebSocket registry, rate limiter and usage
      meter are per-process (see the scaling note under Render above)
- [ ] Public sandbox (`/auth/sandbox`): accounts self-expire after 7 days
      (`app/core/sandbox_gc.py`) and are row-capped (`deps/auth.SANDBOX_LIMITS`).
      Set `PLATFORM_OWNER_EMAILS` so you can inspect/delete them from `/platform`.
