"""v4.9.0 — transport hardening + entity brain map network endpoint."""
import os
os.environ["BRO_TRUST_HEADER"] = "1"
import pytest
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"X-User": "admin"}


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(f"sqlite:///{tmp_path/'d.db'}"))


def test_gzip_on_large_responses(client):
    r = client.get("/static/app.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_static_cache_headers(client):
    r = client.get("/static/app.js")
    assert "immutable" in (r.headers.get("cache-control") or "")


def test_new_security_headers(client):
    h = client.get("/healthz").headers
    assert "camera=()" in (h.get("permissions-policy") or "")
    assert h.get("cross-origin-opener-policy") == "same-origin"
    # pre-existing set still intact
    assert h.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in (h.get("content-security-policy") or "")


def test_graph_network_shape(client):
    r = client.get("/api/v2/graph/network", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert {"nodes", "links", "counts"} <= set(d)
    ids = {n["id"] for n in d["nodes"]}
    assert all(n["type"] in ("vendor", "fourth_party", "owner", "bu") for n in d["nodes"])
    # link integrity: every endpoint resolves to a node
    assert all(l["s"] in ids and l["t"] in ids for l in d["links"])


def test_graph_network_permission_gate(client):
    assert client.get("/api/v2/graph/network").status_code in (401, 403)


def test_graph_network_node_metadata(client):
    d = client.get("/api/v2/graph/network", headers=H).json()
    v = [n for n in d["nodes"] if n["type"] == "vendor"]
    if v:
        assert "vendor_id" in v[0] and "critical" in v[0]


def test_graph_network_temporal_payload(client):
    d = client.get("/api/v2/graph/network", headers=H).json()
    assert "timeline" in d
    # any dated node carries ISO YYYY-MM-DD
    dated = [n["since"] for n in d["nodes"] if n.get("since")]
    assert all(len(x) == 10 and x[4] == "-" for x in dated)
