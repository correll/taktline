# Deploying Taktline

Render for the app and the database, Resend for email. About **$13/month**
($7 web service + $6 Postgres), roughly 15 minutes end to end — most of it
waiting for the first image build.

The repo ships everything needed: **`render.yaml`** provisions both services
and wires them together, and **`Dockerfile`** builds the API and the SPA into
one image so they share a single origin — which means `SameSite=Lax` cookies,
no CORS, and no cross-site WebSocket handling.

## Before you start

- The GitHub repo connected to Render.
- A [Resend](https://resend.com) account (free tier: 3,000 emails/month).
- Access to DNS for your domain, if you want one.

---

## 1. Check the branch

A Blueprint follows your repo's **default branch**, and `Dockerfile` +
`render.yaml` must be on it — deploying a branch without them fails with a
build error that does not explain itself. Either merge your release branch into
`main`, or set the branch under Service → Settings once the blueprint exists.

## 2. Create the blueprint

In Render: **New → Blueprint** → connect the repo → **Apply**.

Render reads `render.yaml` and creates:

| | |
|---|---|
| `taktline` | web service, Docker, `starter` plan (~$7/mo, always on) |
| `taktline-db` | Postgres, `basic-256mb` (~$6/mo, 1 GB, no expiry) |

It wires `DATABASE_URL` between them and generates `SECRET_KEY` itself, so
neither ever touches your repo. **This starts billing on apply.**

Render then prompts for the values it cannot invent:

| Variable | What to put | If you skip it |
|---|---|---|
| `PLATFORM_OWNER_EMAILS` | your email | no access to the `/platform` support dashboard |
| `SMTP_HOST` | `smtp.resend.com` | email is only logged — see step 5 |
| `SMTP_PORT` | `587`, or `465` — either works | defaults to 587 |
| `SMTP_USER` | `resend` — the literal word | authentication fails |
| `SMTP_PASSWORD` | your Resend API key | authentication fails |
| `SMTP_FROM` | `Taktline <no-reply@taktline.com>` | Resend rejects the message |

Resend shows the API key as the SMTP **password**; the username is the literal
string `resend`. Either port works — 465/2465 are implicit TLS, 587/2587
upgrade with STARTTLS, and the app picks the mode from the port number.

Leave **`SENDGRID_API_KEY` empty.** It takes precedence over the `SMTP_*`
values, so a stray value there would send your Resend key to SendGrid's server
and every email would fail.

`FRONTEND_BASE_URL` is already set to `https://taktline.com` in `render.yaml` —
change that line if you are deploying anywhere else. It is what the links in
verification and invite emails are built from.

## 3. Watch the first deploy

Two stages, both visible in **Logs**:

- **Build** (~3–5 min) — Node builds the SPA, Python installs, the image
  assembles.
- **Boot** (~40 s) — `alembic upgrade head` runs *before* the port is bound, so
  migrations scroll past, then `Uvicorn running on http://0.0.0.0:8000`.
  Render's health check hits `/health` and flips the service to **Live**.

## 4. Verify your domain in Resend

Until you do, Resend only sends **from** `onboarding@resend.dev` and **to** the
address you signed up with — enough to prove the wiring, not enough to invite
anyone.

In Resend: **Domains → Add Domain** → `taktline.com`. It gives you SPF and DKIM
records; add them at your registrar, then set `SMTP_FROM` to
`Taktline <no-reply@taktline.com>`.

Sending from your own verified domain rather than a provider subdomain is the
single biggest thing you can do for deliverability. A verification email
landing in spam is the failure mode nobody reports — they just never sign up.

## 5. Create the first account

Open the service URL and **Create account**, then verify the email:

- **Resend configured** — the email arrives; click the link.
- **Not yet** — Taktline falls back to a console mailer that prints the whole
  message, *including the verification link*, to stdout. Find the
  `===== DEV EMAIL =====` block in **Logs** and paste the link. Fine for
  bootstrapping your own account, useless for running: team invitations go to
  the same place.

Then **create a company**. The address in `PLATFORM_OWNER_EMAILS` also unlocks
`/platform` for support and metrics.

## 6. Custom domain

Service → **Settings → Custom Domains → Add**. Add both `taktline.com` and
`www.taktline.com` — Render redirects one to the other, which matters because
the session cookie is bound to a single origin; someone landing on the other
spelling would see a logged-out app.

At your registrar:

- **apex** (`taktline.com`) — an `ALIAS`/`ANAME` record if your provider
  supports one, otherwise the A record Render gives you. GoDaddy's basic DNS
  has no ALIAS at the apex, so use the A record or host DNS at Cloudflare.
- **www** — a `CNAME` to the `onrender.com` hostname.

Render issues TLS automatically once the record resolves. `FRONTEND_BASE_URL`
already points here, so nothing else changes.

## 7. Before you put real work on it

- [ ] `/auth/dev/bootstrap` returns 404 (confirms `TAKTLINE_DEV=0`)
- [ ] Sign in on a phone — the connection light shows **LIVE**
- [ ] Upload a floor plan, then redeploy: it is stored in Postgres, so it survives
- [ ] Send yourself an invitation and confirm it arrives from your own domain
- [ ] Take a first backup (Render → database → Backups)

---

## How it is built

`Dockerfile` is two stages: Node builds the SPA with `VITE_API_URL=""` so the
client calls its own origin, then Python serves both the API and that build.

On boot it runs `alembic upgrade head` **before** binding the port, so a
redeploy never serves traffic against a schema it does not match, and starts
uvicorn with `--proxy-headers --forwarded-allow-ips='*'` so the per-IP rate
limits (login, password reset, the public sandbox) see real client IPs instead
of Render's load balancer collapsing them into one shared bucket.

Floor plans need **no persistent disk**: they live in Postgres, and the
container's `uploads/` directory is only a read-through cache that repopulates
itself after a redeploy.

`DATABASE_URL` uses Render's **`connectionString`, not `connectionPoolString`.**
The pooled endpoint is PgBouncer in transaction mode, which breaks asyncpg's
prepared statements unless the driver's statement cache is disabled — an
intermittent failure that only shows up under concurrency. The app keeps its own
SQLAlchemy pool and runs as a single instance, so it gains nothing from the
pooler. Do not "optimise" this.

---

## Three things to know before you rely on it

**One instance, deliberately.** `numInstances: 1` is not a cost saving. The
WebSocket connection registry, the per-IP rate limiter and the usage meter all
live in process memory, so a second instance would serve boards that never
receive the other instance's events — lot moves appearing on some tablets and
not others. Measured headroom for one instance: **3,200 concurrent boards** at
100% event delivery, and ~280 writes/s. That is roughly 60 shops of 50 tablets.
Scaling out needs a cross-instance relay first (Postgres `LISTEN/NOTIFY` fits:
no new infrastructure, and it delivers only on commit) plus a shared store for
the rate limiter.

**Deploys are downtime.** The service is always on, but with one instance every
deploy costs the ~40 s boot while the new container migrates and starts. Deploy
outside shift hours once people depend on it.

**Password hashing is the CPU floor.** argon2id is deliberately expensive and is
by far the heaviest thing the app does — everything else answers in ~90 ms.
Taktline ships the OWASP minimum profile (19 MiB, t=2, p=1) rather than
argon2-cffi's multi-core defaults, which on a small instance cost 3.2 s per
login and 27 s for eight tablets signing in at once; tuned, that is 0.2 s and
6 s. On a larger instance raise `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST_KIB` /
`ARGON2_PARALLELISM` — hashes record the cost they were made with, so existing
passwords keep working and migrate to the new cost on their next login.

---

## Running it elsewhere

The image is a plain container, and `DATABASE_URL` accepts any managed Postgres:
`postgresql://`, `postgres://`, and a trailing `?sslmode=require` (plus Neon's
`channel_binding`) are all normalized to asyncpg at boot, so there is nothing to
hand-edit.

```bash
docker build -t taktline .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host/db \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e TAKTLINE_DEV=0 \
  -e FRONTEND_BASE_URL=https://your-host \
  taktline
```

To use an external database with Render, delete the `databases:` block from
`render.yaml` and set `DATABASE_URL` to `sync: false`.

For local development, leave the email variables unset: the console mailer
prints messages and their links to stdout, so every flow is testable without an
account anywhere.
