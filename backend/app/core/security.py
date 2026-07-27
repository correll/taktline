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

from .config import settings

# Cost is configurable because it is deployment-dependent: the same parameters
# that are comfortable on a multi-core host make a login take seconds on a
# small one. See the notes on `argon2_*` in config.py.
_ph = PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_cost_kib,
    parallelism=settings.argon2_parallelism,
)

# Pre-computed hash used to equalize timing when logging in with an unknown
# email, so response time doesn't reveal whether an account exists. Built with
# the *current* parameters so the decoy costs what a real verify costs.
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
    """True when this hash was made with parameters other than the current ones.

    An argon2 hash carries the cost it was created with, so an old hash keeps
    verifying at the *old* price forever. Re-hashing on a successful login is
    what actually migrates a deployment onto new parameters — in either
    direction: cheaper after tuning for a small instance, stronger after moving
    to a bigger one.
    """
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

