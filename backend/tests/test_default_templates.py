"""A line must run — pull precursors, then merge — without an admin hand-defining
a template for every source and the merge. Default templates are auto-provisioned."""

from tests.helpers import bootstrap_admin


def _line(a):
    """Steel + Motor → Assembly (a merge) → Testing. No templates."""
    steel = a.req("POST", "/stations/", {"name": "Steel"}).json()["_id"]
    motor = a.req("POST", "/stations/", {"name": "Motor"}).json()["_id"]
    asm = a.req("POST", "/stations/", {"name": "Assembly"}).json()["_id"]
    test = a.req("POST", "/stations/", {"name": "Testing"}).json()["_id"]
    p = a.req("POST", "/processes/", {"name": "Line"}).json()["_id"]
    a.req("POST", "/routes/", {"processId": p, "load": steel, "unload": asm, "quantity": 1})
    a.req("POST", "/routes/", {"processId": p, "load": motor, "unload": asm, "quantity": 1})
    a.req("POST", "/routes/", {"processId": p, "load": asm, "unload": test, "quantity": 1})
    return {"steel": steel, "motor": motor, "asm": asm, "test": test}


def test_pull_seeds_every_branch_without_templates(actor):
    a = actor(); bootstrap_admin(a); L = _line(a)
    assert a.req("GET", "/lot-templates/").json() == []          # nothing predefined

    pull = a.req("POST", f"/merge/{L['asm']}/pull", {"quantity": 1})
    assert pull.status_code == 201, pull.text
    # both branches seeded — Motor is no longer silently skipped
    assert {s["stationName"] for s in pull.json()["sources"]} == {"Steel", "Motor"}
    # default templates were created, named after their station
    names = {t["name"] for t in a.req("GET", "/lot-templates/").json()}
    assert {"Steel", "Motor"} <= names


def test_merge_runs_without_assembly_template(actor):
    a = actor(); bootstrap_admin(a); L = _line(a)
    a.req("POST", f"/merge/{L['asm']}/pull", {"quantity": 1})

    # advance both precursor lots into the Assembly station
    for c in a.req("GET", "/cards/").json():
        st = next(iter(c["bins"]))
        a.req("POST", f"/cards/{c['_id']}/move",
              {"fromStationId": st, "toStationId": L["asm"], "quantity": c["totalQuantity"]})

    prev = a.req("GET", f"/merge/{L['asm']}").json()
    assert prev["isMergeStation"] and prev["assembliesPossible"] == 1

    res = a.req("POST", f"/merge/{L['asm']}")           # no 422 for a missing template
    assert res.status_code == 201, res.text
    assert res.json()["assemblies"] == 1
    # a default Assembly template now exists and carries the new lot
    assert "Assembly" in {t["name"] for t in a.req("GET", "/lot-templates/").json()}
