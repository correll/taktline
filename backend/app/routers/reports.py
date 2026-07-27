"""Read-only reporting feeds for BI tools (Power BI, Grafana, Metabase, …).

Authenticated by a `reports`-scoped API key (or a member session). These are the
join-free, flat shapes a dashboard's JSON/Web connector wants — no pagination
games, capped for safety.
"""
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.connection import get_session
from ..db.tables import LotTemplate as LotTemplateRow, ProductionOrder as OrderRow
from ..deps.auth import CompanyContext, require_scope

router = APIRouter(prefix="/reports", tags=["reports"])

_reports_access = require_scope("reports", session_role="user")


@router.get("/orders")
async def report_orders(status: Optional[str] = None, limit: int = 5000,
                        ctx: CompanyContext = Depends(_reports_access),
                        session: AsyncSession = Depends(get_session)):
    """Flat order feed — one row per production order, product resolved to its
    template name. The primary BI dataset."""
    stmt = select(OrderRow).where(OrderRow.companyId == ctx.company_id)
    if status:
        stmt = stmt.where(OrderRow.status == status)
    orders = (await session.execute(
        stmt.order_by(OrderRow.createdAt.desc()).limit(min(limit, 20000))
    )).scalars().all()

    names = {t.id: t.name for t in (await session.execute(
        select(LotTemplateRow).where(LotTemplateRow.companyId == ctx.company_id)
    )).scalars().all()}

    return [{
        "orderId": str(o.id),
        "source": o.source,
        "externalRef": o.externalRef,
        "product": names.get(o.productTemplateId),
        "quantity": o.quantity,
        "quantityDone": o.quantityDone,
        "status": o.status,
        "createdAt": o.createdAt,
        "updatedAt": o.updatedAt,
    } for o in orders]


@router.get("/throughput")
async def report_throughput(ctx: CompanyContext = Depends(_reports_access),
                            session: AsyncSession = Depends(get_session)):
    """Daily completed-order rollup: [{date, orders, units}] ascending by date.
    A ready-made time series for a throughput chart."""
    completed = (await session.execute(
        select(OrderRow).where(
            OrderRow.companyId == ctx.company_id,
            OrderRow.status == "completed",
        )
    )).scalars().all()

    by_day: dict[str, dict] = defaultdict(lambda: {"orders": 0, "units": 0})
    for o in completed:
        day = o.updatedAt.date().isoformat()
        by_day[day]["orders"] += 1
        by_day[day]["units"] += o.quantityDone
    return [{"date": d, **v} for d, v in sorted(by_day.items())]
