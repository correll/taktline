"""OAuth2 refresh-token grant, shared by the accounting connectors (QBO, Xero).

Both providers rotate the refresh token on use (Xero every refresh; QBO ~daily)
and invalidate the previous one, so the value in the environment goes stale the
first time a connector runs. Keeping the new token only in memory means the next
restart authenticates with a dead token and never recovers — so the rotated value
is written to a small JSON store on disk (``TOKEN_STORE``, default
``.taktline-tokens.json`` in the working directory) and read back at startup in
preference to the env value.

Point ``TOKEN_STORE`` at a persistent volume when running in a container; on a
purely ephemeral filesystem you are back to re-pasting the token by hand after
every redeploy.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger("taktline_connect")

DEFAULT_STORE = ".taktline-tokens.json"


def _store_path() -> Path:
    return Path(os.environ.get("TOKEN_STORE") or DEFAULT_STORE)


def load_refresh_token(provider: str, fallback: str) -> str:
    """The freshest refresh token for ``provider``: the persisted one if there is
    one, otherwise the value configured in the environment."""
    path = _store_path()
    try:
        if path.exists():
            saved = (json.loads(path.read_text()) or {}).get(provider)
            if saved:
                return saved
    except (OSError, ValueError) as e:
        log.warning("could not read the token store at %s (%s) — falling back to "
                    "the configured refresh token", path, e)
    return fallback


def save_refresh_token(provider: str, token: str) -> None:
    path = _store_path()
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    data[provider] = token
    try:
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)                  # it is a credential
        tmp.replace(path)                     # atomic — never a half-written store
    except OSError as e:
        log.error("could not persist the rotated %s refresh token to %s (%s) — this "
                  "connector will fail to authenticate after a restart; set "
                  "TOKEN_STORE to a writable, persistent path", provider, path, e)


def refresh_access_token(token_url: str, client_id: str, client_secret: str,
                         refresh_token: str, timeout: float = 30.0,
                         provider: str | None = None) -> tuple[str, str]:
    """Exchange a refresh token for (access_token, new_refresh_token). When
    ``provider`` is given, a rotated token is persisted to the token store."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        token_url, timeout=timeout,
        headers={"Authorization": f"Basic {basic}",
                 "Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    r.raise_for_status()
    j = r.json()
    new_refresh = j.get("refresh_token", refresh_token)
    if new_refresh != refresh_token and provider:
        save_refresh_token(provider, new_refresh)
        log.info("%s refresh token rotated — persisted to %s", provider, _store_path())
    return j["access_token"], new_refresh
