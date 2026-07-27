"""OAuth2 refresh-token grant, shared by the accounting connectors (QBO, Xero).

Both providers rotate the refresh token on use (Xero every refresh; QBO ~daily),
so a long-running deployment must persist the value returned here. This helper
keeps the latest token in memory for the process lifetime; on restart it falls
back to the env value. Persist it yourself (a file/secret store) for production.
"""
from __future__ import annotations

import base64
import logging

import requests

log = logging.getLogger("taktline_connect")


def refresh_access_token(token_url: str, client_id: str, client_secret: str,
                         refresh_token: str, timeout: float = 30.0) -> tuple[str, str]:
    """Exchange a refresh token for (access_token, new_refresh_token)."""
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
    if new_refresh != refresh_token:
        log.warning("refresh token rotated — persist the new value to survive restarts")
    return j["access_token"], new_refresh
