from tests.helpers import bootstrap_admin, add_member


def _process_with_card(admin):
    st = admin.req("POST", "/stations/", {"name": "S"}).json()
    proc = admin.req("POST", "/processes/", {"name": "P"}).json()
    tmpl = admin.req("POST", "/lot-templates/", {"name": "T", "startStationId": st["_id"]}).json()
    card = admin.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": proc["_id"],
                                         "totalQuantity": 3, "bins": {st["_id"]: {"count": 3}}}).json()
    return st, proc, card


def test_member_is_readonly_but_can_operate(actor):
    admin = actor(); bootstrap_admin(admin)
    member = actor(); add_member(admin, member, "user")
    st, proc, card = _process_with_card(admin)

    assert member.req("GET", "/stations/").status_code == 200            # view
    assert member.req("POST", "/stations/", {"name": "no"}).status_code == 403   # no config
    assert member.req("DELETE", f"/stations/{st['_id']}").status_code == 403
    assert member.req("POST", f"/cards/{card['_id']}/move",
                      {"fromStationId": st["_id"], "toStationId": st["_id"], "quantity": 1}).status_code == 403

    sess = member.req("POST", "/sessions/", {"stationId": st["_id"], "operatorId": "m", "quantity": 1})
    assert sess.status_code == 201                                        # operator work allowed
    assert member.req("POST", f"/sessions/{sess.json()['_id']}/end", {"quantity": 1}).status_code == 200
    assert member.req("PATCH", f"/cards/{card['_id']}/status", {"status": "working"}).status_code == 200


def test_operator_advance_is_route_constrained(actor):
    admin = actor(); bootstrap_admin(admin)
    member = actor(); add_member(admin, member)
    a = admin.req("POST", "/stations/", {"name": "A"}).json()
    b = admin.req("POST", "/stations/", {"name": "B"}).json()
    c = admin.req("POST", "/stations/", {"name": "C"}).json()
    proc = admin.req("POST", "/processes/", {"name": "P"}).json()
    admin.req("POST", "/routes/", {"processId": proc["_id"], "load": a["_id"], "unload": b["_id"], "quantity": 1})
    tmpl = admin.req("POST", "/lot-templates/", {"name": "T", "startStationId": a["_id"]}).json()
    card = admin.req("POST", "/cards/", {"lotTemplateId": tmpl["_id"], "processId": proc["_id"],
                                         "totalQuantity": 2, "bins": {a["_id"]: {"count": 2}}}).json()

    assert member.req("POST", f"/cards/{card['_id']}/advance",
                      {"fromStationId": a["_id"], "toStationId": b["_id"], "quantity": 1}).status_code == 200
    # no route A→C, so advance is refused
    assert member.req("POST", f"/cards/{card['_id']}/advance",
                      {"fromStationId": a["_id"], "toStationId": c["_id"], "quantity": 1}).status_code == 400


def test_last_super_admin_guard(actor):
    admin = actor(); bootstrap_admin(admin)   # the sole super-admin (company owner)
    members = admin.req("GET", f"/companies/{admin.company}/members").json()
    uid = members[0]["userId"]
    # can't demote or remove the last super-admin
    assert admin.req("PATCH", f"/companies/{admin.company}/members/{uid}", {"role": "user"}).status_code == 400
    assert admin.req("PATCH", f"/companies/{admin.company}/members/{uid}", {"role": "admin"}).status_code == 400
    assert admin.req("DELETE", f"/companies/{admin.company}/members/{uid}").status_code == 400


def test_super_admin_can_promote_through_tiers(actor):
    admin = actor(); bootstrap_admin(admin)
    member = actor(); m_email = add_member(admin, member, "user")
    members = {m["email"]: m["userId"] for m in admin.req("GET", f"/companies/{admin.company}/members").json()}
    uid = members[m_email]

    # promote to the middle 'admin' tier → may create lots but NOT config
    assert admin.req("PATCH", f"/companies/{admin.company}/members/{uid}", {"role": "admin"}).status_code == 200
    assert member.req("POST", "/stations/", {"name": "no"}).status_code == 403

    # promote to super_admin → full config now works
    assert admin.req("PATCH", f"/companies/{admin.company}/members/{uid}", {"role": "super_admin"}).status_code == 200
    assert member.req("POST", "/stations/", {"name": "ok"}).status_code == 201
    assert admin.req("PATCH", f"/companies/{admin.company}/members/{uid}", {"role": "user"}).status_code == 200


def test_middle_admin_can_create_lots_and_orders_but_not_config(actor):
    """The new middle tier: create lots + pull precursors + release orders, on top
    of operator work — but no process/floor config and no structural lot ops."""
    su = actor(); bootstrap_admin(su)
    planner = actor(); add_member(su, planner, "admin")

    # super-admin lays out the line
    steel = su.req("POST", "/stations/", {"name": "Steel"}).json()
    asm   = su.req("POST", "/stations/", {"name": "Assembly"}).json()
    wh    = su.req("POST", "/stations/", {"name": "Warehouse"}).json()
    proc  = su.req("POST", "/processes/", {"name": "P"}).json()
    for load, unload in [(steel, asm), (asm, wh)]:
        su.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"], "unload": unload["_id"], "quantity": 1})
    tmpl = su.req("POST", "/lot-templates/", {"name": "Bike", "startStationId": asm["_id"], "processId": proc["_id"]}).json()
    src  = su.req("POST", "/lot-templates/", {"name": "Steel", "startStationId": steel["_id"], "processId": proc["_id"]}).json()

    # the middle admin CAN create a lot and pull precursors
    card = planner.req("POST", "/cards/", {"lotTemplateId": src["_id"], "processId": proc["_id"],
                                           "totalQuantity": 1, "bins": {steel["_id"]: {"count": 1}}})
    assert card.status_code == 201, card.text
    assert planner.req("POST", f"/merge/{wh['_id']}/pull", {"quantity": 1}).status_code == 201
    # …and release an order
    assert planner.req("POST", "/orders/", {"productTemplateId": tmpl["_id"], "quantity": 1,
                                            "source": "manual", "externalRef": "PO-9"}).status_code == 201

    # but CANNOT do config or structural lot ops
    assert planner.req("POST", "/stations/", {"name": "no"}).status_code == 403
    assert planner.req("POST", "/routes/", {"processId": proc["_id"], "load": asm["_id"], "unload": steel["_id"], "quantity": 1}).status_code == 403
    assert planner.req("DELETE", f"/cards/{card.json()['_id']}").status_code == 403
    assert planner.req("POST", f"/cards/{card.json()['_id']}/move",
                       {"fromStationId": steel["_id"], "toStationId": asm["_id"], "quantity": 1}).status_code == 403
    assert planner.req("GET", f"/companies/{su.company}/members").status_code == 200   # can view roster
    # …but not manage members (invite is super-admin only)
    assert planner.req("POST", f"/companies/{su.company}/invitations",
                       {"email": "x@example.com", "role": "user"}).status_code == 403
