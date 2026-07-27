"""Anonymous sandbox: one-click account with hard capability limits."""

from tests.helpers import Actor, png_bytes

STATION_BODY = {
    "name": "S1", "description": "", "adapterType": None, "adapterConfig": {},
    "color": None, "icon": None,
    "position": {"x": 1, "y": 1, "width": 60, "height": 60},
}


def _sandbox() -> Actor:
    a = Actor()
    r = a.req("POST", "/auth/sandbox")
    assert r.status_code == 200, r.text
    a.company = r.json()["companyId"]
    return a


def test_sandbox_can_build_and_run_a_line():
    a = _sandbox()
    me = a.req("GET", "/auth/me").json()
    assert me["user"]["isSandbox"] is True
    assert me["companies"][0]["role"] == "super_admin"

    st = a.req("POST", "/stations/", STATION_BODY)
    assert st.status_code == 201
    proc = a.req("POST", "/processes/", {"name": "Line"})
    assert proc.status_code == 201


def test_sandbox_capability_limits():
    a = _sandbox()
    # No floor-plan upload
    r = a.req("POST", "/map-settings/upload-floor-plan",
              files={"file": ("plan.png", png_bytes(), "image/png")})
    assert r.status_code == 403
    # No invitations
    r = a.req("POST", f"/companies/{a.company}/invitations",
              {"email": "friend@example.com", "role": "user"})
    assert r.status_code == 403
    # No API keys
    r = a.req("POST", "/api-keys/", {"name": "k", "scopes": ["orders"]})
    assert r.status_code == 403
    # No extra companies
    r = a.req("POST", "/companies/", {"name": "Escape Co", "timezone": "UTC"})
    assert r.status_code == 403
    # No order release
    r = a.req("POST", "/orders/", {"source": "manual", "productTemplateId": "x", "quantity": 1})
    assert r.status_code == 403


def test_sandbox_row_quota_is_enforced(monkeypatch):
    from app.deps import auth as auth_deps
    monkeypatch.setitem(auth_deps.SANDBOX_LIMITS, "stations", 2)
    a = _sandbox()
    assert a.req("POST", "/stations/", {**STATION_BODY, "name": "A"}).status_code == 201
    assert a.req("POST", "/stations/", {**STATION_BODY, "name": "B"}).status_code == 201
    r = a.req("POST", "/stations/", {**STATION_BODY, "name": "C"})
    assert r.status_code == 403 and "Sandbox limit" in r.text


def test_expired_sandbox_accounts_are_swept():
    import asyncio
    from datetime import timedelta
    from sqlalchemy import select
    from app.core.sandbox_gc import sweep_once
    from app.db.connection import SessionLocal
    from app.db.tables import User
    from app.models.common import utcnow

    a = _sandbox()
    email = a.req("GET", "/auth/me").json()["user"]["email"]

    async def age_and_sweep():
        async with SessionLocal() as s:
            row = (await s.execute(select(User).where(User.email == email))).scalars().one()
            row.createdAt = utcnow() - timedelta(days=30)
            await s.commit()
        removed = await sweep_once()
        async with SessionLocal() as s:
            gone = (await s.execute(select(User).where(User.email == email))).scalars().first() is None
        return removed, gone

    removed, gone = asyncio.run(age_and_sweep())
    assert removed >= 1 and gone
    assert a.req("GET", "/auth/me").status_code == 401   # session cascaded away


def test_usage_is_not_attributable_via_raw_header():
    """A stranger naming someone else's company id must not move their meter."""
    from app.core import usage
    victim = Actor()
    from tests.helpers import bootstrap_admin
    bootstrap_admin(victim, company="Victim Metrics Co")
    before = dict(usage._pending_api)

    outsider = Actor()                              # unauthenticated client
    r = outsider.req("GET", "/cards/", headers={"X-Company-Id": victim.company})
    assert r.status_code == 401                     # never reaches the data
    after = dict(usage._pending_api)
    assert after.get(victim.company, 0) == before.get(victim.company, 0)

    # …but the victim's own authenticated call does move their meter.
    victim.req("GET", "/cards/")
    assert dict(usage._pending_api).get(victim.company, 0) > before.get(victim.company, 0)


def test_sandbox_is_resumable_not_recreated():
    """Clicking "try it" again — or coming back from the marketing site — must
    return the line the visitor already built, not mint an empty one."""
    a = _sandbox()
    first = a.company
    a.req("POST", "/stations/", {**STATION_BODY, "name": "My station"})

    r = a.req("POST", "/auth/sandbox")            # same browser, same cookie jar
    assert r.status_code == 200, r.text
    assert r.json()["companyId"] == first
    assert r.json().get("resumed") is True
    names = [s["name"] for s in a.req("GET", "/stations/").json()]
    assert names == ["My station"]                # the work is still there

    # A different browser still gets its own sandbox.
    other = _sandbox()
    assert other.company != first


def test_sandbox_session_outlives_the_normal_idle_window():
    """An 8-hour idle timeout would lose the line overnight; a sandbox session
    idles for as long as the account survives the sweep."""
    import asyncio
    from datetime import timedelta
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import AuthSession, User
    from app.models.common import utcnow

    a = _sandbox()
    email = a.req("GET", "/auth/me").json()["user"]["email"]

    async def age_session(hours: int):
        async with SessionLocal() as s:
            uid = (await s.execute(select(User.id).where(User.email == email))).scalar_one()
            row = (await s.execute(
                select(AuthSession).where(AuthSession.userId == uid))).scalars().first()
            row.lastSeenAt = utcnow() - timedelta(hours=hours)
            await s.commit()

    asyncio.run(age_session(24))                  # overnight and then some
    assert a.req("GET", "/auth/me").status_code == 200
    asyncio.run(age_session(24 * 9))              # past the 7-day sandbox window
    assert a.req("GET", "/auth/me").status_code == 401
