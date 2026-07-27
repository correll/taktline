"""Async SQLAlchemy database layer (PostgreSQL via asyncpg).

Replaces the previous Motor/MongoDB connection. Exposes:

- ``engine``        — the async engine (one per process)
- ``SessionLocal``  — async session factory (``expire_on_commit=False``)
- ``Base``          — declarative base for ORM models
- ``get_session``   — FastAPI dependency that wraps each request in a
                       transaction (commit on success, rollback on error).
                       This is what makes multi-write endpoints such as
                       ``/merge`` and ``/cards/{id}/move`` atomic for free.
- ``parse_uuid`` / ``require_uuid`` / ``optional_uuid`` — helpers for turning
                       string ids from the API into ``uuid.UUID`` values.
"""

import os
import uuid
from typing import AsyncGenerator, Optional

from fastapi import HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


def normalize_db_url(raw: str) -> str:
    """Accept the connection string a host actually hands out.

    Managed Postgres providers emit libpq/psycopg URLs — Render wires
    ``postgresql://…``, Neon and Supabase append ``?sslmode=require`` (Neon adds
    ``channel_binding`` too), and some tooling still says ``postgres://``. None
    of those reach asyncpg intact: the bare driver name resolves to psycopg2
    (not installed), and ``sslmode``/``channel_binding`` are forwarded verbatim
    into ``asyncpg.connect()``, which rejects them as unexpected keywords. So a
    correct, copy-pasted production URL would fail at boot.

    Normalizing here rather than asking an operator to hand-edit the URL is what
    lets a Render blueprint wire the database in automatically. asyncpg's ``ssl``
    parameter takes the same vocabulary as libpq's ``sslmode``
    (disable/allow/prefer/require/verify-ca/verify-full), so the TLS posture is
    carried across unchanged rather than downgraded.
    """
    url = make_url(raw)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername == "postgresql+asyncpg":
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)   # libpq-only; asyncpg has no such arg
        if sslmode and "ssl" not in query:
            query["ssl"] = sslmode
        url = url.set(query=query)
    return url.render_as_string(hide_password=False)


# ─── Connection URL ──────────────────────────────────────────────────────────
# On macOS Homebrew the local PostgreSQL server uses "trust" auth for the OS
# user, so no password is needed. asyncpg falls back to the OS username when
# one is not present in the URL.
DATABASE_URL: str = normalize_db_url(os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://localhost:5432/taktline",
))


# ─── Engine / session factory ────────────────────────────────────────────────
# Under pytest (TESTING=1) use NullPool so connections aren't reused across the
# per-test event loops that would otherwise break asyncpg.
if os.getenv("TESTING"):
    from sqlalchemy.pool import NullPool
    engine: AsyncEngine = create_async_engine(DATABASE_URL, poolclass=NullPool)
else:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# ─── Lifespan helpers (kept for main.py compatibility) ───────────────────────
async def connect_db() -> None:
    """Validate connectivity at startup so failures surface early."""
    async with engine.connect():
        pass


async def close_db() -> None:
    await engine.dispose()


# ─── Request-scoped transactional session ────────────────────────────────────
# Function-scoped (FastAPI ≥0.113 dependency scopes): the request stack that
# holds request-scoped dependencies is closed only AFTER the response has been
# sent, so a commit living there races the client's NEXT request — a tablet (or
# the next request on a keep-alive connection) can act on a 201 whose row has
# not landed yet and get a 404, a 401 on a fresh session, or a stale board.
# Function scope closes the stack BEFORE the response bytes leave the server:
# commit first, respond second. Every Depends on get_session must carry this
# scope — the first declaration FastAPI solves decides which stack the shared
# session lands in, so one stray unscoped Depends would reintroduce the race.
SESSION_SCOPE = {"scope": "function"}


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session and commit the whole request as one transaction.

    Any exception (including ``HTTPException``) rolls the transaction back, so a
    handler that raises partway through a multi-step operation never leaves
    partial state behind.
    """
    from ..core.ws_events import flush_events

    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # Only after a successful commit: broadcast any staged card events, so
        # clients never hear about state that rolled back.
        await flush_events(session)


# ─── UUID helpers ────────────────────────────────────────────────────────────
def parse_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    """Return a UUID for a well-formed string, else ``None`` (no raise)."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def require_uuid(value: Optional[str], detail: str = "Resource not found") -> uuid.UUID:
    """Parse an id that must be valid, else 404 (mirrors old ObjectId behaviour)."""
    parsed = parse_uuid(value)
    if parsed is None:
        raise HTTPException(404, detail)
    return parsed


def optional_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    """Parse a nullable foreign-key id; empty/blank -> None, invalid -> 400."""
    if value is None or value == "":
        return None
    parsed = parse_uuid(value)
    if parsed is None:
        raise HTTPException(400, f"Invalid id: {value!r}")
    return parsed


async def get_or_create_singleton(session, model, company_id, **defaults):
    """Fetch a company's single per-company settings row, creating it on first
    access. Concurrency-safe: two simultaneous first-loads no longer 500 on the
    unique ``companyId`` index. The insert runs inside a SAVEPOINT so a duplicate
    only rolls back that nested step (leaving the request's transaction intact),
    after which we return the row the other request committed.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    stmt = select(model).where(model.companyId == company_id)
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row
    try:
        async with session.begin_nested():          # SAVEPOINT
            row = model(companyId=company_id, **defaults)
            session.add(row)
            await session.flush()
        return row
    except IntegrityError:
        # A concurrent request won the insert — the duplicate blocked on the
        # unique index until they committed, so their row is now visible.
        return (await session.execute(stmt)).scalars().one()
