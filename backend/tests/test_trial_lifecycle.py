"""The trial drip and the day-15 deletion.

Two failure modes this file exists for, and they pull in opposite directions:
sending an email twice (which reads as a broken company), and deleting an
account that had just been paid for (which is unrecoverable).

The clock is moved rather than waited on: every state that matters here is
reached by the passage of days.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest

from app.core import lifecycle, plans
from app.core.config import settings
from app.models.common import utcnow
from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


class Outbox:
    """Captures what the mailer was asked to send.

    Filtered by recipient. `send_due_emails` sweeps every trial in the database
    and the suite shares one, so an unfiltered outbox would collect whatever
    other tests happened to leave behind — and the failure would look like a
    cadence bug rather than the test-isolation bug it is.
    """

    def __init__(self):
        self.all = []
        self.only = None

    async def send(self, to, subject, body):
        self.all.append({"to": to, "subject": subject, "body": body})

    def watch(self, email: str) -> None:
        self.only = email

    @property
    def sent(self):
        return [m for m in self.all if self.only is None or m["to"] == self.only]

    def kinds(self):
        """Map subjects back to beat kinds, so assertions read in the domain."""
        by_subject = {b.subject: b.kind for b in lifecycle.BEATS}
        return [by_subject.get(m["subject"], m["subject"]) for m in self.sent]


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "cloud", raising=False)
    monkeypatch.setattr("app.core.email.mailer", box, raising=False)
    return box


def _started_days_ago(company_id: str, days: float, **fields):
    """Put the trial clock where we need it."""
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def go():
        async with SessionLocal() as s:
            row = (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(company_id)))).scalars().first()
            row.planCode = fields.pop("planCode", plans.TRIAL)
            row.trialEndsAt = (utcnow() - timedelta(days=days)
                               + timedelta(days=plans.TRIAL_DAYS))
            for k, v in fields.items():
                setattr(row, k, v)
            await s.commit()
    asyncio.run(go())


def _company_exists(company_id: str) -> bool:
    from app.db.connection import SessionLocal
    from app.db.tables import Company

    async def go():
        async with SessionLocal() as s:
            return await s.get(Company, uuid.UUID(company_id)) is not None
    return asyncio.run(go())


def _sweep():
    return asyncio.run(lifecycle.send_due_emails())


def _delete(limit=50):
    return asyncio.run(lifecycle.delete_expired_trials(limit=limit))


def _drain():
    """Clear expired trials other tests left behind.

    The sweep is global by design — it has to be — so a test that asserts on
    *how many* were deleted must first make sure the only expired trials are
    its own. Without this the counts drift with test ordering, which is the
    worst kind of flake: it fails in CI and passes alone.
    """
    while _delete(limit=200):
        pass


# ─── The cadence ─────────────────────────────────────────────────────────────

def test_the_five_emails_arrive_on_their_days(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Drip co"))

    expected = [
        (0, ["welcome"]),
        (3, ["welcome", "progress"]),
        (7, ["welcome", "progress", "week_left"]),
        (11, ["welcome", "progress", "week_left", "three_days"]),
        (14, ["welcome", "progress", "week_left", "three_days", "final"]),
    ]
    for day, want in expected:
        _started_days_ago(a.company, day)
        _sweep()
        assert outbox.kinds() == want, f"on day {day}"


def test_a_restart_does_not_re_send(outbox, actor):
    """The claim is an INSERT with ON CONFLICT DO NOTHING, so a second sweep —
    or a second worker, or a redeploy mid-run — finds the row already there."""
    a = actor()
    outbox.watch(bootstrap_admin(a, "Restart co"))
    _started_days_ago(a.company, 8)
    _sweep()
    first = list(outbox.kinds())
    assert first == ["welcome", "progress", "week_left"]

    for _ in range(3):
        _sweep()
    assert outbox.kinds() == first


def test_converting_stops_the_chain(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Converting co"))
    _started_days_ago(a.company, 3)
    _sweep()
    assert outbox.kinds() == ["welcome", "progress"]

    _started_days_ago(a.company, 12, planCode="pro_50", stripeStatus="active")
    _sweep()
    assert outbox.kinds() == ["welcome", "progress"], "a paying customer got a trial nag"


def test_a_trial_that_never_started_gets_nothing(outbox, actor):
    """The clock starts at first verified login. Until then there is no trial to
    count down, and a welcome email would be premature."""
    a = actor()
    outbox.watch(bootstrap_admin(a, "Unstarted co"))
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import Subscription

    async def clear():
        async with SessionLocal() as s:
            row = (await s.execute(select(Subscription).where(
                Subscription.companyId == uuid.UUID(a.company)))).scalars().first()
            row.trialEndsAt = None
            await s.commit()
    asyncio.run(clear())

    _sweep()
    assert outbox.sent == []


# ─── What the emails say ─────────────────────────────────────────────────────

def test_the_welcome_names_every_price(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Priced co"))
    _started_days_ago(a.company, 0)
    _sweep()
    body = outbox.sent[0]["body"]
    for code in plans.PURCHASABLE:
        assert plans.PLANS[code].label in body
        assert f"{plans.PLANS[code].monthly_cents // 100:,}" in body
    assert "$199" in body.replace(" ", "")   # the on-premise add-on


def test_the_day_three_email_reads_the_actual_line(outbox, actor):
    """It is a line-doctor reading of their own data, not a form letter — which
    is the only reason a three-day-in email is worth sending at all."""
    a = actor()
    outbox.watch(bootstrap_admin(a, "Reading co"))
    a.req("POST", "/stations/", {**STATION, "name": "Cutting"})
    a.req("POST", "/stations/", {**STATION, "name": "Welding"})
    _started_days_ago(a.company, 3)
    _sweep()

    progress = next(m for m in outbox.sent if "line so far" in m["subject"])
    assert "2  stations" in progress["body"] or "2 stations" in progress["body"]
    # With no routes drawn, the doctor's first topology finding should appear.
    assert "connected" in progress["body"].lower()


def test_the_final_email_says_what_will_be_lost(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Losing co"))
    a.req("POST", "/stations/", {**STATION, "name": "Cutting"})
    _started_days_ago(a.company, 14)
    _sweep()
    final = next(m for m in outbox.sent if "ends tomorrow" in m["subject"])
    assert "deleted" in final["body"]
    assert "share links" in final["body"]


def test_every_email_carries_a_way_out(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Escape co"))
    _started_days_ago(a.company, 14)
    _sweep()
    assert len(outbox.sent) == 5
    for m in outbox.sent:
        assert "/trial/stop?company=" in m["body"]
        assert "tab=billing" in m["body"]


# ─── Opt-out ─────────────────────────────────────────────────────────────────

def _stop_url(company_id: str) -> str:
    return (f"/billing/trial/stop?company={company_id}"
            f"&token={lifecycle._token_for(company_id)}")


def test_the_opt_out_link_describes_before_it_destroys(outbox, actor):
    """GET only describes. A destructive GET is deleted by the first corporate
    mail filter that prefetches links, and the customer never sees the email."""
    a = actor()
    outbox.watch(bootstrap_admin(a, "Describing co"))
    a.req("POST", "/stations/", {**STATION, "name": "Cutting"})

    r = Actor().req("GET", _stop_url(a.company))
    assert r.status_code == 200
    assert r.json()["companyName"] == "Describing co"
    assert r.json()["stations"] == 1
    assert _company_exists(a.company), "GET deleted the account"


def test_the_opt_out_link_deletes_on_post(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Leaving co"))
    assert Actor().req("POST", _stop_url(a.company)).status_code == 204
    assert not _company_exists(a.company)


def test_a_forged_opt_out_token_is_a_404(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Guarded co"))
    bad = f"/billing/trial/stop?company={a.company}&token=deadbeef"
    assert Actor().req("GET", bad).status_code == 404
    assert Actor().req("POST", bad).status_code == 404
    assert _company_exists(a.company)


def test_an_opt_out_link_cannot_destroy_a_paying_account(outbox, actor):
    """The token lives forever in an old email. Once they are paying, it must
    stop being a delete button."""
    a = actor()
    outbox.watch(bootstrap_admin(a, "Paying co"))
    _started_days_ago(a.company, 3, planCode="pro_50", stripeStatus="active")
    assert Actor().req("POST", _stop_url(a.company)).status_code == 409
    assert _company_exists(a.company)


# ─── Deletion ────────────────────────────────────────────────────────────────

def test_an_expired_trial_is_deleted_a_day_late_not_on_the_hour(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Expiring co"))

    _started_days_ago(a.company, 14.5)          # trial over, inside the last day
    _delete()
    assert _company_exists(a.company), "deleted during the final 24 hours"

    _started_days_ago(a.company, 15.5)          # a full day past
    _delete()
    assert not _company_exists(a.company)


def test_deletion_never_touches_a_paid_account(outbox, actor):
    a = actor()
    outbox.watch(bootstrap_admin(a, "Safe co"))
    _started_days_ago(a.company, 40, planCode="pro_100", stripeStatus="active")
    _delete()
    assert _company_exists(a.company)


def test_deletion_leaves_the_neighbours_alone(outbox, actor):
    """The blast radius. One expired trial must take exactly one company."""
    doomed, safe_trial, paid = actor(), actor(), actor()
    bootstrap_admin(doomed, "Doomed co")
    bootstrap_admin(safe_trial, "Young co")
    bootstrap_admin(paid, "Paid co")
    _started_days_ago(doomed.company, 16)
    _started_days_ago(safe_trial.company, 2)
    _started_days_ago(paid.company, 30, planCode="basic_50", stripeStatus="active")

    _delete()
    assert not _company_exists(doomed.company)
    assert _company_exists(safe_trial.company)
    assert _company_exists(paid.company)


def test_deletion_is_capped_per_run(outbox, actor):
    """A cap is a circuit breaker: whatever goes wrong, it goes wrong slowly
    enough that somebody can pull the plug."""
    _drain()
    companies = []
    for i in range(3):
        a = actor()
        bootstrap_admin(a, f"Bulk co {i}")
        _started_days_ago(a.company, 20)
        companies.append(a.company)

    assert _delete(limit=2) == 2
    assert sum(_company_exists(c) for c in companies) == 1


def test_a_deletion_is_recorded_where_it_survives(outbox, actor):
    """`platform_audit` has no foreign keys, so it is the only table that
    outlives the company it describes."""
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import PlatformAudit

    a = actor()
    outbox.watch(bootstrap_admin(a, "Audited co"))
    _started_days_ago(a.company, 20)
    _delete()

    async def go():
        async with SessionLocal() as s:
            return (await s.execute(select(PlatformAudit).where(
                PlatformAudit.targetId == a.company))).scalars().all()

    rows = asyncio.run(go())
    assert [r.action for r in rows] == ["trial_deleted"]
    assert rows[0].detail["name"] == "Audited co"


# ─── Where it must not run ───────────────────────────────────────────────────

def test_the_drip_does_not_start_on_a_customers_own_box(monkeypatch):
    """Their server would email their staff our marketing sequence and delete
    their company on day 15."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "onprem", raising=False)
    lifecycle.stop()
    lifecycle.start()
    assert lifecycle._task is None


def test_the_drip_does_not_start_without_billing(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", None, raising=False)
    lifecycle.stop()
    lifecycle.start()
    assert lifecycle._task is None


def test_deletion_waits_out_the_first_minutes_of_a_boot():
    """A redeploy must not fire a mass delete.

    This rule lived inside the sweep loop and was wrong: the elapsed counter
    was incremented before the first check, so a freshly booted process deleted
    immediately. Nothing exercised the loop, so nothing caught it — a company
    vanished seconds after a restart during manual testing instead.
    """
    assert not lifecycle.deletion_is_due(0)
    assert not lifecycle.deletion_is_due(lifecycle._DELETE_START_DELAY - 1)
    assert lifecycle.deletion_is_due(lifecycle._DELETE_START_DELAY)
    # And the first pass of the loop must be at zero, not one interval in.
    assert lifecycle._DELETE_START_DELAY > 0
