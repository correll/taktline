"""Client-side crash reports — the error boundary's memory.

The frontend error boundary turns a render crash into a message and a Reload
button, which is right for the person standing at the screen. But its only
sink was ``console.error``, so the moment they reloaded, the crash was
unknowable — "the system said something went wrong during my demo" with no way
to ever learn what. This endpoint is the answer: the boundary posts the error
here (and stashes it in localStorage) before the user reloads.

Design constraints, in order:

- **Reporting must never fail the reporter.** No required auth — the crash may
  be on a screen with no session, and a 401 on the report would be losing the
  crash twice. Attribution is best-effort: the session is resolved when there
  is one, and the company header is *only trusted after membership
  verification* (same lesson as usage metering — an unverified header is an
  invitation to pollute another tenant's diagnostics).
- **It is an abuse surface**, so: hard rate limit per IP, hard truncation of
  every field, and a rolling retention window instead of unbounded growth.
- **Rows survive account deletion** (no FKs) — a crash report from a deleted
  sandbox is still a crash report; sandbox visitors are exactly who hit the
  odd paths.

Reading them is platform-staff only: ``GET /platform/client-errors/list``.
The bare ``/platform/client-errors`` is left to the SPA, which renders
them as a page with a copy-for-support button.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ratelimit import limiter
from ..db.connection import SESSION_SCOPE, get_session, parse_uuid
from ..db.tables import ClientError as ClientErrorRow, Membership, User, AuthSession
from ..core.security import hash_token
from ..models.common import utcnow
from datetime import timedelta

router = APIRouter(prefix="/client-errors", tags=["client-errors"])

RETENTION_DAYS = 30
_MAX = {"message": 1000, "stack": 6000, "componentStack": 6000, "url": 500, "appVersion": 100}


class ClientErrorReport(BaseModel):
    message: str
    stack: Optional[str] = None
    componentStack: Optional[str] = None
    url: Optional[str] = None
    appVersion: Optional[str] = None


def _clip(v: Optional[str], key: str) -> str:
    return (v or "")[: _MAX[key]]


@router.post("/", status_code=204)
@limiter.limit("10/minute")
async def report_client_error(request: Request, body: ClientErrorReport,
                              session: AsyncSession = Depends(get_session, **SESSION_SCOPE)):
    # Best-effort attribution — never a reason to reject the report.
    user_email, company_id = None, None
    token = request.cookies.get("taktline_session")
    if token:
        row = (await session.execute(
            select(AuthSession, User).join(User, AuthSession.userId == User.id)
            .where(AuthSession.tokenHash == hash_token(token))
        )).first()
        if row is not None:
            auth, user = row
            # Sessions are revoked by deletion in this schema, so presence +
            # unexpired is the whole check.
            if auth.expiresAt > utcnow():
                user_email = user.email
                claimed = parse_uuid(request.headers.get("X-Company-Id", ""))
                if claimed is not None:
                    member = (await session.execute(
                        select(Membership.id).where(Membership.userId == user.id,
                                                    Membership.companyId == claimed).limit(1)
                    )).first()
                    if member is not None:
                        company_id = claimed

    session.add(ClientErrorRow(
        companyId=company_id,
        userEmail=user_email,
        message=_clip(body.message, "message"),
        stack=_clip(body.stack, "stack"),
        componentStack=_clip(body.componentStack, "componentStack"),
        url=_clip(body.url, "url"),
        appVersion=_clip(body.appVersion, "appVersion"),
        userAgent=(request.headers.get("user-agent") or "")[:300],
    ))
    # Rolling retention, settled at write time: errors are rare enough that one
    # extra DELETE per report is cheaper than a scheduled sweep to maintain.
    await session.execute(delete(ClientErrorRow).where(
        ClientErrorRow.createdAt < utcnow() - timedelta(days=RETENTION_DAYS)))
