"""What the backend says the graph is — written down where the frontend reads it.

The frontend re-derives graph judgements the backend already owns: which
stations are merges, which fan out, where work accumulates. It has to — the
board and the floor plan draw those labels without asking the server about
every station. Three bugs have come from the two answers drifting apart: the
merge modal grouped by raw routes and showed every branch twice, the split
lanes counted a handoff link as a branch, and the pull button vanished from a
station the backend was perfectly happy to pull at.

None of those were caught by either side's tests, because each side agreed with
itself. So the answer is checked in — `contracts/station-roles.json`, generated
from the backend's own reasoning over the shipped example lines — and both
sides assert against it. If the backend's rule changes, this test fails until
the file is regenerated; when the file changes, the frontend's test
(`graph.contract.test.ts`) fails until it agrees. Neither can move alone.
"""

import json
from pathlib import Path

from tests.helpers import Actor, bootstrap_admin

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "station-roles.json"
EXAMPLES = sorted((ROOT / "examples").glob("*.json"))


def _roles_now(actor) -> dict:
    out = {}
    for ex in EXAMPLES:
        a = actor(); bootstrap_admin(a)
        assert a.req("POST", "/map-io/import", json.loads(ex.read_text())).status_code == 200
        names = {s["_id"]: s["name"] for s in a.req("GET", "/stations/").json()}
        out[ex.stem] = {
            names[sid]: bool(a.req("GET", f"/merge/{sid}").json().get("isMergeStation"))
            for sid in names
        }
    return out


def test_the_contract_file_exists_and_covers_every_example():
    assert CONTRACT.exists(), f"missing {CONTRACT}"
    have = json.loads(CONTRACT.read_text())
    assert sorted(have) == sorted(e.stem for e in EXAMPLES), \
        "the contract does not describe the same lines the repo ships"
    assert any(v for line in have.values() for v in line.values()), \
        "no station in the contract is a merge — the fixture is vacuous"


def test_the_backend_still_says_what_the_contract_says(actor):
    """Regenerate with:

        cd backend && .venv/bin/python -m pytest tests/test_graph_contract.py \\
            --regenerate-contract
    """
    expected = json.loads(CONTRACT.read_text())
    actual = _roles_now(actor)
    assert actual == expected, (
        "the backend's view of the graph changed.\n"
        "If that was intentional, regenerate contracts/station-roles.json and let "
        "the frontend test fail until it agrees.")
