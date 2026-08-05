"""On-premise licensing: a signed file that says what this box may do, until when.

An on-premise install runs on the customer's hardware against a database they
administer, so **entitlement cannot live in a row** — they can edit it. It lives
in a file we sign and they cannot forge: Ed25519, public key baked into the
image, private key never leaving the release machine.

The licence carries an expiry, so a monthly subscription is enforceable: stop
paying and no new file is issued, the current one runs out, and the install
degrades exactly the way a lapsed cloud account does — read-only, then paused.

**The hard part is not the crypto, it is not bricking a factory.** A shop's
network dies, an outbound call fails, a firewall rule changes on a Friday. If a
licence lapse looked the same as a payment lapse, we would take a production
line down for a reason that had nothing to do with the customer. So:

- Licences are issued with a long life (`DEFAULT_DAYS`, 35 days) against a
  monthly charge, and refresh attempts start well before expiry
  (`REFRESH_AFTER_DAYS`, 21). A fortnight of no internet changes nothing.
- Expiry is followed by the same read-only grace as the cloud, not an immediate
  stop.
- A file can always be installed **by hand** (`POST /billing/licence`), so an
  air-gapped shop is never dependent on our reachability.
- If no licence is present at all, the install is unmetered. That is deliberate:
  a self-hosted evaluation, a developer machine and a CI box must all just work,
  and the enforcement is for customers who have signed a contract and been given
  a file.

The file is JSON with a detached signature:

    {"licence": {...claims...}, "signature": "<base64 ed25519 over the canonical
     JSON of `licence`>"}
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import settings

#: How long an issued licence is valid. Comfortably longer than the billing
#: period it is issued against, so an unreachable server is never the thing that
#: stops a line.
DEFAULT_DAYS = 35

#: When the install starts trying to renew — two weeks of slack before expiry.
REFRESH_AFTER_DAYS = 21

#: Read-only window after a licence expires, before the install is paused.
#: Mirrors the cloud grace period, for the same reason: whatever went wrong,
#: they can still see and export their own line.
GRACE_DAYS = 7


class LicenceError(Exception):
    pass


@dataclass(frozen=True)
class Licence:
    issued_to: str
    plan_code: str
    stations: Optional[int]
    connectors: Optional[int]
    issued_at: datetime
    expires_at: datetime
    #: Free-text, shown in Settings → Billing so an operator can tell support
    #: which box they are looking at.
    note: str = ""

    @property
    def expired(self) -> bool:
        return _now() >= self.expires_at

    @property
    def grace_ends_at(self) -> datetime:
        return self.expires_at + timedelta(days=GRACE_DAYS)

    @property
    def due_for_refresh(self) -> bool:
        return _now() >= self.issued_at + timedelta(days=REFRESH_AFTER_DAYS)

    def as_dict(self) -> dict:
        return {
            "issuedTo": self.issued_to,
            "plan": self.plan_code,
            "stations": self.stations,
            "connectors": self.connectors,
            "issuedAt": self.issued_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "note": self.note,
            "expired": self.expired,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(claims: dict) -> bytes:
    """The exact bytes that are signed.

    Sorted keys and no incidental whitespace, so a file that has been through a
    formatter, an email client or a copy-paste still verifies. Signing the raw
    file text instead would make the signature depend on how it was transported.
    """
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()


# ─── Verification ────────────────────────────────────────────────────────────

def verify(document: dict, public_key_b64: Optional[str] = None) -> Licence:
    """Parse and verify a licence document. Raises `LicenceError` on anything
    that is not a valid, correctly-signed licence."""
    key_b64 = public_key_b64 or settings.licence_public_key
    if not key_b64:
        raise LicenceError("No licence public key is configured in this build")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:                     # pragma: no cover
        raise LicenceError(f"cryptography is not installed: {exc}") from None

    claims = document.get("licence")
    signature = document.get("signature")
    if not isinstance(claims, dict) or not isinstance(signature, str):
        raise LicenceError("Not a licence file")

    try:
        key = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64))
        key.verify(base64.b64decode(signature), _canonical(claims))
    except InvalidSignature:
        raise LicenceError("This licence's signature does not match") from None
    except Exception as exc:
        raise LicenceError(f"This licence could not be read: {exc}") from None

    try:
        return Licence(
            issued_to=str(claims["issuedTo"]),
            plan_code=str(claims["plan"]),
            stations=claims.get("stations"),
            connectors=claims.get("connectors"),
            issued_at=_parse(claims["issuedAt"]),
            expires_at=_parse(claims["expiresAt"]),
            note=str(claims.get("note", "")),
        )
    except KeyError as exc:
        raise LicenceError(f"Licence is missing {exc}") from None


def _parse(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ─── Where it lives on disk ──────────────────────────────────────────────────

def _path() -> Path:
    return Path(settings.licence_file)


def load() -> Optional[Licence]:
    """The installed licence, or None if there is none or it is unreadable.

    Never raises. A corrupt file must not stop the server from booting — the
    entitlement layer treats "no valid licence" as unmetered, and an operator
    can see the problem in Settings → Billing and install a new one.
    """
    path = _path()
    if not path.is_file():
        return None
    try:
        return verify(json.loads(path.read_text(encoding="utf-8")))
    except (LicenceError, ValueError, OSError) as exc:
        print(f"[licence] ignoring {path}: {exc}")
        return None


def install(document: dict) -> Licence:
    """Verify a licence and write it to disk. Returns the parsed licence."""
    licence = verify(document)
    _path().write_text(json.dumps(document, indent=2), encoding="utf-8")
    return licence


# ─── Issuing (release machine only) ──────────────────────────────────────────

def issue(private_key_b64: str, *, issued_to: str, plan_code: str,
          stations: Optional[int] = None, connectors: Optional[int] = None,
          days: int = DEFAULT_DAYS, note: str = "") -> dict:
    """Sign a licence. Never called by the server — this is the tool the
    release machine runs, kept beside `verify` so the two cannot drift."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key_b64))
    now = _now()
    claims = {
        "issuedTo": issued_to,
        "plan": plan_code,
        "stations": stations,
        "connectors": connectors,
        "issuedAt": now.isoformat(),
        "expiresAt": (now + timedelta(days=days)).isoformat(),
        "note": note,
    }
    return {"licence": claims,
            "signature": base64.b64encode(key.sign(_canonical(claims))).decode()}


def generate_keypair() -> tuple[str, str]:
    """(private_b64, public_b64). Run once; keep the private half offline."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private = ed25519.Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (base64.b64encode(raw_private).decode(),
            base64.b64encode(raw_public).decode())
