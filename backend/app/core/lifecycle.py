"""The trial lifecycle: five emails, then deletion.

    day 0   welcome, the tiers, and a promise that reminders are coming
    day 3   what you have built, and what is still missing — a real reading
    day 7   one week left
    day 11  three days left
    day 14  24 hours; here is exactly what gets deleted
    day 15  delete

Three properties this file is built around.

**Exactly once.** Each send is claimed with `INSERT ... ON CONFLICT DO NOTHING
RETURNING` against `lifecycle_emails(companyId, kind)`. Checking "have we sent
it?" and then sending is a race, and at a cadence of days it would be a rare
and baffling one — the sort of bug that shows up as one customer, once,
receiving "three days left" twice.

**Never at boot.** `sandbox_gc` sweeps immediately on startup, and copying that
here would mean a redeploy fires a mass deletion with no operator between it
and the data. Deletion waits `_DELETE_START_DELAY` and is capped per run.

**Cloud only.** On a customer's own hardware this must not run at all, or their
server emails their staff our marketing sequence and deletes their company on
day 15.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, delete, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import plans
from .config import settings

SWEEP_INTERVAL_SECONDS = 60 * 60          # hourly; the cadence is days
_DELETE_START_DELAY = 10 * 60             # never delete in the first minutes of a boot
_DELETE_PER_RUN = 50                      # a cap is a circuit breaker, not a rate limit

_task: Optional[asyncio.Task] = None


@dataclass(frozen=True)
class Beat:
    kind: str
    #: Days since the trial started. Negative days-remaining is the tail.
    day: int
    subject: str


#: Keyed by `kind`, which is stored — renaming one would re-send that email to
#: everyone who has already had it.
BEATS = [
    Beat("welcome", 0, "Welcome to Taktline — and what happens next"),
    Beat("progress", 3, "Your line so far, and the one thing missing"),
    Beat("week_left", 7, "One week left on your Taktline trial"),
    Beat("three_days", 11, "Three days left on your Taktline trial"),
    Beat("final", 14, "Your Taktline trial ends tomorrow"),
]


# ─── Copy ────────────────────────────────────────────────────────────────────

def _price_table() -> str:
    lines = []
    for code in plans.PURCHASABLE:
        p = plans.PLANS[code]
        stations = f"up to {p.stations} stations"
        extras = "with integrations" if p.integrations else "no integrations"
        lines.append(f"  {p.label:<18} ${p.monthly_cents / 100:>6,.0f}/month   "
                     f"{stations}, {extras}")
    lines.append(f"  On-premise add-on  ${plans.ONPREM_CENTS / 100:>6,.0f}/month   "
                 f"runs on your own hardware")
    return "\n".join(lines)


def _links(company_id: str, token: str) -> tuple[str, str]:
    base = settings.frontend_base_url.rstrip("/")
    return (f"{base}/settings?tab=billing",
            f"{base}/trial/stop?company={company_id}&token={token}")


def _footer(billing_url: str, stop_url: str) -> str:
    return (f"\n\nChoose a plan: {billing_url}\n"
            f"Stop these emails and delete the account: {stop_url}\n")


def _welcome(company: str, billing: str, stop: str) -> str:
    return (
        f"Your Taktline line for {company} is live, and you have "
        f"{plans.TRIAL_DAYS} days to see whether it earns its keep.\n\n"
        f"Nothing is limited during the trial except integrations — draw your "
        f"floor, run real lots through it, and let the statistics build.\n\n"
        f"What it costs afterwards:\n\n{_price_table()}\n\n"
        f"We will send four more emails: a reading of your line in three days, "
        f"then reminders at one week, three days, and the day before it ends. "
        f"You can stop them at any time with the link below."
        + _footer(billing, stop))


def _progress(company: str, facts: dict, findings: list, readiness: str,
              billing: str, stop: str) -> str:
    built = "\n".join(f"  {v:>4}  {k}" for k, v in facts.items() if v)
    if not built:
        built = "  Nothing yet — the floor plan is the place to start."

    # Topology findings need no measurements at all, and they are the ones that
    # matter most to somebody three days in: "this line can never complete an
    # order" is worth saying long before there is a cycle time to report. An
    # earlier version replaced them with the no-timing note, which threw away
    # the only useful thing the doctor can say to a brand-new account.
    parts = []
    if findings:
        parts.append("Reading your line as it stands:\n\n" + "\n\n".join(
            f"  {f['title']}\n  {f['detail']}" for f in findings[:3]))
    elif readiness != "no-data":
        parts.append("Your line reads as healthy — nothing is structurally wrong "
                     "with it. The value from here is in the trend.")

    if readiness == "no-data":
        parts.append("Nobody has run a timer yet, so there is nothing to say "
                     "about pace. That is the next thing worth doing: open the "
                     "Operator view on a tablet at one station and press start.")

    verdict = "\n\n".join(parts) or ("There is not much on the line yet — the "
                                     "floor plan is the place to start.")

    return (f"Three days in. Here is what {company} has on Taktline:\n\n{built}\n\n"
            f"{verdict}\n\n"
            f"This is the same line doctor that runs inside the app, on your own "
            f"data. Nothing left the building to produce it."
            + _footer(billing, stop))


def _week_left(company: str, billing: str, stop: str) -> str:
    return (f"One week left on the trial for {company}.\n\n"
            f"If the board is being used, the cheapest next step is to pick a "
            f"plan — the line stays exactly as it is.\n\n{_price_table()}"
            + _footer(billing, stop))


def _three_days(company: str, billing: str, stop: str) -> str:
    return (f"Three days left on the trial for {company}.\n\n"
            f"After it ends the account is locked rather than deleted, for one "
            f"day — you can still choose a plan and pick up where you left off."
            + _footer(billing, stop))


def _final(company: str, facts: dict, billing: str, stop: str) -> str:
    built = ", ".join(f"{v} {k}" for k, v in facts.items() if v) or "your line"
    return (f"The trial for {company} ends tomorrow.\n\n"
            f"If you do nothing, the account and everything in it is deleted 24 "
            f"hours later. That means {built} — and any share links you have "
            f"posted will stop working.\n\n"
            f"Choosing a plan keeps all of it, unchanged.\n\n{_price_table()}"
            + _footer(billing, stop))


BODIES = {
    "welcome": _welcome,
    "week_left": _week_left,
    "three_days": _three_days,
}


# ─── Facts about the line ────────────────────────────────────────────────────

async def _facts(session, company_id) -> dict:
    from sqlalchemy import func
    from ..db.tables import (Card as CardRow, LotTemplate as LotTemplateRow,
                             Process as ProcessRow, Route as RouteRow,
                             Station as StationRow, WorkSession as SessionRow)

    async def count(model):
        return (await session.execute(
            select(func.count()).select_from(model)
            .where(model.companyId == company_id))).scalar_one()

    # (singular, plural) so the email does not say "1 processes" — a small
    # thing that makes a generated message read as generated.
    labels = [
        ("station", "stations", StationRow),
        ("route", "routes", RouteRow),
        ("process", "processes", ProcessRow),
        ("product", "products", LotTemplateRow),
        ("lot on the floor", "lots on the floor", CardRow),
        ("work session recorded", "work sessions recorded", SessionRow),
    ]
    out = {}
    for one, many, model in labels:
        n = await count(model)
        out[one if n == 1 else many] = n
    return out


async def _reading(session, company_id) -> tuple[list, str]:
    """The line doctor's own findings, or nothing if it cannot run."""
    try:
        from . import analysis as engine
        from . import line_snapshot

        snapshot = await line_snapshot.build(session, company_id)
        report = engine.analyse(snapshot)
    except Exception as exc:                       # noqa: BLE001
        print(f"[lifecycle] could not read line {company_id}: {exc}")
        return [], "no-data"
    # One per rule. The doctor legitimately reports the same finding for
    # several stations ("everything passes through Weld", "…through Paint"),
    # which is right in the app beside a map and reads as padding in an email.
    findings, seen = [], set()
    for f in report.findings:
        if f.rule in seen:
            continue
        seen.add(f.rule)
        findings.append({"title": f.title, "detail": f.detail})
    return findings, report.readiness


# ─── The sweep ───────────────────────────────────────────────────────────────

def _token_for(company_id) -> str:
    """A per-company opt-out token, derived rather than stored.

    Derived from the company id and the app's secret, so it needs no column and
    cannot be enumerated. It is not a session: all it authorises is "stop
    emailing this trial and delete it", and the link goes to a confirmation
    page, never straight to a deletion.
    """
    import hashlib
    import hmac

    secret = (settings.stripe_webhook_secret or settings.database_url).encode()
    return hmac.new(secret, f"trial-stop:{company_id}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def verify_token(company_id, token: str) -> bool:
    import hmac
    return hmac.compare_digest(_token_for(company_id), token or "")


async def _claim(session, company_id, kind: str, to: str) -> bool:
    """Claim this send. False means somebody (or some earlier run) has it."""
    from ..db.tables import LifecycleEmail

    claimed = (await session.execute(
        pg_insert(LifecycleEmail)
        .values(companyId=company_id, kind=kind, sentTo=to)
        .on_conflict_do_nothing(index_elements=["companyId", "kind"])
        .returning(LifecycleEmail.id)
    )).scalar()
    return claimed is not None


async def _recipient(session, company_id):
    """The company's super-admin. Trials have exactly one; if somehow several,
    the oldest membership is the person who created it."""
    from ..db.tables import Membership, User

    return (await session.execute(
        select(User).join(Membership, Membership.userId == User.id)
        .where(Membership.companyId == company_id,
               Membership.role == "super_admin",
               User.isSandbox.is_(False))
        .order_by(Membership.createdAt)
    )).scalars().first()


async def send_due_emails() -> int:
    """One pass. Returns how many emails went out."""
    from ..db.connection import SessionLocal
    from ..db.tables import Company, Subscription
    from ..models.common import utcnow
    from .email import mailer

    sent = 0
    now = utcnow()
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Subscription, Company)
            .join(Company, Company.id == Subscription.companyId)
            .where(Subscription.planCode == plans.TRIAL,
                   Subscription.trialEndsAt.isnot(None))
        )).all()

        for sub, company in rows:
            started = sub.trialEndsAt - timedelta(days=plans.TRIAL_DAYS)
            elapsed = (now - started).days
            user = await _recipient(session, sub.companyId)
            if user is None:
                continue

            for beat in BEATS:
                if elapsed < beat.day:
                    continue
                if not await _claim(session, sub.companyId, beat.kind, user.email):
                    continue

                billing, stop = _links(str(sub.companyId), _token_for(sub.companyId))
                if beat.kind == "progress":
                    facts = await _facts(session, sub.companyId)
                    findings, readiness = await _reading(session, sub.companyId)
                    body = _progress(company.name, facts, findings, readiness,
                                     billing, stop)
                elif beat.kind == "final":
                    body = _final(company.name, await _facts(session, sub.companyId),
                                  billing, stop)
                else:
                    body = BODIES[beat.kind](company.name, billing, stop)

                try:
                    await mailer.send(user.email, beat.subject, body)
                    sent += 1
                except Exception as exc:           # noqa: BLE001
                    # The claim stands. A send that failed is not retried, on
                    # purpose: retrying a mail server that is down means the
                    # customer eventually gets four copies of "three days left".
                    print(f"[lifecycle] send failed ({beat.kind} → {user.email}): {exc}")

        await session.commit()
    return sent


async def delete_expired_trials(limit: int = _DELETE_PER_RUN) -> int:
    """Delete trials that ended more than a day ago.

    One conditional statement per company rather than read-then-delete: a
    checkout completing between the read and the write would otherwise delete a
    line somebody had just paid for. The `EXISTS` clause re-checks the trial is
    still expired *as part of* the delete.
    """
    from ..db.connection import SessionLocal
    from ..db.tables import Company, Subscription
    from ..models.common import utcnow
    from . import entitlements

    cutoff = utcnow() - timedelta(days=1)
    removed = 0
    async with SessionLocal() as session:
        candidates = (await session.execute(
            select(Subscription.companyId, Company.name)
            .join(Company, Company.id == Subscription.companyId)
            .where(Subscription.planCode == plans.TRIAL,
                   Subscription.trialEndsAt.isnot(None),
                   Subscription.trialEndsAt < cutoff)
            .limit(limit)
        )).all()

        for company_id, name in candidates:
            await entitlements.release_company(session, company_id)
            result = await session.execute(
                delete(Company).where(and_(
                    Company.id == company_id,
                    exists(select(Subscription.id).where(and_(
                        Subscription.companyId == company_id,
                        Subscription.planCode == plans.TRIAL,
                        Subscription.trialEndsAt < cutoff,
                    ))),
                ))
            )
            if result.rowcount:
                removed += 1
                _audit_deleted(session, company_id, name)
        await session.commit()
    return removed


def _audit_deleted(session, company_id, name: str) -> None:
    """`platform_audit` is FK-free, so it is the only record that survives the
    deletion it describes."""
    from ..db.tables import PlatformAudit

    session.add(PlatformAudit(
        actorUserId="system", actorEmail="system@lifecycle",
        action="trial_deleted", targetType="company",
        targetId=str(company_id), detail={"name": name},
    ))


# ─── The loop ────────────────────────────────────────────────────────────────

async def _loop() -> None:
    started = 0.0
    while True:
        try:
            sent = await send_due_emails()
            if sent:
                print(f"[lifecycle] sent {sent} trial email(s)")
            started += SWEEP_INTERVAL_SECONDS
            # Deletion never runs in the first minutes after a boot: a redeploy
            # would otherwise fire a mass delete with nobody watching.
            if started >= _DELETE_START_DELAY:
                gone = await delete_expired_trials()
                if gone:
                    print(f"[lifecycle] deleted {gone} expired trial(s)")
        except Exception as exc:                   # noqa: BLE001 — never kill the app
            print(f"[lifecycle] sweep failed: {exc}")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start() -> None:
    """Cloud only. A customer's own box must never run this."""
    global _task
    if not settings.is_cloud or not settings.billing_enabled:
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
