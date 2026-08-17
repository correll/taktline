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

You pick the branch when you create the Blueprint, so it does not have to be
`main` — but `Dockerfile` and `render.yaml` must exist on whichever branch you
choose. Deploying one without them fails with a build error that does not
explain itself.

## 2. Create the blueprint

**A Blueprint is created at the workspace level, not inside a Project.** If you
have just made a Project and are looking at its "add a service" menu, you will
only be offered Web Service, Static Site, Postgres and so on — Blueprint is not
there. Go back to the dashboard root.

From [dashboard.render.com](https://dashboard.render.com): the **New** button
in the top navigation → **Blueprint**. (Direct link:
[dashboard.render.com/blueprints](https://dashboard.render.com/blueprints) →
**New Blueprint**.)

Then: select the repository → **Connect** → name the Blueprint and **choose the
branch** → leave Blueprint Path empty (it defaults to `render.yaml` at the
root) → review the proposed changes → **Deploy Blueprint**.

Render reads `render.yaml` and creates:

| | |
|---|---|
| `taktline` | web service, Docker, `starter` plan (~$7/mo, always on) |
| `taktline-db` | Postgres, `basic-256mb` (~$6/mo, no expiry) — see [storage](#a-note-on-storage) |

It wires `DATABASE_URL` between them, so it never touches your repo.
**This starts billing on apply.**

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

### A note on storage

`basic-256mb` names the **RAM, not the disk**. It comes with **1 GB of
storage**, and storage scales independently of the instance type — add it at
any time, in 5 GB steps, at $0.30/GB-month, with no downtime. You cannot shrink
it again, so there is no reason to over-provision up front.

1 GB is more than it sounds for this workload. Measured against the real
schema, the two tables that grow forever are `card_events` (167 B/row, the
audit log — never pruned) and `sessions` (122 B/row). A busy single shop doing
200 lot movements and 1,000 work sessions a day accumulates roughly **100 MB a
year** including index overhead, so the included gigabyte lasts about a decade.
Floor plans live in Postgres too, but at ~90 KB each a handful of them never
matters.

Watch it rather than assume it: Render shows database size in the dashboard,
and the first thing to check if it ever climbs unexpectedly is `card_events`,
since nothing deletes from it by design.

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

**Deploys drop websockets, not requests.** Render brings the new instance up,
waits for `/health`, moves traffic, and only then stops the old one — so HTTP
requests are not interrupted even at one instance. What does break is the open
WebSocket on every tablet, because the process holding it goes away: the boards
show the amber "reconnecting" strip and come back on their own within a few
seconds (`api/ws.ts` retries with backoff). Nothing is lost, because the client
never queues writes. See **Deploying without downtime** below for the part that
is *not* automatic — the database.

**Password hashing is the CPU floor.** argon2id is deliberately expensive and is
by far the heaviest thing the app does — everything else answers in ~90 ms.
Taktline ships the OWASP minimum profile (19 MiB, t=2, p=1) rather than
argon2-cffi's multi-core defaults, which on a small instance cost 3.2 s per
login and 27 s for eight tablets signing in at once; tuned, that is 0.2 s and
6 s. On a larger instance raise `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST_KIB` /
`ARGON2_PARALLELISM` — hashes record the cost they were made with, so existing
passwords keep working and migrate to the new cost on their next login.

---

## Deploying without downtime

### What Render already handles

A web service with a `healthCheckPath` gets a zero-downtime deploy by default,
and `numInstances: 1` does not change that: Render starts the new instance,
waits for `/health` to answer, moves traffic, and only then stops the old one.
The two versions overlap for a few seconds by design.

That overlap is the thing to design around, and it is why migrations do **not**
run from the container's start command. They run once, before the new instance
starts, from `preDeployCommand` in `render.yaml`. Two consequences worth having:
a failed migration **aborts the deploy** while the current version carries on
serving, instead of taking the container down and then crash-looping on the same
failure; and a restart (an out-of-memory kill, a manual restart) no longer
re-runs migrations as a side effect of coming back up.

### The part that is not automatic: the schema

For the seconds between the migration finishing and the last old instance
stopping, **the previous release's code is running against the new schema.**
That is not hypothetical — it happened during this work: a `NOT NULL` column was
added without a database-side default, and every insert from the still-running
old build failed until it went away.

So every migration has to be **expand/contract**: the schema is only ever
widened in the deploy that needs it, and narrowed a deploy later.

| Change | Safe in one deploy? | What to do |
|---|---|---|
| Add a table | yes | — |
| Add a nullable column | yes | — |
| Add a `NOT NULL` column | **only with `server_default`** | old code omits it from `INSERT`; keep the default in the model too, or the next `--autogenerate` will drop it |
| Drop a column | no | deploy 1: stop reading and writing it. deploy 2: drop it |
| Rename a column | no | add the new one, write both, backfill, ship; then stop writing the old one, ship; then drop it |
| Change a type | usually no | add a new column and migrate across, as with a rename |
| Add an index on a large table | needs care | `CREATE INDEX CONCURRENTLY` — a plain `CREATE INDEX` holds a write lock for the duration |
| Add a `CHECK` / `FOREIGN KEY` | needs care | add `NOT VALID`, then `VALIDATE CONSTRAINT` in a later migration |

`CONCURRENTLY` cannot run inside a transaction, which Alembic opens by default:

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index("ix_cards_company_lot", "cards", ["companyId", "lotNum"],
                        postgresql_concurrently=True)
```

### Testing the new version before it takes traffic

Add a staging service and a staging database to `render.yaml` (both are in
there, commented, under `# ── Staging ──`). It tracks a `staging` branch and has
its own database, so nothing you do there can reach a customer.

```bash
git switch -c staging          # once
git push -u origin staging     # Render builds and deploys it
# … exercise it at https://taktline-staging.onrender.com …
git switch main && git merge --ff-only staging && git push
```

That is the whole promotion: production auto-deploys from `main`, so a
fast-forward merge is the switch. The image is rebuilt rather than moved, which
is worth knowing — it is the same commit, not the same artifact, so a build that
depends on the network can in principle differ. Pin what matters (the
`requirements.txt` and `package-lock.json` are both exact).

If you would rather promote deliberately instead of on push, set
`autoDeploy: false` on the production service and press **Deploy** in the
dashboard when staging looks right.

### Rolling back

Render keeps previous deploys: **Rollback** in the dashboard puts the old image
back in about the same time a deploy takes. What it does *not* roll back is the
database — which is the other half of why migrations are expand/contract. A
migration that only widened the schema is safe to leave in place while the code
goes back a version; one that dropped or renamed something is not, and getting
out of that needs a restore. Every migration in this repo has a working
`downgrade` (`tests/test_migrations.py` runs them on a scratch database), but a
downgrade that drops a column drops the data in it.

### A deploy checklist that fits on one line

Migrate forward-compatibly, test on staging, merge to `main`, watch `/health`,
expect the boards to blink amber for a few seconds.

---

## Going live with billing

Billing is **dormant until `STRIPE_SECRET_KEY` is set** — with the four
Stripe variables empty, nothing is metered, nothing can be purchased, no
webhook is accepted, and the deploy behaves exactly as the site did before
the paywall existed. That makes the code deploy and the commercial launch two
separate events, in that order, and the second one is reversible: unset the
key and billing is dormant again.

What happens to accounts that already exist: every company present when the
billing migration runs is grandfathered onto the paid plan as **comped** —
full capability, station count uncapped, integrations on, no charge, visible
as "comped" on the platform dashboard so it never counts as MRR. Companies
created after that start on the free tier (7 stations). Nobody who signed up
before the paywall meets it retroactively.

The launch sequence, in order:

1. **Activate the live Stripe account** — business details, bank account.
   Everything below happens in live mode; the sandbox ids in `.env` are for
   development and will not work in production.
2. **Create the prices**: `STRIPE_SECRET_KEY=sk_live_… python setup_stripe.py`
   in `backend/`. Idempotent; prints the two `STRIPE_PRICE_*` values. It
   refuses, loudly, if a price already exists with different numbers.
3. **Dashboard configuration** (each of these is a checkbox, not code):
   - *Tax*: origin address + the Indiana registration
     (dashboard.stripe.com/tax). No registration, no collection.
   - *Payment methods*: enable ACH (`us_bank_account`); card and Link are on
     by default. The code deliberately does not pin the list.
   - *Billing → Revenue recovery*: Smart Retries + failed-payment emails, and
     set the after-retries end-state so it agrees with the app's 7-day
     read-only window rather than racing it.
   - The customer-portal configuration needs nothing: the app creates its own
     (plan-switching off) the first time anyone opens the portal.
4. **Register the webhook**: endpoint `https://taktline.com/billing/webhook`,
   with exactly the events listed in `billing_stripe.HANDLED`. Copy the
   signing secret.
5. **Set the four variables** in Render (`STRIPE_SECRET_KEY`,
   `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_TAKTLINE`, `STRIPE_PRICE_ONPREM`)
   and let the service restart. Billing is now live.
6. **Spend $200 on yourself.** Create a company, add a station, subscribe with
   a real card, watch the webhook flip the row to `active`, open the portal,
   cancel, and confirm the refund-and-pause path. Ten minutes, and it is the
   only test that exercises Stripe's half of the contract. (A dry run of the
   same loop against the sandbox keys on staging or a dev machine first —
   `stripe listen --forward-to localhost:8000/billing/webhook` — costs
   nothing.)

Keep the window between deploying the branch and setting the key short: while
dormant, the pricing page already advertises the metered plan but Settings →
Billing says the deployment is not connected to a payment provider, and
companies signing up meanwhile land on the free tier able to build past 3
stations (they keep what they built; they just cannot add more once the gate
is live).

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
  -e TAKTLINE_DEV=0 \
  -e FRONTEND_BASE_URL=https://your-host \
  -e RUN_MIGRATIONS=1 \
  taktline
```

`RUN_MIGRATIONS=1` makes the container migrate on start. On Render that is done
by `preDeployCommand` instead (see below), so the variable is left unset there —
but on a single box with no pre-deploy hook it is what you want.

To use an external database with Render, delete the `databases:` block from
`render.yaml` and set `DATABASE_URL` to `sync: false`.

For local development, leave the email variables unset: the console mailer
prints messages and their links to stdout, so every flow is testable without an
account anywhere.
