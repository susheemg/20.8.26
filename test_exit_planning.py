import os, sys
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app.bro_app import create_app

H = {"x-user": "admin"}
c = TestClient(create_app("sqlite:///:memory:"))


def ok(cond, name):
    print(("PASS" if cond else "FAIL") + " - " + name)


# need a vendor + engagement to attach to
v = c.post("/api/v2/vendors", headers=H, json={"legal_name": "ExitCo Ltd"}).json()
vid = v.get("vendor_id") or v.get("id")
ok(vid, "vendor created")

# portfolio works on an empty estate
p = c.get("/api/v2/exit/portfolio", headers=H)
ok(p.status_code == 200 and "counts" in p.json(), "portfolio endpoint")

# trigger catalogue
cat = c.get("/api/v2/exit/triggers", headers=H).json()
ok(len(cat["catalogue"]) >= 5, "trigger catalogue returned")

# create / update a plan -> readiness computed deterministically
r = c.put(f"/api/v2/exit/plan/{vid}", headers=H, json={
    "exit_mode": "both", "strategy_type": "alternative_provider", "status": "approved",
    "data_plan": "export + certified deletion", "one_off_cost": 100000}).json()
ok("readiness" in r and isinstance(r["readiness"]["score"], int), "plan saved with readiness")
s1 = r["readiness"]["score"]

# determinism: re-save identical -> identical score
r2 = c.put(f"/api/v2/exit/plan/{vid}", headers=H, json={
    "exit_mode": "both", "strategy_type": "alternative_provider", "status": "approved",
    "data_plan": "export + certified deletion", "one_off_cost": 100000}).json()
ok(r2["readiness"]["score"] == s1, "readiness is deterministic/reproducible")

# add children -> score should not decrease, components reflect them
c.post(f"/api/v2/exit/plan/{vid}/child", headers=H, json={
    "kind": "alternative", "name": "Alt Provider", "prequalified": True, "lead_time_days": 60, "viability": 4})
for i in range(3):
    c.post(f"/api/v2/exit/plan/{vid}/child", headers=H, json={"kind": "step", "description": f"step {i}"})
c.post(f"/api/v2/exit/plan/{vid}/child", headers=H, json={"kind": "dependency", "service_name": "Payments"})
full = c.get(f"/api/v2/exit/plan/{vid}", headers=H).json()
comp = full["readiness"]["components"]
ok(comp["alternative"] == 15 and comp["impact_tolerance"] == 10 and comp["stressed_playbook"] == 15,
   "children feed readiness components")
ok(full["readiness"]["score"] >= s1, "score non-decreasing after adding children")

# log a test -> tested component rises
c.post(f"/api/v2/exit/plan/{vid}/test", headers=H, json={"method": "tabletop", "passed": True})
full2 = c.get(f"/api/v2/exit/plan/{vid}", headers=H).json()
ok(full2["readiness"]["components"]["tested"] == 20, "passing test sets tested component to 20")
ok(len(full2["tests"]) == 1, "test recorded")

# attest sets review dates
at = c.post(f"/api/v2/exit/plan/{vid}/attest", headers=H, json={}).json()
ok(at["plan"]["next_review"], "attest sets next review")

# invoke -> hands to offboarding
inv = c.post(f"/api/v2/exit/plan/{vid}/invoke", headers=H, json={"mode": "stressed"}).json()
ok(inv["status"] == "invoked", "invoke returns invoked")
after = c.get(f"/api/v2/exit/plan/{vid}", headers=H).json()
ok(after["plan"]["status"] == "invoked", "plan status becomes invoked")

# delete a child
aid = full2["alternatives"][0]["id"]
d = c.delete(f"/api/v2/exit/plan/{vid}/child/alternative/{aid}", headers=H).json()
ok(all(a["id"] != aid for a in d["alternatives"]), "child deleted")

# trigger scan endpoint runs
sc = c.post("/api/v2/exit/triggers/scan", headers=H, json={})
ok(sc.status_code == 200 and "fired" in sc.json(), "trigger scan endpoint")
