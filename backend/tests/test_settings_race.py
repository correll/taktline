"""The per-company settings singletons must survive concurrent first-loads.

Two simultaneous `GET /map-settings/` on a company that has no settings row yet
used to race: both inserted, and one 500'd on the unique `companyId` index.
`get_or_create_singleton` closes that with a savepoint + re-select fallback.
"""
import asyncio
import uuid

from app.db.connection import SessionLocal, get_or_create_singleton
from app.db.tables import GlobalSettings as GlobalSettingsRow
from app.db.tables import MapSettings as MapSettingsRow
from app.models.common import utcnow
from tests.helpers import bootstrap_admin


def _race(company_id, model, **defaults):
    async def one():
        async with SessionLocal() as s:
            async with s.begin():
                row = await get_or_create_singleton(s, model, company_id, **defaults)
                return str(row.id)

    async def run():
        return await asyncio.gather(*[one() for _ in range(8)])

    return asyncio.run(run())


def test_map_settings_singleton_no_duplicate_under_concurrency(actor):
    admin = actor()
    bootstrap_admin(admin)
    cid = uuid.UUID(admin.company)
    ids = _race(cid, MapSettingsRow, floorPlanUrl=None, pixelsPerUnit=100.0,
                unit="ft", mapWidthPx=None, mapHeightPx=None, updatedAt=utcnow())
    assert len(set(ids)) == 1, f"expected one shared row, got {set(ids)}"


def test_global_settings_singleton_no_duplicate_under_concurrency(actor):
    admin = actor()
    bootstrap_admin(admin)
    cid = uuid.UUID(admin.company)
    ids = _race(cid, GlobalSettingsRow, timezone="UTC")
    assert len(set(ids)) == 1, f"expected one shared row, got {set(ids)}"
