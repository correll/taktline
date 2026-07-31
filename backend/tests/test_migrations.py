"""The migrations, run for real.

Twenty-five revisions have shipped and not one of them has ever been executed
by a test — the suite builds its schema straight from the ORM metadata, which
is the one path production never takes. So the tests prove the *models* are
coherent and say nothing about whether a customer's database can actually get
from where it is to where the models are.

Three things are checked, on a scratch database that is dropped afterwards:

  * `upgrade head` runs from empty — the path a new install takes;
  * the result **matches the ORM metadata**, which is what catches the common
    failure: a column added to `tables.py` with no revision to match, so it
    works everywhere except on a real deployment;
  * every revision can be stepped back down and up again, which is what makes
    a bad deploy recoverable rather than a restore-from-backup.

Skipped, loudly, if the server is unreachable, because a skipped test that
looks like a pass is worse than no test.
"""

import asyncio
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# `.venv/bin/alembic` carries a shebang that does not survive the venv being
# moved, so the module is invoked through the interpreter that certainly works.
ALEMBIC = [os.path.join(BASE, ".venv", "bin", "python"), "-m", "alembic"]


def _url(dbname: str) -> str:
    raw = os.environ.get("DATABASE_URL", "postgresql+asyncpg://localhost:5432/taktline_test")
    head = raw.split("://", 1)[1].rsplit("/", 1)[0]
    return f"postgresql+asyncpg://{head}/{dbname}"


async def _psql(dbname: str, *statements):
    engine = create_async_engine(_url(dbname), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as c:
            for s in statements:
                await c.exec_driver_sql(s)
    finally:
        await engine.dispose()


async def _table_names(dbname: str) -> set:
    engine = create_async_engine(_url(dbname))
    try:
        async with engine.connect() as c:
            names = await c.run_sync(lambda s: inspect(s).get_table_names())
        return {t for t in names if t != "alembic_version"}
    finally:
        await engine.dispose()


async def _columns(dbname: str, table: str) -> set:
    engine = create_async_engine(_url(dbname))
    try:
        async with engine.connect() as c:
            cols = await c.run_sync(lambda s: inspect(s).get_columns(table))
        return {c["name"] for c in cols}
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def scratch_db():
    """A database of its own, so a half-applied migration cannot damage the
    suite's own schema."""
    name = f"taktline_mig_{uuid.uuid4().hex[:10]}"
    try:
        asyncio.run(_psql("postgres", f'CREATE DATABASE "{name}"'))
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"cannot create a scratch database ({exc})")

    yield name

    asyncio.run(_psql(
        "postgres",
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}'",
        f'DROP DATABASE IF EXISTS "{name}"'))


def _alembic(scratch_db: str, *args) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(scratch_db)
    return subprocess.run([*ALEMBIC, *args], cwd=BASE, env=env,
                          capture_output=True, text=True, timeout=600)


def _tables(scratch_db: str) -> set:
    return asyncio.run(_table_names(scratch_db))


def test_upgrade_head_builds_the_schema_from_empty(scratch_db):
    r = _alembic(scratch_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr or r.stdout
    assert _tables(scratch_db), "upgrade head produced no tables"


def test_the_migrated_schema_matches_the_models(scratch_db):
    """The failure this catches: a column added to `tables.py` without a
    revision. Every test passes — they all build from the metadata — and the
    first real deployment is the one that finds out."""
    assert _alembic(scratch_db, "upgrade", "head").returncode == 0

    import app.db.tables  # noqa: F401  (register the metadata)
    from app.db.connection import Base

    migrated = _tables(scratch_db)
    declared = set(Base.metadata.tables)
    assert declared - migrated == set(), \
        f"models declare tables no migration creates: {sorted(declared - migrated)}"
    assert migrated - declared == set(), \
        f"migrations create tables no model declares: {sorted(migrated - declared)}"

    drift = {}
    for name, table in Base.metadata.tables.items():
        actual = asyncio.run(_columns(scratch_db, name))
        missing = {c.name for c in table.columns} - actual
        extra = actual - {c.name for c in table.columns}
        if missing or extra:
            drift[name] = {"missing_in_db": sorted(missing), "not_in_model": sorted(extra)}
    assert drift == {}, f"column drift between models and migrations: {drift}"


def test_the_whole_history_steps_down_and_back_up(scratch_db):
    """A revision you cannot step back out of turns a bad deploy into a restore
    from backup. Walking the full history down to base and up again is the only
    way to know each `downgrade` was ever run at all."""
    assert _alembic(scratch_db, "upgrade", "head").returncode == 0
    before = _tables(scratch_db)

    down = _alembic(scratch_db, "downgrade", "base")
    assert down.returncode == 0, down.stderr or down.stdout
    assert _tables(scratch_db) == set(), \
        f"downgrade to base left tables behind: {sorted(_tables(scratch_db))}"

    up = _alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, up.stderr or up.stdout
    assert _tables(scratch_db) == before, "the second upgrade built a different schema"


def test_there_is_exactly_one_head():
    """Two heads mean two people branched the history and nobody merged them;
    `upgrade head` then fails on a deploy with a message nobody expects."""
    r = subprocess.run([*ALEMBIC, "heads"], cwd=BASE,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr or r.stdout
    heads = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(heads) == 1, f"migration history has {len(heads)} heads:\n{r.stdout}"
