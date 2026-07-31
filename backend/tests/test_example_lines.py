"""Every line the repo ships, imported and run.

An example that cannot be imported is worse than no example: it is a promise
the product breaks on first contact. These walk the whole `examples/` folder,
so a file added later is covered the day it lands, and they check the two
things a reader assumes — that it loads, and that work can actually flow
through it.
"""

import json
from pathlib import Path

import pytest

from tests.helpers import Actor, bootstrap_admin

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.json"))


def _ids(p: Path) -> str:
    return p.stem


def test_the_folder_is_not_empty():
    """Guards the guard: a glob that matches nothing turns every parameterised
    test below into a silent pass."""
    assert len(EXAMPLES) >= 3, [p.name for p in EXAMPLES]


@pytest.mark.parametrize("example", EXAMPLES, ids=_ids)
def test_the_example_imports(actor, example: Path):
    a = actor(); bootstrap_admin(a)
    doc = json.loads(example.read_text())
    r = a.req("POST", "/map-io/import", doc)
    assert r.status_code == 200, f"{example.name}: {r.text}"

    assert len(a.req("GET", "/stations/").json()) == len(doc["stations"])
    assert len(a.req("GET", "/processes/").json()) == len(doc["processes"])
    assert len(a.req("GET", "/lot-templates/").json()) == len(doc["templates"])
    assert len(a.req("GET", "/routes/").json()) == len(doc["routes"])


@pytest.mark.parametrize("example", EXAMPLES, ids=_ids)
def test_the_example_survives_a_round_trip(actor, example: Path):
    """Export what was imported and import THAT: a document the product cannot
    reproduce from its own state is a document that will rot."""
    a = actor(); bootstrap_admin(a)
    assert a.req("POST", "/map-io/import", json.loads(example.read_text())).status_code == 200
    exported = a.req("GET", "/map-io/export").json()

    b = actor(); bootstrap_admin(b)
    assert b.req("POST", "/map-io/import", exported).status_code == 200
    again = b.req("GET", "/map-io/export").json()

    def shape(d):
        return (sorted(s["name"] for s in d["stations"]),
                sorted(p["name"] for p in d["processes"]),
                sorted(t["name"] for t in d["templates"]),
                sorted((r["quantity"], r["process"]) for r in d["routes"]))
    assert shape(again) == shape(exported), example.name


@pytest.mark.parametrize("example", EXAMPLES, ids=_ids)
def test_an_order_can_be_released_into_the_example(actor, example: Path):
    """The line has to do something, not merely load. Ordering the product an
    ERP raises demand against must seed real lots at real queues — and never
    onto the ERP's own node, which is the one thing a partner may not hold."""
    a = actor(); bootstrap_admin(a)
    assert a.req("POST", "/map-io/import", json.loads(example.read_text())).status_code == 200

    stations = {s["_id"]: s for s in a.req("GET", "/stations/").json()}
    partners = {sid for sid, s in stations.items() if s.get("integrationProvider")}
    routes = a.req("GET", "/routes/").json()
    demand_targets = {r["unload"] for r in routes if r["load"] in partners}
    assert demand_targets, f"{example.name} has no integration raising demand"

    products = [t for t in a.req("GET", "/lot-templates/").json()
                if t.get("startStationId") in demand_targets]
    assert products, f"{example.name}: nothing is made where demand lands"

    for product in products:
        ref = f"EX-{product['_id'][:8]}"
        r = a.req("POST", "/orders/", {"productTemplateId": product["_id"], "quantity": 1,
                                       "source": "manual", "externalRef": ref})
        assert r.status_code == 201, f"{example.name}/{product['name']}: {r.text}"
        seeded = [c for c in a.req("GET", "/cards/").json() if c["lotNum"] == ref]
        assert seeded, f"{example.name}/{product['name']}: released nothing"
        for c in seeded:
            assert not (set(c["bins"]) & partners), c["bins"]
