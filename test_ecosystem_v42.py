"""v4.2 interconnected ecosystem: global search, connections, schedules,
notification engine (Build 2), notable incidents (Build 3), dump-to-draft."""
import io, os, sys
sys.path.insert(0, "/home/claude/tprm")
os.environ["BRO_TRUST_HEADER"] = "1"
for k in ("ANTHROPIC_API_KEY","OPENAI_API_KEY","XAI_API_KEY","MANUS_API_KEY","NVIDIA_API_KEY","BRO_LLM_PROVIDER"):
    os.environ.pop(k, None)
from fastapi.testclient import TestClient  # noqa: E402
from app.bro_app import create_app  # noqa: E402
H = {"x-user": "admin"}; DB = "sqlite:////tmp/eco.db"

def _client():
    if os.path.exists("/tmp/eco.db"): os.remove("/tmp/eco.db")
    return TestClient(create_app(DB))

def test_global_search_finds_vendor_and_engagement():
    c = _client()
    vid = c.post("/api/v2/vendors", headers=H, json={"legal_name": "Searchable Systems Ltd"}).json()["vendor_id"]
    c.post("/api/v2/engagements", headers=H, json={"vendor_id": vid, "title": "Searchable payment rails"})
    r = c.get("/api/v1/search?q=searchable", headers=H).json()
    kinds = {x["kind"] for x in r["results"]}
    assert "vendor" in kinds and "engagement" in kinds
    assert next(x for x in r["results"] if x["kind"] == "vendor")["id"] == vid
    assert c.get("/api/v1/search?q=a", headers=H).json()["results"] == []

def test_mcp_connections_roundtrip():
    c = _client()
    r = c.post("/api/v1/connections/mcp", headers=H, json={"name": "brata-tprm", "url": "https://mcp.example.com/sse"}).json()
    assert any(x["name"] == "brata-tprm" and "untested" in x["status"] for x in r["connections"])
    c.post("/api/v1/connections/mcp/brata-tprm/delete", headers=H)
    assert c.get("/api/v1/connections/mcp", headers=H).json()["connections"] == []
    assert c.post("/api/v1/connections/mcp", headers=H, json={"name": "x"}).status_code == 400

def test_schedules_list_and_configure():
    c = _client()
    d = c.get("/api/v1/schedules", headers=H).json()
    ids = {x["id"] for x in d["schedules"]}
    assert {"monitoring_sweep","sanctions_screen","fdd_refresh","cert_expiry_scan","exit_trigger_scan","contract_expiry_scan"} <= ids
    c.post("/api/v1/schedules/sanctions_screen", headers=H, json={"enabled": True, "cadence_hours": 12})
    sc = next(x for x in c.get("/api/v1/schedules", headers=H).json()["schedules"] if x["id"] == "sanctions_screen")
    assert sc["enabled"] is True and sc["cadence_hours"] == 12

def test_notifications_all_off_by_default_and_emit_respects_switch():
    c = _client()
    d = c.get("/api/v1/notifications/catalogue", headers=H).json()
    assert len(d["catalogue"]) >= 24
    assert all(not v["enabled"] for v in d["settings"].values())
    csv = "legal_name\nQuiet Importer Ltd\n"
    c.post("/api/v2/vendors/import", headers=H, files={"file": ("v.csv", io.BytesIO(csv.encode()), "text/csv")}, data={"mode": "commit"})
    assert c.get("/api/v1/notifications/inbox", headers=H).json()["items"] == []
    c.post("/api/v1/notifications/settings", headers=H, json={"settings": {"import.completed": {"enabled": True, "audience": "risk_team"}}})
    csv2 = "legal_name\nLoud Importer Ltd\n"
    c.post("/api/v2/vendors/import", headers=H, files={"file": ("v2.csv", io.BytesIO(csv2.encode()), "text/csv")}, data={"mode": "commit"})
    inbox = c.get("/api/v1/notifications/inbox", headers=H).json()
    assert inbox["unread"] == 1 and inbox["items"][0]["type"] == "import.completed"
    assert inbox["items"][0]["audience"] == "risk_team"
    c.post("/api/v1/notifications/read", headers=H, json={})
    assert c.get("/api/v1/notifications/inbox", headers=H).json()["unread"] == 0

def test_notable_incident_always_notifies_management():
    c = _client()
    vid = c.post("/api/v2/vendors", headers=H, json={"legal_name": "Incidental Ltd"}).json()["vendor_id"]
    iid = c.post("/api/v2/incidents", headers=H, json={"vendor_id": vid, "incident_type": "Ransomware", "impact_description": "Ransomware at supplier", "severity": "Critical"}).json()["incident_id"]
    r = c.post(f"/api/v2/incidents/{iid}/notable", headers=H)
    assert r.status_code == 200 and r.json()["notable"] is True
    n = c.get("/api/v1/notifications/inbox", headers=H).json()["items"][0]
    assert n["type"] == "incident.notable" and n["forced"] == 1
    assert n["audience"] == "management" and "NOTABLE EVENT" in n["title"]
    assert c.post("/api/v2/incidents/NOPE-1/notable", headers=H).status_code == 404

def test_dump_to_draft_offline_label_matching():
    c = _client()
    doc = ("Vendor onboarding pack\nLegal name: Drafted Dynamics Ltd\nRegistration number: 09876543\n"
           "HQ country: United Kingdom\nWebsite: https://drafted.example\n")
    fields = ('[{"id":"nv_name","label":"Legal name"},{"id":"nv_reg","label":"Registration number"},'
              '{"id":"nv_hq","label":"HQ country"},{"id":"nv_web","label":"Website"},{"id":"nv_parent","label":"Parent company"}]')
    r = c.post("/api/v1/ai/dump-to-draft", headers=H, files={"files": ("pack.txt", io.BytesIO(doc.encode()), "text/plain")}, data={"fields": fields, "context": "New vendor form"})
    assert r.status_code == 200
    j = r.json()
    assert j["engine"] == "rules"
    assert j["values"]["nv_name"] == "Drafted Dynamics Ltd" and j["values"]["nv_hq"] == "United Kingdom"
    assert "nv_parent" not in j["values"]
    assert c.post("/api/v1/ai/dump-to-draft", headers=H, files={"files": ("x.exe", io.BytesIO(b"MZ"), "application/x")}, data={"fields": fields}).status_code == 415

if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try: fn(); print(f"PASS {fn.__name__}")
        except Exception as e: print(f"FAIL {fn.__name__}: {e}")
