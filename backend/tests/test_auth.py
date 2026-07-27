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
