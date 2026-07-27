"""Application configuration (pydantic-settings).

All secrets and tunables come from the environment (or a local `.env`). Field
names map to UPPERCASE env vars; a few carry explicit aliases so they match the
names used elsewhere (`DATABASE_URL`, `TAKTLINE_DEV`).
"""

from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Database (kept consistent with db/connection.py) ──────────────────────
    database_url: str = Field(
        "postgresql+asyncpg://localhost:5432/taktline",
        validation_alias=AliasChoices("DATABASE_URL"),
    )

    # ── Dev mode ──────────────────────────────────────────────────────────────
    # When true: verification/invite links are returned in API responses and the
    # /auth/dev/bootstrap helper is enabled. MUST be false in production.
    dev: bool = Field(False, validation_alias=AliasChoices("TAKTLINE_DEV", "DEV"))

    # ── Secrets ───────────────────────────────────────────────────────────────
    secret_key: str = "dev-insecure-secret-change-in-production"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed browser origins. Never "*" with credentials.
    cors_origins: str = "http://localhost:3000"

    # ── Platform staff ────────────────────────────────────────────────────────
    # Comma-separated emails of platform OWNERS (full customer-service powers +
    # granting the 'support' role). Deliberately env-only: no API path can add
    # an owner, so a fully compromised tenant account still can't reach it.
    platform_owner_emails: str = Field("", validation_alias=AliasChoices("PLATFORM_OWNER_EMAILS"))

    @property
    def platform_owner_list(self) -> list[str]:
        return [e.strip().lower() for e in self.platform_owner_emails.split(",") if e.strip()]

    # ── Session / CSRF cookies ────────────────────────────────────────────────
    # For a cross-origin deployment (SPA and API on different hosts) set
    # COOKIE_SAMESITE=none and COOKIE_SECURE=1 so the browser sends the cookies.
    session_cookie_name: str = "taktline_session"
    csrf_cookie_name: str = "taktline_csrf"
    cookie_secure: bool = False          # set true in production (HTTPS only)
    cookie_samesite: str = "lax"         # "none" for cross-origin (requires secure)
    cookie_domain: Optional[str] = None

    # ── Uploads ───────────────────────────────────────────────────────────────
    max_upload_bytes: int = 10 * 1024 * 1024   # 10 MB

    # ── Optional single-service hosting ───────────────────────────────────────
    # Path to the built frontend (frontend/dist). When set, FastAPI serves the
    # SPA so the API and app share one origin (simplest/safest for free hosting).
    frontend_dist: Optional[str] = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── Token / session TTLs (seconds) ────────────────────────────────────────
    session_absolute_ttl: int = 60 * 60 * 24 * 14   # 14 days
    session_idle_ttl: int = 60 * 60 * 8             # 8 hours
    email_verify_ttl: int = 60 * 60 * 24            # 24 hours
    password_reset_ttl: int = 60 * 60               # 1 hour
    invite_ttl: int = 60 * 60 * 24 * 7              # 7 days

    # ── Password policy ───────────────────────────────────────────────────────
    password_min_length: int = 10

    # ── Password hashing (argon2id) ───────────────────────────────────────────
    # argon2-cffi's own defaults (t=3, 64 MiB, p=4) assume a multi-core server.
    # Taktline's recommended deployment is one small instance, where they are the
    # single most expensive thing the app does: on a 0.1-CPU box a login took
    # 3.2 s, and a shift-change of eight tablets signing in together took 27 s.
    # These values are the OWASP Password Storage minimum for argon2id
    # (19 MiB, t=2, p=1) — a legitimate posture, roughly an order of magnitude
    # cheaper here. Parallelism of 1 matters most: extra lanes are pure overhead
    # when there is less than a core to run them on.
    #
    # Raise them on a bigger instance — hashes record the parameters they were
    # made with, so old passwords keep verifying and are re-hashed to the
    # current cost on next login.
    argon2_time_cost: int = 2
    argon2_memory_cost_kib: int = 19456     # 19 MiB
    argon2_parallelism: int = 1

    # ── Links in outbound email ───────────────────────────────────────────────
    frontend_base_url: str = "http://localhost:3000"

    # ── Email ─────────────────────────────────────────────────────────────────
    # Precedence: SENDGRID_API_KEY → SMTP_HOST → ConsoleMailer (dev default).
    # SendGrid is just SMTP: it maps to smtp.sendgrid.net with user "apikey".
    sendgrid_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: str = "Taktline <no-reply@taktline.local>"
    smtp_starttls: bool = True
    # None = decide from the port: 465/2465 are implicit TLS, everything else
    # upgrades with STARTTLS. Set explicitly only for a non-standard listener.
    smtp_use_tls: Optional[bool] = None

    # ── Default admin (used only by the backfill migration) ───────────────────
    default_admin_email: str = "admin@taktline.dev"
    default_admin_password: str = "change-me-admin-0000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
