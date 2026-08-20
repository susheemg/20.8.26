"""Supply-chain concentration graph + delivery/receiving engagement fields."""
import sys, os
os.environ["BRO_TRUST_HEADER"]="1"; os.environ.pop("ANTHROPIC_API_KEY",None)
sys.path.insert(0,"/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H={"x-user":"admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _seed(c, pairs):
    for nm,loc in pairs:
        v=c.post("/api/v2/vendors", json={"legal_name":nm}, headers=H).json()["vendor_id"]
        e=c.post("/api/v2/engagements", json={"vendor_id":v,"title":"svc"}, headers=H).json()["engagement_id"]
        c.put(f"/api/v2/engagement-register/{e}", json={"data":{"delivery_location":loc,"receiving_location":"United Kingdom"}}, headers=H)

def test_delivery_receiving_fields_persist():
    c=_c()
    v=c.post("/api/v2/vendors", json={"legal_name":"Acme"}, headers=H).json()["vendor_id"]
    e=c.post("/api/v2/engagements", json={"vendor_id":v,"title":"svc"}, headers=H).json()["engagement_id"]
    c.put(f"/api/v2/engagement-register/{e}", json={"data":{"delivery_location":"India","receiving_location":"United Kingdom"}}, headers=H)
    ext=c.get(f"/api/v2/engagement-register/{e}", headers=H).json()["ext"]
    assert ext["delivery_location"]=="India"
    assert ext["receiving_location"]=="United Kingdom"

def test_concentration_graph_shape():
    c=_c(); _seed(c, [("A","India"),("B","India"),("C","United Kingdom")])
    g=c.get("/api/v2/management/concentration", headers=H).json()
    assert "nodes" in g and "edges" in g and "locations" in g and "hubs" in g
    assert g["summary"]["vendors"]==3

def test_concentration_detects_hub():
    c=_c(); _seed(c, [("A","India"),("B","India"),("C","India"),("D","United Kingdom")])
    g=c.get("/api/v2/management/concentration", headers=H).json()
    india=[l for l in g["locations"] if l["country"]=="India"][0]
    assert india["count"]==3  # geographic concentration hub

def test_locations_aggregated_for_map():
    c=_c(); _seed(c, [("A","Singapore"),("B","Singapore"),("C","United States")])
    g=c.get("/api/v2/management/concentration", headers=H).json()
    countries={l["country"] for l in g["locations"]}
    assert "Singapore" in countries and "United States" in countries

if __name__=="__main__":
    import traceback
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p+=1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p==len(tests) else 1)
