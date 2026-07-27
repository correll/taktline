# Taktline — single-service image: FastAPI serves the API *and* the built SPA
# from one origin. Same-origin means SameSite=Lax cookies, no CORS, and no
# cross-site WebSocket handling — the simplest thing that is also the safest.
#
#   docker build -t taktline .
#   docker run -p 8000:8000 -e DATABASE_URL=… -e SECRET_KEY=… taktline

# ─── Stage 1: build the SPA ───────────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Empty (not unset) → the client's baseURL becomes '' and it calls the current
# origin. Unset would fall back to '/api', which only exists in the Vite dev
# proxy; in production those paths hit the SPA catch-all and return index.html
# instead of JSON. The WebSocket derives its origin the same way.
ENV VITE_API_URL=""
ARG VITE_PLAUSIBLE_DOMAIN=""
ENV VITE_PLAUSIBLE_DOMAIN=$VITE_PLAUSIBLE_DOMAIN
RUN npm run build

# ─── Stage 2: the runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# PYTHONUNBUFFERED so logs reach the platform's log stream as they happen,
# rather than sitting in a pipe buffer until the process exits.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./frontend_dist
ENV FRONTEND_DIST=/app/frontend_dist

# Floor plans live in Postgres and are cached to disk read-through, so this
# directory is a cache, not storage: it repopulates itself after a redeploy and
# needs no persistent volume. It must be writable by the non-root user below.
RUN mkdir -p /app/uploads \
 && useradd --create-home --uid 10001 taktline \
 && chown -R taktline:taktline /app
USER taktline

EXPOSE 8000

# Migrations run before the server binds, so a redeploy can never serve traffic
# against a schema it does not match.
#
# --proxy-headers + --forwarded-allow-ips is REQUIRED behind a platform load
# balancer: without it every request appears to come from the proxy's IP, so the
# per-IP rate limits (login, password reset, the public sandbox) collapse into
# one shared bucket that a single abuser can exhaust for everybody.
#
# One worker on purpose — see the scaling note in DEPLOY.md: the WebSocket
# connection registry, the rate limiter and the usage meter are per-process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app \
     --host 0.0.0.0 --port ${PORT:-8000} --workers 1 \
     --proxy-headers --forwarded-allow-ips='*'"]
