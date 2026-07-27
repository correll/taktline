"""Password hashing (argon2id) and secure-token helpers.

- Passwords: argon2id via argon2-cffi.
- Tokens (session / email-verify / password-reset / invite): a random URL-safe
  value is handed to the client, and only its SHA-256 hash is stored at rest so
  a database leak does not expose usable tokens. Comparison is constant-time.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_ph = PasswordHasher()

# Pre-computed hash used to equalize timing when logging in with an unknown
# email, so response time doesn't reveal whether an account exists.
_DUMMY_HASH = _ph.hash("timing-equalization-placeholder")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except Argon2Error:
        return False


def dummy_verify() -> None:
    """Burn roughly one argon2 verify's worth of time (unknown-email path)."""
    try:
        _ph.verify(_DUMMY_HASH, "wrong")
    except Argon2Error:
        pass


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# ── Opaque tokens ─────────────────────────────────────────────────────────────
def generate_token() -> str:
    """A fresh, high-entropy, URL-safe token to hand to a client."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The at-rest representation of a token (never store the raw value)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


def generate_api_key() -> tuple[str, str]:
    """Return (full_key, display_prefix). Only hash_token(full_key) is stored."""
    full = "tk_" + secrets.token_urlsafe(24)
    return full, full[:11]   # e.g. tk_ab12cd34

