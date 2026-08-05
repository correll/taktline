"""Pytest configuration and shared fixtures.

Runs against a dedicated `taktline_test` database (create it once with
`createdb taktline_test`). Each test uses fresh, uniquely-named accounts so the
shared schema needs no per-test reset.
"""

import os

# Must be set before the app (and its Settings) are imported anywhere.
os.environ["TESTING"] = "1"
os.environ["TAKTLINE_DEV"] = "1"
os.environ["COOKIE_SECURE"] = "0"
os.environ["CORS_ORIGINS"] = "http://localhost:3000,https://app.example.com"
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost:5432/taktline_test")

# The developer's .env may carry REAL Stripe credentials (it did, the day
# billing went live). The suite must start from "billing disabled" — both
# because tests assert that default and because a test slipping past a mock
# must find no key to spend with. Tests that want billing use the `stripe`
# fixture, which sets fakes explicitly.
for _var in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
             "STRIPE_PRICE_TAKTLINE", "STRIPE_PRICE_ONPREM"):
    os.environ[_var] = ""

import asyncio

import pytest

from tests.helpers import Actor


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the ORM schema in the test DB once per session."""
    from app.db.connection import Base, engine
    import app.db.tables  # noqa: F401  (register tables on the metadata)

    async def build():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()  # drop setup-loop connections (NullPool)

    asyncio.run(build())
    yield


@pytest.fixture
def actor():
    """Factory: each call returns a fresh, independent API client."""
    return lambda: Actor()
