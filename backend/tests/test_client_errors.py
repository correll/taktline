"""Crash reports from the frontend error boundary.

The contract: reporting never fails the reporter, attribution is verified or
absent (never taken from an unverified header), and only platform staff can
read the reports back.
"""

import pytest

from app.core.config import settings
from tests.helpers import Actor, bootstrap_admin


@pytest.fixture
def owner():
    a = Actor()
    email = bootstrap_admin(a, company="Owner HQ")
    old = settings.platform_owner_emails
    settings.platform_owner_emails = email
    yield a
    settings.platform_owner_emails = old


REPORT = {"message": "boom from the view", "stack": "Error: boom\n  at LotsView",
          "componentStack": "  in LotsView", "url": "https://taktline.com/lots"}


def test_signed_in_report_is_attributed(actor, owner):
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/client-errors/", REPORT)
    assert r.status_code == 204, r.text

    rows = owner.req("GET", "/platform/client-errors/list").json()
    mine = [x for x in rows if x["message"] == "boom from the view"]
    assert mine, rows
    assert mine[0]["companyId"] == a.company           # header verified via membership
    assert mine[0]["userEmail"] is not None


def test_anonymous_report_is_accepted_unattributed(actor, owner):
    """A crash on a screen with no session still reports — a 401 here would be
    losing the crash twice."""
    a = actor()   # never signed in
    r = a.req("POST", "/client-errors/", {**REPORT, "message": "anon crash"})
    assert r.status_code == 204, r.text
    rows = owner.req("GET", "/platform/client-errors/list").json()
    mine = [x for x in rows if x["message"] == "anon crash"]
    assert mine and mine[0]["companyId"] is None and mine[0]["userEmail"] is None


def test_spoofed_company_header_is_not_trusted(actor, owner):
    """Same lesson as usage metering: attribution only after membership
    verification. A signed-in user naming someone else's company gets stored
    without a company, not filed under the victim's."""
    a = actor(); bootstrap_admin(a)
    b = actor(); bootstrap_admin(b, company="Victim Inc")
    r = a.req("POST", "/client-errors/", {**REPORT, "message": "spoof try"},
              headers={"X-Company-Id": b.company})
    assert r.status_code == 204, r.text
    rows = owner.req("GET", "/platform/client-errors/list").json()
    mine = [x for x in rows if x["message"] == "spoof try"]
    assert mine and mine[0]["companyId"] is None, mine


def test_fields_are_truncated_not_rejected(actor, owner):
    a = actor(); bootstrap_admin(a)
    r = a.req("POST", "/client-errors/", {"message": "x" * 5000, "stack": "y" * 50000})
    assert r.status_code == 204, r.text
    rows = owner.req("GET", "/platform/client-errors/list").json()
    mine = [x for x in rows if x["message"].startswith("xxx")]
    assert mine and len(mine[0]["message"]) == 1000 and len(mine[0]["stack"]) == 6000


def test_reading_reports_is_staff_only(actor):
    a = actor(); bootstrap_admin(a)
    r = a.req("GET", "/platform/client-errors/list")
    assert r.status_code == 404, r.text     # non-staff sees no such endpoint


def test_staff_can_dismiss_a_report(actor, owner):
    a = actor(); bootstrap_admin(a)
    a.req("POST", "/client-errors/", {**REPORT, "message": "one to dismiss"})
    rows = owner.req("GET", "/platform/client-errors/list").json()
    mine = next(x for x in rows if x["message"] == "one to dismiss")

    assert owner.req("DELETE", f"/platform/client-errors/{mine['id']}").status_code == 204
    after = owner.req("GET", "/platform/client-errors/list").json()
    assert not [x for x in after if x["message"] == "one to dismiss"]

    # Idempotent: a double-click is not an error.
    assert owner.req("DELETE", f"/platform/client-errors/{mine['id']}").status_code == 204


def test_dismissing_by_message_clears_every_copy(actor, owner):
    """The same crash from twenty browsers is twenty rows saying one thing."""
    a = actor(); bootstrap_admin(a)
    for _ in range(3):
        a.req("POST", "/client-errors/", {**REPORT, "message": "the same crash"})
    a.req("POST", "/client-errors/", {**REPORT, "message": "a different one"})

    r = owner.req("DELETE", "/platform/client-errors?message=the%20same%20crash")
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == 3, r.json()

    left = [x["message"] for x in owner.req("GET", "/platform/client-errors/list").json()]
    assert "the same crash" not in left
    assert "a different one" in left


def test_dismissing_is_staff_only(actor):
    a = actor(); bootstrap_admin(a)
    a.req("POST", "/client-errors/", {**REPORT, "message": "not yours"})
    assert a.req("DELETE", "/platform/client-errors").status_code == 404


def test_reports_older_than_the_window_are_swept_on_write(actor, owner):
    """Retention is enforced at write time rather than by a scheduled job —
    which only works if the write actually sweeps. Age a row past 30 days and
    the next report must take it with it."""
    import asyncio
    from datetime import timedelta
    from sqlalchemy import select, update
    from app.db.connection import SessionLocal
    from app.db.tables import ClientError
    from app.models.common import utcnow

    a = actor(); bootstrap_admin(a)
    a.req("POST", "/client-errors/", {**REPORT, "message": "ancient crash"})

    async def age():
        async with SessionLocal() as s:
            await s.execute(update(ClientError)
                            .where(ClientError.message == "ancient crash")
                            .values(createdAt=utcnow() - timedelta(days=31)))
            await s.commit()
    asyncio.run(age())

    a.req("POST", "/client-errors/", {**REPORT, "message": "fresh crash"})
    msgs = [x["message"] for x in owner.req("GET", "/platform/client-errors/list").json()]
    assert "fresh crash" in msgs
    assert "ancient crash" not in msgs, "the 31-day-old report survived the sweep"
