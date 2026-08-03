"""Languages: who may pick what, at which door.

Three doors, three rules (core/languages.py): signup may pick any language the
product speaks; a company declares the subset it runs in; an invited operator
picks from the company's subset, not from the whole list. The user's choice
lives in `preferences["language"]` — cross-device, no schema of its own.
"""

import uuid

from app.core import languages
from tests.helpers import Actor, bootstrap_admin


def _invite_token(admin: Actor, email: str) -> str:
    r = admin.req("POST", f"/companies/{admin.company}/invitations",
                  {"email": email, "role": "user"})
    assert r.status_code == 201, r.text
    return r.json()["devLink"].split("token=")[1]


# ─── The catalogue ───────────────────────────────────────────────────────────

def test_the_catalogue_is_what_we_think_it_is():
    """Pinned on purpose: removing a language strands every account that chose
    it, so shrinking this set must be a decision that fails a test first."""
    assert set(languages.LANGUAGES) == {"en", "es", "fr-CA", "my", "ht"}
    assert languages.DEFAULT_LANGUAGE == "en"


# ─── Signup: any language the product speaks ─────────────────────────────────

def test_signup_stores_the_chosen_language():
    a = Actor()
    email = f"op-{uuid.uuid4().hex}@example.com"
    r = a.req("POST", "/auth/signup", {"email": email, "password": "password-abcdef",
                                       "language": "ht"})
    assert r.status_code in (200, 201, 202), r.text
    token = r.json()["devLink"].split("token=")[1]
    assert a.req("POST", "/auth/verify-email", {"token": token}).status_code == 200

    b = Actor()
    b.req("POST", "/auth/login", {"email": email, "password": "password-abcdef"})
    me = b.req("GET", "/auth/me").json()
    assert me["user"]["preferences"].get("language") == "ht"


def test_signup_refuses_a_language_we_do_not_speak():
    a = Actor()
    r = a.req("POST", "/auth/signup",
              {"email": f"x-{uuid.uuid4().hex}@example.com",
               "password": "password-abcdef", "language": "tlh"})
    assert r.status_code == 422


def test_the_language_can_be_changed_later():
    """The existing preferences endpoint carries it — same door as the theme."""
    a = Actor()
    bootstrap_admin(a, "Later co")
    r = a.req("PATCH", "/auth/me/preferences", {"language": "es"})
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["language"] == "es"

    assert a.req("PATCH", "/auth/me/preferences",
                 {"language": "xx"}).status_code == 422


# ─── The company's subset ────────────────────────────────────────────────────

def test_a_company_defaults_to_every_language():
    """Inclusive until narrowed: a company that never opened Settings has not
    decided anything, and its operators may pick any language."""
    a = Actor()
    bootstrap_admin(a, "Default co")
    body = a.req("GET", "/global-settings/").json()
    assert body["supportedLanguages"] == list(languages.LANGUAGES)


def test_an_admin_narrows_the_set_and_nonsense_is_refused():
    a = Actor()
    bootstrap_admin(a, "Narrow co")
    r = a.req("PUT", "/global-settings/", {"supportedLanguages": ["en", "es", "es"]})
    assert r.status_code == 200, r.text
    assert r.json()["supportedLanguages"] == ["en", "es"]   # deduped, order kept

    assert a.req("PUT", "/global-settings/",
                 {"supportedLanguages": ["en", "xx"]}).status_code == 422
    assert a.req("PUT", "/global-settings/",
                 {"supportedLanguages": []}).status_code == 422


# ─── The invited operator picks from the company's subset ────────────────────

def test_the_invite_page_offers_the_company_languages():
    a = Actor()
    bootstrap_admin(a, "Invite co")
    a.req("PUT", "/global-settings/", {"supportedLanguages": ["en", "my"]})
    token = _invite_token(a, f"burmese-{uuid.uuid4().hex}@example.com")

    preview = Actor().req("GET", f"/invitations/{token}").json()
    assert preview["valid"] is True
    assert preview["supportedLanguages"] == ["en", "my"]


def test_an_invited_operator_cannot_pick_outside_the_set():
    """Offering a language the company does not run in would hand an operator
    a UI their supervisor cannot read over their shoulder."""
    a = Actor()
    bootstrap_admin(a, "Spanish co")
    a.req("PUT", "/global-settings/", {"supportedLanguages": ["en", "es"]})
    token = _invite_token(a, f"op-{uuid.uuid4().hex}@example.com")

    joiner = Actor()
    r = joiner.tc.post(f"/invitations/{token}/accept-signup",
                       json={"password": "password-abcdef", "language": "my"})
    assert r.status_code == 422
    assert "en, es" in r.json()["detail"]

    r = joiner.tc.post(f"/invitations/{token}/accept-signup",
                       json={"password": "password-abcdef", "language": "es"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["preferences"].get("language") == "es"
