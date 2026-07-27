# Deploying Taktline (free tier)

Taktline is a FastAPI backend + Postgres + a React (Vite) SPA. It can be hosted
for free. The documented path — and the one `render.yaml` builds — is **Render**
for the app, **Neon** for Postgres (Render's own free database expires after 30
days), and **Resend** for email. Two topologies are supported; pick one.

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
   SMTP_HOST=smtp-relay.brevo.com          # or any provider — see Email
   SMTP_USER=...
   SMTP_PASSWORD=...
   SMTP_FROM=Taktline <no-reply@yourdomain.com>
   ```
4. **Start command:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`

   `--proxy-headers` is **required behind a platform load balancer**: without it
   every request appears to come from the proxy's IP, so the per-IP rate limits
   (login, password reset, the public `/auth/sandbox`) collapse into one shared
   bucket that a single abuser can exhaust for everyone.
5. Open the service URL, **Create account → verify by email → create a company**.

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

### 1. Create the database, then the blueprint

First make a Postgres instance and copy its connection string — [Neon](https://neon.tech)
takes about a minute and needs no card (see [Which Postgres](#which-postgres)
for why, and for the alternatives). Paste the string exactly as given; the app
normalizes the driver prefix and `sslmode`/`channel_binding` itself.

Then in Render: **New → Blueprint** → connect the GitHub repo → **Apply**.
Render reads `render.yaml`, creates the web service `taktline`, and generates
`SECRET_KEY` itself so it never touches your repo.

`FRONTEND_BASE_URL` is pre-set to `https://taktline.com` in `render.yaml` —
change that line if you are deploying anywhere else. The blueprint asks for
a handful of values it cannot invent:

| Variable | What to put | If you skip it |
|---|---|---|
| `DATABASE_URL` | your Postgres connection string, verbatim | the service cannot start |
| `PLATFORM_OWNER_EMAILS` | your email | no access to the `/platform` support dashboard |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | any SMTP provider — see [Email](#email) | email is logged instead of sent, see step 4 |
| `SMTP_FROM` | a **verified** sender, e.g. `Taktline <no-reply@taktline.com>` | the provider rejects the message |

Leave any of them blank for now; you can fill them in later under
Service → Environment. Saving an env var triggers a redeploy automatically.

### 2. Know which URL your emails point at

`FRONTEND_BASE_URL` is what the app builds verification, invite and
password-reset links from. It is committed as `https://taktline.com`, so those
links are right from the very first account — but until the custom domain
actually resolves (step 5) they point somewhere that does not answer yet.

That is harmless and easy to work around: the token in the link is what
matters, not the host. Swap `taktline.com` for your `*.onrender.com` hostname
and the same link works. Or just do step 5 before creating your account.

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

- **With SMTP configured** — the verification email arrives normally. Click
  the link.
- **Without it** — Taktline falls back to a console mailer, which prints the
  whole message *including the verification link* to stdout. Open
  Service → **Logs**, find the `===== DEV EMAIL =====` block, and paste the link
  into your browser. This is a perfectly good way to bootstrap the very first
  account, but it is not a way to run: invitations to your team go to the same
  place, so nobody but you can ever join. Configure a mail provider before
  inviting anyone.

Then **create a company**, and you are on the map. The email you put in
`PLATFORM_OWNER_EMAILS` also unlocks `/platform` for support and metrics.

### 5. Custom domain (optional)

Service → **Settings → Custom Domains → Add**. Render shows you the DNS record
it wants. At your registrar:

- **apex** (`taktline.com`) — an `ALIAS`/`ANAME` record if your DNS provider
  supports it, otherwise the A record Render gives you. GoDaddy's basic DNS has
  no ALIAS at the apex, so either use the A record or host DNS at Cloudflare.
- **subdomain** (`app.taktline.com`) — a `CNAME` to the `onrender.com` hostname.

Add **both** `taktline.com` and `www.taktline.com` — Render redirects one to
the other, so a visitor who types `www` still lands on the app and on the same
origin your cookies are set for.

Render issues the TLS certificate automatically once the record resolves
(usually minutes; DNS propagation can take longer). `FRONTEND_BASE_URL` already
points here, so nothing else changes once it is live.

### 6. Before you put real work on it

- [ ] `TAKTLINE_DEV` is `0` (the blueprint sets it) — confirm `/auth/dev/bootstrap` returns 404
- [ ] Sign in on a phone and confirm the connection light shows **LIVE**
- [ ] Upload a floor plan and reload — it is served from Postgres, so it survives redeploys
- [ ] Decide whether to stay on free plans — Neon's is permanent, Render's web
      service sleeps (see [Which Postgres](#which-postgres) and below)
- [ ] Take a first database backup (Render → database → Backups)

### Which Postgres

**Render's free Postgres expires 30 days after it is created** (then 14 more
days to upgrade before the data is deleted). That is a trial, not a free tier,
so `render.yaml` deliberately does *not* provision a database — a blueprint
that hands you a one-month fuse is worse than one that asks for a connection
string. Bring your own and paste it into `DATABASE_URL`.

| | Free plan | Catch |
|---|---|---|
| **Neon** ← default | permanent: 0.5 GB, 100 CU-hours/month, no card | idle compute suspends and **auto-resumes in ~1 s** |
| **Supabase** | 500 MB | project **pauses after 7 days idle and needs a manual unpause**; deleted if left |
| **Render** | 1 GB | **expires after 30 days** |

**Why Neon over Supabase.** The pause behaviour is the whole argument. A shop
that is quiet for a week — a holiday shutdown, a plant between contracts —
comes back to a Taktline that woke up by itself on Neon, and to a dead one on
Supabase until somebody remembers to log into a dashboard. Secondarily,
Supabase's value is a *platform* (Auth, Storage, Realtime, PostgREST) and this
app already has all four of its own: session auth with argon2, floor plans in
Postgres, its own WebSocket broadcast, its own FastAPI. Adopting it would mean
running two auth systems and duplicating `companyId` scoping in RLS. Neon is
just Postgres, which is the amount of database this wants.

**The one thing to watch on Neon's free plan** is compute-hours, not storage.
0.5 GB is enormous for this data — stations, routes, lots and events are small,
and floor plans are ~100 KB each. But the backend holds a connection pool open
(`pool_pre_ping=True`, SQLAlchemy's default pool), and compute that never goes
idle never suspends, which can outrun 100 CU-hours in a month. If Neon's usage
dashboard shows that happening, the fix is to let the pool drain — run the
engine with `poolclass=NullPool`, trading a little per-request connection
latency for compute that actually suspends between shifts.

**When to just pay.** Roughly $6–7/month buys Render's Basic-256MB or Neon's
Launch plan and removes every caveat above — no expiry, no pause, no
compute-hour ceiling. Taktline being free forever is a statement about the
software licence, not a reason to run a production shop floor on a hobby
database. Move before you have data you would miss, and take a backup.

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
anything real. (The database is a separate decision, covered in
[Which Postgres](#which-postgres).)

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
   SMTP_HOST=smtp-relay.brevo.com          # or any provider — see Email
   SMTP_USER=...
   SMTP_PASSWORD=...
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

## Email

Taktline speaks plain SMTP, so any provider works — nothing about it is
SendGrid-specific. Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`,
`SMTP_PASSWORD`, and an `SMTP_FROM` address you have **verified** with the
provider. `SENDGRID_API_KEY` remains as a one-variable shortcut: it fills in
`smtp.sendgrid.net` with user `apikey` for you.

**SendGrid's permanent free plan ended on 27 May 2025.** New accounts get a
60-day trial (100 emails/day), then paid plans from about $19.95/month. Still a
fine choice if you are already paying for it; a poor default now. Options with
a standing free tier, all plain SMTP:

| Provider | Free tier | Their branding on your email? | SMTP host |
|---|---|---|---|
| **Resend** ← default | 3,000/month, 100/day | no | `smtp.resend.com:587` (user `resend`) |
| **Brevo** | ~300/day | **yes** — "Sent with Brevo"; removing it is a paid add-on | `smtp-relay.brevo.com:587` |
| **SMTP2GO** | 1,000/month | no | `mail.smtp2go.com:587` |
| **Amazon SES** | none, ~$0.10 per 1,000 | no | `email-smtp.<region>.amazonaws.com:587` |

**Resend is the default here, and the branding column is why.** Taktline's only
emails are the ones that *are* the first impression — "Verify your Taktline
email" to a new customer, "You're invited to join…" to every worker on a floor.
A third-party marketing footer on those reads as hobby-grade at precisely the
wrong moment. Brevo's free tier is otherwise more generous (300/day against
Resend's 100/day), so it is the better pick if you expect to onboard several
large customers on the same day — but that is headroom you can buy later, and
clean email you cannot.

Volume is not the deciding factor either way: Taktline sends only verification,
invitation and password-reset messages, so a shop of 50 people might send a few
dozen emails in its lifetime. Onboarding an entire 50-person floor is 50
invitations — comfortable inside any row above.

**Send from your own domain.** `no-reply@taktline.com` on a domain you have
verified (SPF + DKIM records at your registrar) rather than a provider
subdomain is the single biggest thing you can do for deliverability. Do it in
the same sitting as the custom-domain DNS in step 5 — a verification email
landing in spam is the failure mode that quietly kills signups, and it is
invisible until someone tells you they never got it.

Locally, leave all of it unset: the console mailer prints the message and its
link to stdout, which is what makes the flows testable with no account
anywhere.

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
- [ ] SMTP configured + a verified `SMTP_FROM` (SendGrid is no longer free — see Email)
- [ ] Default admin password rotated / that account removed
- [ ] `alembic upgrade head` runs on deploy
- [ ] Tests pass: `createdb taktline_test && python -m pytest`
- [ ] `--proxy-headers` on the uvicorn command (real client IPs → working rate limits)
- [ ] Single instance only — the WebSocket registry, rate limiter and usage
      meter are per-process (see the scaling note under Render above)
- [ ] Public sandbox (`/auth/sandbox`): accounts self-expire after 7 days
      (`app/core/sandbox_gc.py`) and are row-capped (`deps/auth.SANDBOX_LIMITS`).
      Set `PLATFORM_OWNER_EMAILS` so you can inspect/delete them from `/platform`.
