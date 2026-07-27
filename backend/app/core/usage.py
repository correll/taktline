"""Per-company usage metering (API requests + WebSocket messages per month).

The request path only touches an in-memory dict (`bump_api` / `bump_ws` — no
I/O); a background task started from the app lifespan flushes the deltas into
`usage_counters` every FLUSH_SECONDS with an upsert-increment. Counts flushed
for a company that was deleted in the meantime are dropped (the pre-filter
against `companies` also swallows garbage X-Company-Id headers).
"""

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

FLUSH_SECONDS = 30

_pending_api: dict[str, int] = defaultdict(int)
_pending_ws: dict[str, int] = defaultdict(int)
_task: Optional[asyncio.Task] = None


def bump_api(company_id: Optional[str], n: int = 1) -> None:
    if company_id:
        _pending_api[company_id] += n


def bump_ws(company_id, n: int = 1) -> None:
    if company_id and n > 0:
        _pending_ws[str(company_id)] += n


def month_bucket(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def flush() -> None:
    """Write pending deltas to usage_counters (upsert-increment)."""
    global _pending_api, _pending_ws
    if not _pending_api and not _pending_ws:
        return
    api, ws = _pending_api, _pending_ws
    _pending_api, _pending_ws = defaultdict(int), defaultdict(int)

    from ..db.connection import SessionLocal
    from ..db.tables import Company, UsageCounter

    deltas: dict[uuid.UUID, list[int]] = {}
    for raw, n in api.items():
        try:
            deltas.setdefault(uuid.UUID(raw), [0, 0])[0] += n
        except ValueError:
            continue
    for raw, n in ws.items():
        try:
            deltas.setdefault(uuid.UUID(raw), [0, 0])[1] += n
        except ValueError:
            continue
    if not deltas:
        return

    month = month_bucket()
    try:
        async with SessionLocal() as session:
            existing = set((await session.execute(
                select(Company.id).where(Company.id.in_(list(deltas))))).scalars().all())
            for cid in existing:
                api_n, ws_n = deltas[cid]
                stmt = pg_insert(UsageCounter).values(
                    companyId=cid, month=month, apiRequests=api_n, wsMessages=ws_n,
                ).on_conflict_do_update(
                    index_elements=[UsageCounter.companyId, UsageCounter.month],
                    set_={
                        "apiRequests": UsageCounter.apiRequests + api_n,
                        "wsMessages": UsageCounter.wsMessages + ws_n,
                    },
                )
                await session.execute(stmt)
            await session.commit()
    except Exception:
        pass  # metering must never take the app down; deltas for this window are lost


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(FLUSH_SECONDS)
        await flush()


def start_flush_task() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_event_loop().create_task(_flush_loop())


async def stop_flush_task() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
    await flush()   # final drain on shutdown
