"""The MCP server: the protocol, and every lock on it.

The protocol half is cheap to test and worth testing — a handshake that answers
the wrong shape fails inside somebody else's agent, where we never see it.

The safety half is the point. This file is written as the list of things that
must stay true no matter what is added to the tool catalogue later, so each
test is named after the property rather than the endpoint:

  * off until switched on, per company;
  * a key, never a cookie;
  * reading and acting are separately granted;
  * the destructive half of the product is not reachable at all;
  * one company's agent cannot see another's floor;
  * a failed write leaves nothing behind, and tells nobody it happened;
  * credentials and customer data never leave in a tool result.
"""

import json
import uuid
from datetime import timedelta

from app.models.common import utcnow
from tests.helpers import add_member, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {}, "color": None,
           "icon": None, "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _line(a):
    """Cut → Assembly ← Fasteners, then Pack, then a warehouse.

    Every shape a station can have is present exactly once — two source queues,
    a merge, a plain one-in-one-out bench, and a storage leaf — because the role
    labels are the part of `get_line` an agent reasons hardest from. Pack in
    particular is the ordinary case, and the ordinary case is the one that was
    wrong first (reported `unconnected`)."""
    st = lambda n, **k: a.req("POST", "/stations/", {**STATION, "name": n, **k}).json()["_id"]
    cut, fast, asm = st("Cutting"), st("Fasteners"), st("Assembly")
    pack = st("Pack")
    wh = st("Warehouse", isStorage=True)
    proc = a.req("POST", "/processes/", {"name": "Widgets"}).json()["_id"]
    for load, unload in ((cut, asm), (fast, asm), (asm, pack), (pack, wh)):
        r = a.req("POST", "/routes/", {"processId": proc, "load": load,
                                       "unload": unload, "quantity": 1})
        assert r.status_code == 201, r.text
    for name, start in (("Blank", cut), ("Fastener", fast), ("Widget", asm)):
        a.req("POST", "/lot-templates/", {"name": name, "processId": proc,
                                          "startStationId": start})
    products = {t["name"]: t["_id"] for t in a.req("GET", "/lot-templates/").json()}
    return {"proc": proc, "cut": cut, "fast": fast, "asm": asm, "pack": pack,
            "wh": wh, "products": products}


def _key(a, scopes=("mcp",)):
    return a.req("POST", "/api-keys/", {"name": "agent", "scopes": list(scopes)}).json()["key"]


def _enable(a, on=True):
    r = a.req("PUT", "/global-settings/", {"mcpEnabled": on})
    assert r.status_code == 200, r.text
    return r


class Agent:
    """An MCP client: a bare HTTP caller with a key and no cookies."""

    def __init__(self, actor, key):
        self.tc = actor().tc
        self.key = key
        self._id = 0

    def raw(self, body, headers=None):
        return self.tc.post("/mcp", json=body, headers={
            "Authorization": f"Bearer {self.key}", **(headers or {})})

    def rpc(self, method, params=None):
        self._id += 1
        r = self.raw({"jsonrpc": "2.0", "id": self._id, "method": method,
                      "params": params or {}})
        assert r.status_code == 200, r.text
        return r.json()

    def call(self, tool, args=None):
        """A tool call, with the JSON payload already parsed out of the text
        block. Returns (payload, is_error)."""
        res = self.rpc("tools/call", {"name": tool, "arguments": args or {}})
        assert "result" in res, res
        text = res["result"]["content"][0]["text"]
        try:
            return json.loads(text), res["result"].get("isError", False)
        except json.JSONDecodeError:
            return text, res["result"].get("isError", False)

    def tools(self):
        return {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}


def _agent(actor, scopes=("mcp",)):
    a = actor(); bootstrap_admin(a)
    line = _line(a)
    _enable(a)
    return a, line, Agent(actor, _key(a, scopes))


# ── The protocol ─────────────────────────────────────────────────────────────

def test_initialize_answers_a_handshake(actor):
    _, _, agent = _agent(actor)
    res = agent.rpc("initialize", {"protocolVersion": "2025-06-18",
                                   "capabilities": {}, "clientInfo": {"name": "t"}})
    r = res["result"]
    assert r["protocolVersion"] == "2025-06-18"
    assert "tools" in r["capabilities"]
    assert r["serverInfo"]["name"] == "taktline"
    assert r["instructions"]


def test_an_unknown_protocol_version_gets_ours(actor):
    """The spec's negotiation: echo what the client asked for if we know it,
    otherwise answer with ours and let it decide."""
    _, _, agent = _agent(actor)
    res = agent.rpc("initialize", {"protocolVersion": "1999-01-01"})
    assert res["result"]["protocolVersion"] == "2025-06-18"

    res = agent.rpc("initialize", {"protocolVersion": "2024-11-05"})
    assert res["result"]["protocolVersion"] == "2024-11-05"


def test_a_notification_gets_no_reply(actor):
    """No id means no response — and specifically not an empty JSON object,
    which a client would try to match against a request it never sent."""
    _, _, agent = _agent(actor)
    r = agent.raw({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert r.content == b""


def test_unknown_methods_and_bad_json_are_jsonrpc_errors(actor):
    _, _, agent = _agent(actor)
    assert agent.rpc("resources/list")["error"]["code"] == -32601
    r = agent.tc.post("/mcp", content=b"{not json",
                      headers={"Authorization": f"Bearer {agent.key}",
                               "Content-Type": "application/json"})
    assert r.json()["error"]["code"] == -32700


def test_there_is_no_event_stream_and_it_says_so(actor):
    """A client that gets a hanging GET waits forever instead of using POST."""
    _, _, agent = _agent(actor)
    r = agent.tc.get("/mcp", headers={"Authorization": f"Bearer {agent.key}"})
    assert r.status_code == 405


def test_both_spellings_of_the_path_work(actor):
    """Clients differ on the trailing slash, and a redirect between them drops
    the Authorization header in some HTTP stacks."""
    _, _, agent = _agent(actor)
    for path in ("/mcp", "/mcp/"):
        r = agent.tc.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                          headers={"Authorization": f"Bearer {agent.key}"})
        assert r.status_code == 200, path
        assert r.json()["result"] == {}


# ── Off until switched on ────────────────────────────────────────────────────

def test_the_server_is_off_on_a_fresh_company(actor):
    a = actor(); bootstrap_admin(a); _line(a)
    agent = Agent(actor, _key(a))            # a valid key, with the right scope
    r = agent.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403
    assert "switched off" in r.text


def test_switching_it_off_locks_every_agent_out_at_once(actor):
    a, _, agent = _agent(actor)
    assert agent.tools()                     # working before
    _enable(a, False)
    assert agent.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 403


def test_only_a_super_admin_can_switch_it_on(actor):
    a = actor(); bootstrap_admin(a)
    member = actor(); add_member(a, member, role="admin")
    assert member.req("PUT", "/global-settings/", {"mcpEnabled": True}).status_code == 403


# ── A key, never a cookie ────────────────────────────────────────────────────

def test_a_logged_in_session_is_not_a_credential_here(actor):
    """Every other integration endpoint accepts a session as a fallback. This
    one does not, on purpose: a browser-reachable agent gateway authenticated
    by an ambient cookie is a confused deputy, and an MCP client has no browser."""
    a, _, _ = _agent(actor)
    r = a.req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_no_key_and_a_revoked_key_are_both_refused(actor):
    a, _, _ = _agent(actor)
    anon = actor().tc
    assert anon.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401

    created = a.req("POST", "/api-keys/", {"name": "k", "scopes": ["mcp"]}).json()
    agent = Agent(actor, created["key"])
    assert agent.rpc("ping")["result"] == {}
    a.req("DELETE", f"/api-keys/{created['id']}")
    assert agent.raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401


def test_a_key_without_the_mcp_scope_cannot_connect(actor):
    """An ERP connector's existing key must not silently become an agent gateway."""
    a, _, _ = _agent(actor)
    agent = Agent(actor, _key(a, ("orders", "cards:advance")))
    r = agent.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403
    assert "mcp" in r.text


# ── Reading and acting are separately granted ────────────────────────────────

READ_TOOLS = {"get_line", "find_lots", "list_orders", "get_statistics", "diagnose_line"}


def test_the_mcp_scope_alone_is_read_only(actor):
    _, _, agent = _agent(actor)
    assert agent.tools() == READ_TOOLS


def test_write_tools_appear_only_with_their_own_scope(actor):
    a = actor(); bootstrap_admin(a); _line(a); _enable(a)
    assert Agent(actor, _key(a, ("mcp", "orders"))).tools() == \
        READ_TOOLS | {"release_order", "cancel_order"}
    assert Agent(actor, _key(a, ("mcp", "cards:advance"))).tools() == \
        READ_TOOLS | {"advance_lot"}


def test_an_unlisted_tool_cannot_be_called_anyway(actor):
    """The catalogue is a convenience, not the guard. Calling a tool that was
    never listed must be refused by the same code path that hid it — and with
    the same answer as a tool that does not exist, so the catalogue cannot be
    probed for what this company has enabled."""
    _, line, agent = _agent(actor)                       # 'mcp' only
    res = agent.rpc("tools/call", {"name": "release_order", "arguments": {
        "productTemplateId": line["products"]["Widget"], "quantity": 1}})
    assert res["error"]["code"] == -32602
    assert res["error"]["message"] == "Unknown tool: release_order"

    ghost = agent.rpc("tools/call", {"name": "no_such_tool", "arguments": {}})
    assert ghost["error"]["message"] == "Unknown tool: no_such_tool"

    # and nothing was released
    assert agent.call("list_orders")[0]["orders"] == []


# ── The dangerous half is simply not there ───────────────────────────────────

def test_no_tool_can_reshape_or_destroy_the_factory(actor):
    """The floor under the whole feature. An agent may run a line; it may not
    rebuild one, empty one, or hand itself more access. If a tool is ever added
    whose name suggests otherwise, this fails and someone has to think."""
    a = actor(); bootstrap_admin(a); _line(a); _enable(a)
    # Every scope this product has, so the check sees the whole catalogue and
    # not just the read half — the mistake that made this test decorative once.
    all_scopes = [s["scope"] for s in a.req("GET", "/api-keys/scopes").json()]
    all_tools = Agent(actor, _key(a, all_scopes)).tools()
    assert len(all_tools) == 8, all_tools
    forbidden = ("station", "route", "process", "template", "product_create",
                 "delete", "remove", "reset", "member", "invit", "key",
                 "billing", "import", "export", "unmerge", "move", "handoff",
                 "settings", "user", "password")
    offenders = [t for t in all_tools for word in forbidden if word in t]
    assert not offenders, f"a tool reaches configuration or destruction: {offenders}"


def test_the_full_catalogue_is_exactly_these_eight(actor):
    """A deliberate inventory. Adding a tool should be a decision someone makes
    on purpose, with this list in front of them."""
    a = actor(); bootstrap_admin(a); _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders", "cards:advance", "reports")))
    assert agent.tools() == READ_TOOLS | {"release_order", "cancel_order", "advance_lot"}


def test_every_write_tool_is_flagged_as_one(actor):
    """The annotations a well-behaved client uses to decide whether to ask
    before acting. A write advertised as readOnly is worse than no annotation."""
    a = actor(); bootstrap_admin(a); _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders", "cards:advance")))
    by_name = {t["name"]: t["annotations"]
               for t in agent.rpc("tools/list")["result"]["tools"]}
    for name in READ_TOOLS:
        assert by_name[name]["readOnlyHint"] is True, name
    for name in ("release_order", "cancel_order", "advance_lot"):
        assert by_name[name]["readOnlyHint"] is False, name
    assert by_name["cancel_order"]["destructiveHint"] is True


# ── Tenancy ──────────────────────────────────────────────────────────────────

def test_an_agent_sees_only_its_own_companys_floor(actor):
    a, line_a, agent = _agent(actor)
    b = actor(); bootstrap_admin(b, "Other"); line_b = _line(b); _enable(b)

    names = {s["name"] for s in agent.call("get_line")[0]["stations"]}
    assert names == {"Cutting", "Fasteners", "Assembly", "Pack", "Warehouse"}

    ids = {s["id"] for s in agent.call("get_line")[0]["stations"]}
    assert line_b["asm"] not in ids


def test_a_company_id_header_cannot_redirect_an_agent(actor):
    """The key resolves its own company, so the header every other endpoint
    reads is ignored here — there is nothing to spoof."""
    a, _, agent = _agent(actor)
    b = actor(); bootstrap_admin(b, "Other"); _line(b); _enable(b)

    r = agent.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "get_line", "arguments": {}}},
                  headers={"X-Company-Id": b.company})
    payload = json.loads(r.json()["result"]["content"][0]["text"])
    assert {s["name"] for s in payload["stations"]} == \
        {"Cutting", "Fasteners", "Assembly", "Pack", "Warehouse"}


# ── The reads ────────────────────────────────────────────────────────────────

def test_get_line_names_the_roles_the_graph_actually_has(actor):
    _, line, agent = _agent(actor)
    payload, err = agent.call("get_line")
    assert not err
    roles = {s["name"]: s["roles"] for s in payload["stations"]}
    assert "merge" in roles["Assembly"]
    assert "queue" in roles["Cutting"] and "queue" in roles["Fasteners"]
    assert "storage" in roles["Warehouse"] and "end" in roles["Warehouse"]
    assert len(payload["routes"]) == 4

    # The ordinary bench — one route in, one out. It has no special shape, and
    # for a while that meant it got no label and fell through to 'unconnected',
    # which describes most of a real line as detached from itself.
    assert roles["Pack"] == ["work"]
    assert not any("unconnected" in r for r in roles.values()), roles


def test_a_station_with_no_routes_is_the_only_unconnected_one(actor):
    """The other half: 'unconnected' has to keep meaning something, or the fix
    above is just a relabelling that hides a genuinely detached station."""
    a, _, agent = _agent(actor)
    a.req("POST", "/stations/", {**STATION, "name": "Drawn but unwired"})
    roles = {s["name"]: s["roles"] for s in agent.call("get_line")[0]["stations"]}
    assert roles["Drawn but unwired"] == ["unconnected"]


def test_a_boundary_link_is_not_counted_as_a_feed(actor):
    """The mistake test_graph_reads.py exists to catch, asked of this reader:
    an ERP's demand link is not material and must not make a station a merge."""
    a = actor(); bootstrap_admin(a)
    st = lambda n, **k: a.req("POST", "/stations/", {**STATION, "name": n, **k}).json()["_id"]
    cut, asm = st("Cutting"), st("Assembly")
    erp = st("Odoo", integrationProvider="odoo", integrationRole="source")
    proc = a.req("POST", "/processes/", {"name": "L"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": proc, "load": cut, "unload": asm, "quantity": 1})
    a.req("POST", "/lot-templates/", {"name": "W", "processId": proc, "startStationId": asm})
    assert a.req("POST", "/routes/", {"processId": proc, "load": erp,
                                      "unload": asm, "quantity": 1}).status_code == 201
    _enable(a)
    agent = Agent(actor, _key(a))

    payload, _ = agent.call("get_line")
    roles = {s["name"]: s["roles"] for s in payload["stations"]}
    assert "merge" not in roles["Assembly"], \
        "a demand link was counted as a second feed"
    assert roles["Odoo"] == ["integration"]
    # and the backend's own answer agrees, which is the property that matters
    assert a.req("GET", f"/merge/{asm}").json()["isMergeStation"] is False


def test_find_lots_reports_where_units_actually_are(actor):
    a, line, agent = _agent(actor)
    a.req("POST", "/cards/", {"lotTemplateId": line["products"]["Blank"],
                              "processId": line["proc"], "lotNum": "L-1",
                              "totalQuantity": 6, "bins": {line["cut"]: {"count": 6}}})
    payload, err = agent.call("find_lots")
    assert not err and payload["count"] == 1
    lot = payload["lots"][0]
    assert lot["lotCode"] == "L-1" and lot["product"] == "Blank"
    assert lot["at"] == [{"stationId": line["cut"], "stationName": "Cutting", "units": 6}]

    # the station filter is about where units are, not where the lot started
    assert agent.call("find_lots", {"stationId": line["cut"]})[0]["count"] == 1
    assert agent.call("find_lots", {"stationId": line["asm"]})[0]["count"] == 0
    assert payload["hasMore"] is False


def test_find_lots_says_when_there_is_more(actor):
    """A short list that reads as "this is all of them" is worse than a long
    one: an agent that thinks it has seen the whole floor reasons about what is
    missing. A cap must announce itself."""
    a, line, agent = _agent(actor)
    for i in range(4):
        a.req("POST", "/cards/", {"lotTemplateId": line["products"]["Blank"],
                                  "processId": line["proc"], "lotNum": f"B-{i}",
                                  "totalQuantity": 1, "bins": {line["cut"]: {"count": 1}}})
    capped, _ = agent.call("find_lots", {"limit": 2})
    assert capped["count"] == 2 and capped["hasMore"] is True and "note" in capped

    whole, _ = agent.call("find_lots", {"limit": 50})
    assert whole["count"] == 4 and whole["hasMore"] is False


def test_statistics_and_diagnosis_answer_on_an_unmeasured_line(actor):
    """`readiness: no-data` is the honest answer, and saying so is the feature —
    a report that invents advice from no measurements is worse than none."""
    _, _, agent = _agent(actor)
    stats, err = agent.call("get_statistics")
    assert not err and isinstance(stats["stations"], list)

    diag, err = agent.call("diagnose_line")
    assert not err
    assert diag["readiness"] in ("no-data", "partial", "ready")
    assert diag["headline"]


# ── Nothing leaks ────────────────────────────────────────────────────────────

def test_bearer_credentials_and_customer_data_never_leave(actor):
    """A lot's trackingUrl and a station's supplierUrl are bearer credentials —
    anyone holding one reads that order's status or that supplier's. The ERP
    attributes riding on an order are customer names and ship-to addresses.
    None of it is needed to answer "where is this lot", and all of it would be
    handed to a third party's model."""
    a, line, agent = _agent(actor)
    a.req("PUT", f"/stations/{line['cut']}",
          {"supplierUrl": "https://supplier.example/track/abc/SECRET-SUPPLIER"})
    r = a.req("POST", "/orders/", {
        "productTemplateId": line["products"]["Blank"], "quantity": 2,
        "source": "odoo", "externalRef": "MO-9",
        "attributes": {"customer": "Jane Roe", "shipTo": "12 Privet Drive"}})
    assert r.status_code == 201, r.text
    a.req("PUT", "/global-settings/", {"orderTracking": True})

    blob = json.dumps([agent.call(t)[0] for t in
                       ("get_line", "find_lots", "list_orders")])
    for secret in ("SECRET-SUPPLIER", "supplier.example", "Jane Roe",
                   "Privet Drive", "trackingUrl", "supplierUrl"):
        assert secret not in blob, f"{secret!r} reached an agent"


# ── The writes ───────────────────────────────────────────────────────────────

def test_release_order_pulls_material_and_is_idempotent(actor):
    a = actor(); bootstrap_admin(a); line = _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders")))

    payload, err = agent.call("release_order", {
        "productTemplateId": line["products"]["Widget"], "quantity": 3,
        "externalRef": "AG-1"})
    assert not err, payload
    assert payload["released"] is True

    # Widget is assembled at a merge, so the release seeds the queues feeding it
    lots = agent.call("find_lots")[0]["lots"]
    assert {l["product"] for l in lots} == {"Blank", "Fastener"}

    again, err = agent.call("release_order", {
        "productTemplateId": line["products"]["Widget"], "quantity": 3,
        "externalRef": "AG-1"})
    assert not err
    assert again["released"] is False and again["alreadyExisted"] is True
    assert len(agent.call("find_lots")[0]["lots"]) == len(lots), "a re-release doubled the run"


def test_cancel_order_scraps_the_run(actor):
    a = actor(); bootstrap_admin(a); line = _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders")))
    agent.call("release_order", {"productTemplateId": line["products"]["Blank"],
                                 "quantity": 4, "externalRef": "AG-2"})
    assert agent.call("find_lots")[0]["count"] == 1

    out, err = agent.call("cancel_order", {"source": "agent", "externalRef": "AG-2"})
    assert not err and out["cancelled"] is True
    assert agent.call("find_lots")[0]["count"] == 0

    # re-cancelling is a no-op, not an error
    again, err = agent.call("cancel_order", {"source": "agent", "externalRef": "AG-2"})
    assert not err and again["cancelled"] is False


def test_advance_lot_follows_the_graph_and_refuses_to_leave_it(actor):
    a = actor(); bootstrap_admin(a); line = _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "cards:advance")))
    card = a.req("POST", "/cards/", {
        "lotTemplateId": line["products"]["Blank"], "processId": line["proc"],
        "lotNum": "L-2", "totalQuantity": 2,
        "bins": {line["cut"]: {"count": 2}}}).json()

    ok, err = agent.call("advance_lot", {"lotId": card["_id"], "fromStationId": line["cut"],
                                         "toStationId": line["asm"], "quantity": 2})
    assert not err, ok
    at = agent.call("find_lots", {"lotCode": "L-2"})[0]["lots"][0]["at"]
    assert at == [{"stationId": line["asm"], "stationName": "Assembly", "units": 2}]

    # There is no route Assembly → Cutting. A refusal, not a teleport.
    bad, err = agent.call("advance_lot", {"lotId": card["_id"], "fromStationId": line["asm"],
                                          "toStationId": line["cut"], "quantity": 2})
    assert err is True
    assert "route" in str(bad).lower()


def test_a_rejected_argument_comes_back_as_one_sentence(actor):
    """Pydantic's own rendering is four lines with the class name in it and the
    rule buried in the middle. The model reads this and has to act on it."""
    a = actor(); bootstrap_admin(a); line = _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders")))
    out, err = agent.call("release_order", {
        "productTemplateId": line["products"]["Widget"], "quantity": 0})
    assert err is True
    assert "\n" not in out and "OrderCreate" not in out
    assert "quantity" in out and "at least 1" in out


def test_a_failed_write_leaves_nothing_behind(actor):
    """A tool error comes back as a *successful* JSON-RPC response carrying
    isError — which is what lets the model read it — but the request is still
    one transaction that commits when the response is built. Without an explicit
    rollback a write that failed halfway would be committed halfway."""
    a = actor(); bootstrap_admin(a); line = _line(a); _enable(a)
    agent = Agent(actor, _key(a, ("mcp", "orders")))

    before = len(agent.call("find_lots")[0]["lots"])
    out, err = agent.call("release_order", {
        "productTemplateId": str(uuid.uuid4()), "quantity": 5, "externalRef": "GHOST"})
    assert err is True and "not found" in str(out).lower()

    assert len(agent.call("find_lots")[0]["lots"]) == before
    assert agent.call("list_orders")[0]["orders"] == [], "a failed release left an order row"


def test_a_refusal_rolls_back_too_and_stays_quiet(actor):
    """The same invariant on the other branch.

    A tool that refuses its situation raises ToolError; one that hits something
    unexpected raises anything else. Both are answered with isError, and BOTH
    must roll back — including the WebSocket events staged for broadcast after
    commit, or every open board would be told about a change that never landed.

    Today no shipped tool writes before raising ToolError, which is exactly why
    this is pinned with an injected one: the invariant has to hold for the tool
    somebody adds next, not just for the ones here now. (Removing either
    `_undo` call was invisible to the rest of this file — that is how this test
    came to exist.)"""
    import app.core.ws_events as ws_events
    from app.core.mcp import ToolError as CoreToolError
    from app.db.tables import Station as StationRow
    from app.routers import mcp as mcp_router

    a, line, agent = _agent(actor)
    tool = mcp_router.registry.get("get_line")
    original = tool.handler

    async def write_then_refuse(p, args):
        p.session.add(StationRow(companyId=p.ctx.company_id, name="GHOST-STATION"))
        await p.session.flush()
        ws_events.queue_event(p.session, p.ctx.company_id,
                              {"type": "card_update", "payload": {"_id": "ghost"}})
        raise CoreToolError("not today")

    broadcast: list = []

    async def spy(company_id, payload):
        broadcast.append(payload)

    was_broadcasting = ws_events._broadcast
    object.__setattr__(tool, "handler", write_then_refuse)
    ws_events.set_broadcast(spy)
    try:
        payload, err = agent.call("get_line")
    finally:
        object.__setattr__(tool, "handler", original)
        ws_events.set_broadcast(was_broadcasting)

    assert err is True and payload == "not today"
    names = {s["name"] for s in a.req("GET", "/stations/").json()}
    assert "GHOST-STATION" not in names, "a refused tool call committed its writes"
    assert broadcast == [], \
        "a refused tool call still told every open board the change had happened"


def test_an_internal_failure_does_not_leak_its_guts(actor):
    """An agent gets a sentence; the traceback stays in our logs. Internal error
    text is where stack frames, SQL and table names live, and here they would
    leak to a third party's model."""
    from app.routers import mcp as mcp_router

    _, _, agent = _agent(actor)
    tool = mcp_router.registry.get("get_line")
    original = tool.handler

    async def boom(p, args):
        raise RuntimeError("psycopg: relation \"production_orders\" does not exist")

    object.__setattr__(tool, "handler", boom)
    try:
        payload, err = agent.call("get_line")
    finally:
        object.__setattr__(tool, "handler", original)
    assert err is True
    assert "production_orders" not in str(payload)
    assert "unexpected" in str(payload).lower()


def test_billing_reaches_the_agent_too(actor, monkeypatch):
    """MCP is an integration, and the subscription gate has to bite here as it
    does everywhere else — including on the key already issued to an agent that
    is polling right now. `test_entitlements.py`'s sweep only knows that
    `require_mcp` claims to gate; this is the part that checks it does."""
    import uuid as _uuid

    from app.core.config import settings
    from tests.test_entitlements import _set_plan

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "deployment", "cloud", raising=False)

    a = actor(); bootstrap_admin(a); _line(a); _enable(a)
    _set_plan(a.company, planCode="taktline", stripeStatus="active")
    agent = Agent(actor, _key(a))
    assert agent.tools()

    # The free tier has no integrations — and therefore no agents.
    _set_plan(a.company, planCode="free", stripeStatus=None)
    r = agent.raw({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "plan_limit"

    # A locked account (payment failed, grace expired) loses it as well.
    _set_plan(a.company, planCode="taktline", stripeStatus="past_due",
              graceEndsAt=utcnow() - timedelta(minutes=1))
    assert agent.raw({"jsonrpc": "2.0", "id": 1,
                      "method": "tools/list"}).status_code in (402, 403)
    assert _uuid.UUID(a.company)          # the company itself is untouched


def test_the_scope_catalog_advertises_mcp(actor):
    """The picker in Settings → Integrations is built from this list; a scope
    missing from it cannot be granted through the UI at all."""
    a = actor(); bootstrap_admin(a)
    scopes = {s["scope"] for s in a.req("GET", "/api-keys/scopes").json()}
    assert "mcp" in scopes
