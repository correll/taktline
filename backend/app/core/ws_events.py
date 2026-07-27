"""After-commit WebSocket card events.

Handlers stage events on the request's session (``queue_event``); the
``get_session`` dependency drains the queue and broadcasts only after the
transaction commits, so clients never receive state that later rolls back.
``main.py`` injects the actual broadcaster at startup (the same late-binding
pattern as ``plugin_registry.set_broadcast``) to avoid a circular import.
"""

from typing import Any, Awaitable, Callable, Optional

_broadcast: Optional[Callable[[Any, dict], Awaitable[None]]] = None


def set_broadcast(fn: Callable[[Any, dict], Awaitable[None]]) -> None:
    global _broadcast
    _broadcast = fn


def queue_event(session, company_id, payload: dict) -> None:
    session.info.setdefault("ws_events", []).append((company_id, payload))


async def flush_events(session) -> None:
    events = session.info.pop("ws_events", [])
    if not events or _broadcast is None:
        return
    for company_id, payload in events:
        try:
            await _broadcast(company_id, payload)
        except Exception:
            pass  # a dead socket must never fail the committed request
