from tests.helpers import bootstrap_admin


def test_cross_tenant_isolation(actor):
    a = actor(); bootstrap_admin(a, "A")
    b = actor(); bootstrap_admin(b, "B")

    a.req("POST", "/stations/", {"name": "A-Station"})
    sb = b.req("POST", "/stations/", {"name": "B-Station"}).json()

    names = {s["name"] for s in a.req("GET", "/stations/").json()}
    assert "A-Station" in names and "B-Station" not in names

    # A can't fetch B's station id (404, not 403 — no existence leak)
    assert a.req("GET", f"/stations/{sb['_id']}").status_code == 404
    # A presenting B's company header → 403 (not a member)
    assert a.req("GET", "/stations/", headers={"X-Company-Id": b.company}).status_code == 403
    # A can't wipe B's data
    assert a.req("POST", "/admin/reset", {}, headers={"X-Company-Id": b.company}).status_code == 403


def test_company_context_required(actor):
    a = actor(); bootstrap_admin(a)
    a.company = None  # drop the X-Company-Id header
    assert a.req("GET", "/stations/").status_code == 400


def test_unauthenticated_blocked(actor):
    a = actor()  # never logs in
    assert a.req("GET", "/stations/").status_code == 401
