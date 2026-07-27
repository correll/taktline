"""Split stations: a station with 2+ outgoing routes multiplies a lot into
pieces, the mirror image of a merge consuming precursors."""

from tests.helpers import Actor, bootstrap_admin

STATION = {"description": "", "adapterType": None, "adapterConfig": {},
           "color": None, "icon": None,
           "position": {"x": 1, "y": 1, "width": 60, "height": 60}}


def _line(a: Actor):
    """bar --(x4)--> tube  and  bar --> scrap   (bar is a split station)"""
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    bar, tube, scrap = st("bar"), st("tube"), st("scrap")
    proc = a.req("POST", "/processes/", {"name": "Cutting"}).json()
    a.req("POST", "/routes/", {"processId": proc["_id"], "load": bar["_id"],
                               "unload": scrap["_id"], "quantity": 1})
    r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": bar["_id"],
                                   "unload": tube["_id"], "quantity": 4})
    assert r.status_code == 201, r.text
    return bar, tube, scrap, proc


def test_split_route_may_carry_a_weight():
    a = Actor(); bootstrap_admin(a)
    _line(a)   # the weighted split route is accepted (asserted inside)


def test_advancing_through_a_split_multiplies_the_lot():
    a = Actor(); bootstrap_admin(a)
    bar, tube, _scrap, proc = _line(a)
    tmpl = a.req("POST", "/lot-templates/", {"name": "Bar", "processId": proc["_id"],
                                             "startStationId": bar["_id"]}).json()
    card = a.req("POST", "/cards/", {
        "lotTemplateId": tmpl["_id"], "processId": proc["_id"], "totalQuantity": 2,
        "bins": {bar["_id"]: {"count": 2}}, "fields": {}, "flagged": False,
        "description": "", "status": "idle"}).json()

    r = a.req("POST", f"/cards/{card['_id']}/advance",
              {"fromStationId": bar["_id"], "toStationId": tube["_id"], "quantity": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bins"][tube["_id"]]["count"] == 4     # one bar → four tubes
    assert body["bins"][bar["_id"]]["count"] == 1      # the other bar is untouched
    assert body["totalQuantity"] == 5                  # 1 bar + 4 tubes


def test_pull_through_a_split_creates_one_upstream_lot():
    """Demand for four tubes must order one bar, not four.

    bar --(x4)--> tube --> assembly <-- widget
      \--> scrap                     (bar splits; assembly merges)
    """
    a = Actor(); bootstrap_admin(a)
    bar, tube, _scrap, proc = _line(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    assembly, widget = st("assembly"), st("widget")
    for load in (tube, widget):
        r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": load["_id"],
                                       "unload": assembly["_id"], "quantity": 1})
        assert r.status_code == 201, r.text

    r = a.req("POST", f"/merge/{assembly['_id']}/pull", {"quantity": 4})
    assert r.status_code == 201, r.text
    by_station = {s["stationId"]: s["quantity"] for s in r.json()["sources"]}
    assert by_station[bar["_id"]] == 1        # one bar yields the four tubes
    assert by_station[widget["_id"]] == 4     # the 1:1 branch still needs four


def test_weight_still_rejected_on_an_unbranched_route():
    a = Actor(); bootstrap_admin(a)
    st = lambda n: a.req("POST", "/stations/", {**STATION, "name": n}).json()
    x, y = st("x"), st("y")
    proc = a.req("POST", "/processes/", {"name": "P"}).json()
    r = a.req("POST", "/routes/", {"processId": proc["_id"], "load": x["_id"],
                                   "unload": y["_id"], "quantity": 3})
    assert r.status_code == 400 and "branches" in r.text
