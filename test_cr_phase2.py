"""CR-6/7/8 phase 2: server-side typed-field validation."""
import sys, os
os.environ["BRO_TRUST_HEADER"]="1"; os.environ.pop("ANTHROPIC_API_KEY",None)
sys.path.insert(0,"/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H={"x-user":"admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c): return c.post("/api/v2/vendors", json={"legal_name":"Acme"}, headers=H).json()["vendor_id"]

def test_bad_email_rejected():
    c=_c(); v=_v(c)
    r=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"contact_email":"not-an-email"},"include_bank":False}, headers=H)
    assert r.status_code==422

def test_good_email_accepted():
    c=_c(); v=_v(c)
    r=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"contact_email":"ops@vendor.com"},"include_bank":False}, headers=H)
    assert r.status_code==200

def test_phone_only_plus_and_digits():
    c=_c(); v=_v(c)
    bad=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"contact_phone":"+44 (20) 7946"},"include_bank":False}, headers=H)
    assert bad.status_code==422
    good=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"contact_phone":"+442079460000"},"include_bank":False}, headers=H)
    assert good.status_code==200

def test_bad_date_rejected():
    c=_c(); v=_v(c)
    r=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"incorporation_date":"31/12/2020"},"include_bank":False}, headers=H)
    assert r.status_code==422

def test_iso_date_accepted():
    c=_c(); v=_v(c)
    r=c.put(f"/api/v2/vendor-master/{v}", json={"data":{"incorporation_date":"2020-12-31"},"include_bank":False}, headers=H)
    assert r.status_code==200

if __name__=="__main__":
    import traceback
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p+=1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p==len(tests) else 1)
