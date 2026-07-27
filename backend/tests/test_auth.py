import uuid

from tests.helpers import bootstrap_admin


def _email():
    return f"u-{uuid.uuid4().hex}@example.com"


def test_signup_verify_login_me(actor):
    a = actor()
    email, pw = _email(), "password-abcdef"
    r = a.req("POST", "/auth/signup", {"email": email, "password": pw, "name": "U"})
    assert r.status_code == 202
    token = r.json()["devLink"].split("token=")[1]
    assert a.req("POST", "/auth/verify-email", {"token": token}).status_code == 200
    r = a.req("POST", "/auth/login", {"email": email, "password": pw})
    assert r.status_code == 200 and r.json()["user"]["email"] == email
    assert a.req("GET", "/auth/me").json()["user"]["emailVerified"] is True


def test_login_requires_verification(actor):
    a = actor()
    email, pw = _email(), "password-abcdef"
    a.req("POST", "/auth/signup", {"email": email, "password": pw})
    assert a.req("POST", "/auth/login", {"email": email, "password": pw}).status_code == 403


def test_login_no_user_enumeration(actor):
    a = actor()
    email, pw = _email(), "password-abcdef"
    token = a.req("POST", "/auth/signup", {"email": email, "password": pw}).json()["devLink"].split("token=")[1]
    a.req("POST", "/auth/verify-email", {"token": token})
    wrong = a.req("POST", "/auth/login", {"email": email, "password": "wrong-abcdef"})
    unknown = a.req("POST", "/auth/login", {"email": _email(), "password": "password-abcdef"})
    # identical 401 + message whether the account exists or not
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_password_min_length(actor):
    a = actor()
    r = a.req("POST", "/auth/signup", {"email": _email(), "password": "short"})
    assert r.status_code == 422


def test_verify_token_single_use(actor):
    a = actor()
    token = a.req("POST", "/auth/signup", {"email": _email(), "password": "password-abcdef"}).json()["devLink"].split("token=")[1]
    assert a.req("POST", "/auth/verify-email", {"token": token}).status_code == 200
    assert a.req("POST", "/auth/verify-email", {"token": token}).status_code == 400


def test_signup_does_not_leak_existing_account(actor):
    a = actor()
    email = _email()
    a.req("POST", "/auth/signup", {"email": email, "password": "password-abcdef"})
    # signing up the same email again must not reveal that it exists
    again = a.req("POST", "/auth/signup", {"email": email, "password": "password-abcdef"})
    assert again.status_code == 202


def test_logout_revokes_session(actor):
    a = actor()
    bootstrap_admin(a)
    assert a.req("POST", "/auth/logout").status_code == 204
    assert a.req("GET", "/auth/me").status_code == 401


# ─── argon2 cost migration ───────────────────────────────────────────────────

def test_login_migrates_a_stale_argon2_hash(actor):
    """An argon2 hash carries the cost it was made with, so tuning the
    parameters only ever reaches new accounts unless a successful login
    re-hashes. Without this, every pre-existing user keeps paying the old price
    forever — on a small instance that is the difference between a 0.3 s and a
    3 s login, permanently."""
    import asyncio
    from argon2 import PasswordHasher
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import User
    from app.core.security import needs_rehash

    a = actor()
    email = bootstrap_admin(a)          # created with the CURRENT parameters
    password = "password-abcdef"

    # Rewrite the stored hash as if it had been made by an older deployment.
    stale = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
    stale_hash = stale.hash(password)
    assert needs_rehash(stale_hash), "fixture must actually differ from current cost"

    async def _set(h):
        async with SessionLocal() as s:
            u = (await s.execute(select(User).where(User.email == email))).scalars().first()
            u.passwordHash = h
            await s.commit()

    async def _get():
        async with SessionLocal() as s:
            u = (await s.execute(select(User).where(User.email == email))).scalars().first()
            return u.passwordHash

    asyncio.run(_set(stale_hash))
    assert needs_rehash(asyncio.run(_get()))

    r = a.req("POST", "/auth/login", {"email": email, "password": password})
    assert r.status_code == 200, r.text

    migrated = asyncio.run(_get())
    assert migrated != stale_hash                     # rewritten…
    assert not needs_rehash(migrated)                 # …at the current cost
    # and the account still works afterwards
    assert a.req("POST", "/auth/login",
                 {"email": email, "password": password}).status_code == 200


def test_a_wrong_password_never_rewrites_the_hash(actor):
    """The rehash must sit behind a successful verify — never on the failure
    path, where the supplied password is by definition not the user's."""
    import asyncio
    from sqlalchemy import select
    from app.db.connection import SessionLocal
    from app.db.tables import User

    a = actor()
    email = bootstrap_admin(a)

    async def _get():
        async with SessionLocal() as s:
            u = (await s.execute(select(User).where(User.email == email))).scalars().first()
            return u.passwordHash

    before = asyncio.run(_get())
    assert a.req("POST", "/auth/login",
                 {"email": email, "password": "definitely-not-it"}).status_code == 401
    assert asyncio.run(_get()) == before
