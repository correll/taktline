"""Model Context Protocol — the framing, with no Taktline in it.

This module speaks the wire protocol an AI agent's MCP client expects and
nothing else: JSON-RPC 2.0 messages, the handshake, the tool catalogue, and the
shape of a tool result. What the tools *are* lives in `routers/mcp.py`, so the
protocol can be read (and tested) without knowing what a lot card is.

Two decisions are worth writing down, because both are load-bearing for safety
rather than for features.

**Stateless.** The Streamable HTTP transport permits a server to issue an
``Mcp-Session-Id`` and keep state behind it. This one does not: every POST
carries its own API key and is authorised on its own. There is no session to
hijack, nothing to expire, no per-connection memory an unauthenticated caller
can make the server allocate, and a revoked key stops working on the very next
call rather than when some stream is next reconnected.

**No server-initiated messages.** The spec also permits the server to open an
SSE stream and push notifications. We have nothing to push — the tools are
request/response — so ``GET /mcp`` is refused rather than left half-implemented.
A client that asks for a stream gets a clear 405 instead of one that hangs open
forever holding a database connection.

Protocol versions: the handshake echoes the client's version when we know it,
otherwise ours. That is what the spec asks for and it is why a client pinned to
an older revision still works — the message shapes this server uses have not
changed across the three revisions listed below.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("taktline.mcp")

#: Newest revision this server implements, and the one it offers when a client
#: asks for something unfamiliar.
PROTOCOL_VERSION = "2025-06-18"

#: Revisions we will echo back verbatim during the handshake.
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# JSON-RPC 2.0 error codes (the four the spec assigns meanings to, plus the
# invalid-params code MCP reuses for "no such tool").
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ── Tools ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Tool:
    """One callable exposed to the agent.

    ``scope`` is the extra API-key scope a caller must ALSO hold to invoke it.
    None means the ``mcp`` scope alone is enough — which is true of every
    read-only tool and of none of the writes. That is the whole permission
    model: connecting and changing something are separately granted, so the
    default agent an admin can create is one that can look but not touch.

    The ``*_hint`` flags become MCP tool annotations. They are advisory to the
    client — a hint is not a guard, and the scope check is the guard — but they
    are what lets a well-behaved agent ask before it does something it cannot
    take back.
    """

    name: str
    title: str
    description: str
    input_schema: dict
    handler: Callable[..., Awaitable[Any]]
    scope: Optional[str] = None
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True

    def describe(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                # Nothing here reaches outside this company's own records.
                "openWorldHint": False,
            },
        }


@dataclass
class Registry:
    tools: list[Tool] = field(default_factory=list)

    def add(self, tool: Tool) -> Tool:
        if any(t.name == tool.name for t in self.tools):
            raise ValueError(f"duplicate MCP tool {tool.name!r}")
        self.tools.append(tool)
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return next((t for t in self.tools if t.name == name), None)

    def visible(self, granted: set[str]) -> list[Tool]:
        """The tools this caller may actually invoke.

        A tool whose scope the key does not carry is not listed at all, rather
        than listed and refused. An agent plans against the catalogue it is
        given: showing it `cancel_order` and then refusing the call wastes a
        turn and teaches it to retry. Absent means absent.
        """
        return [t for t in self.tools if t.scope is None or t.scope in granted]


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _result(msg_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": payload}


def _error(msg_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def text_result(payload: Any, *, is_error: bool = False) -> dict:
    """A tool result carrying JSON as a text block.

    Deliberately text rather than the newer ``structuredContent`` field: that
    one is only meaningful alongside a declared output schema, and a client
    that validates it strictly rejects the whole call on any drift. A JSON
    string in a text block is understood by every client at every revision, and
    the model reads it the same way.
    """
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def dispatch(
    message: Any,
    *,
    registry: Registry,
    granted: set[str],
    deps: Any,
    server_info: dict,
    instructions: str = "",
) -> Optional[dict]:
    """Handle one JSON-RPC message. Returns the response, or None for a
    notification (which by definition gets no reply)."""

    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "Expected a JSON-RPC message object")

    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(msg_id, INVALID_PARAMS, "params must be an object")

    # A message with no method is a *response* to something we sent. We never
    # send requests, so there is nothing it can be answering.
    if not isinstance(method, str):
        return None if msg_id is None else _error(msg_id, INVALID_REQUEST, "Missing method")

    is_notification = "id" not in message

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": server_info,
            "instructions": instructions,
        })

    if method.startswith("notifications/"):
        return None                       # initialized, cancelled, progress …

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": [t.describe() for t in registry.visible(granted)]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(msg_id, INVALID_PARAMS, "arguments must be an object")
        tool = registry.get(name) if isinstance(name, str) else None
        if tool is None or (tool.scope is not None and tool.scope not in granted):
            # One answer for "no such tool" and "your key may not call it", so
            # the catalogue cannot be probed for what this company has enabled.
            return _error(msg_id, INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            payload = await tool.handler(deps, args)
            return _result(msg_id, text_result(payload))
        except ToolError as exc:
            await _undo(deps)
            return _result(msg_id, text_result(str(exc), is_error=True))
        except Exception as exc:                                   # noqa: BLE001
            await _undo(deps)
            # The agent gets a sentence; the traceback stays in our logs. An
            # internal error message is where stack frames, SQL and table names
            # leak, and here they would leak to a third party's model.
            log.exception("MCP tool %s failed", name)
            detail = _safe_detail(exc)
            return _result(msg_id, text_result(
                f"The tool failed: {detail}" if detail else
                "The tool failed unexpectedly. Nothing was changed.",
                is_error=True))

    if is_notification:
        return None
    return _error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")


class ToolError(Exception):
    """A tool refusing its input or its situation — the agent's problem to fix,
    and safe to show it verbatim."""


async def _undo(deps: Any) -> None:
    """Roll back before reporting a failed tool call.

    A tool error is returned as a *successful* JSON-RPC response carrying
    ``isError``, which is what lets the model read and react to it. But the
    request is still inside one transaction that commits when the response is
    built, so without this a write that failed halfway would be committed
    halfway — an order released with only some of its precursor lots seeded.
    """
    rollback = getattr(deps, "rollback", None)
    if rollback is None:
        return
    try:
        result = rollback()
        if inspect.isawaitable(result):
            await result
    except Exception:                                              # noqa: BLE001
        log.exception("MCP rollback failed")


def _safe_detail(exc: Exception) -> str:
    """The message from an exception we raised on purpose, or nothing.

    FastAPI's HTTPException carries text written for a caller ("Order not
    found", "No route from the current station"), which is exactly what the
    agent needs. Anything else is an internal failure whose text was written
    for us, not for a stranger's model.
    """
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        msg = detail.get("message")
        if isinstance(msg, str):
            return msg
    return ""
