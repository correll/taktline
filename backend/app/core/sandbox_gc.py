"""Expiry sweep for anonymous sandbox accounts.

The public /auth/sandbox endpoint creates a throwaway user + company per
visitor. Without a janitor those accumulate forever, so this deletes sandbox
users (and the companies where they are the only member) once they are older
than SANDBOX_TTL_DAYS. Runs once at startup and daily thereafter; FK cascades
remove the stations/cards/sessions underneath.
"""

import asyncio
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete, exists, select

SANDBOX_TTL_DAYS = 7
SWEEP_INTERVAL_SECONDS = 24 * 60 * 60

_task: Optional[asyncio.Task] = None


async def sweep_once() -> int:
    """Delete expired sandbox accounts; returns how many users were removed."""
    from ..db.connection import SessionLocal
    from ..db.tables import Company, Membership, User
    from ..models.common import utcnow

    cutoff = utcnow() - timedelta(days=SANDBOX_TTL_DAYS)
    async with SessionLocal() as session:
        expired = (await session.execute(
            select(User.id).where(User.isSandbox.is_(True), User.createdAt < cutoff)
        )).scalars().all()
        if not expired:
            return 0
        # Companies whose only members are expiring sandbox users go too.
        company_ids = (await session.execute(
            select(Membership.companyId).where(Membership.userId.in_(expired)).distinct()
        )).scalars().all()
        await session.execute(delete(User).where(User.id.in_(expired)))
        await session.flush()
        from . import entitlements
        for cid in company_ids:
            still_used = (await session.execute(
                select(exists().where(Membership.companyId == cid))
            )).scalar()
            if not still_used:
                await entitlements.release_company(session, cid)
                await session.execute(delete(Company).where(Company.id == cid))
        await session.commit()
        return len(expired)


async def _loop() -> None:
    while True:
        try:
            removed = await sweep_once()
            if removed:
                print(f"[sandbox-gc] removed {removed} expired sandbox account(s)")
        except Exception as exc:            # noqa: BLE001 — never kill the app
            print(f"[sandbox-gc] sweep failed: {exc}")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_event_loop().create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
