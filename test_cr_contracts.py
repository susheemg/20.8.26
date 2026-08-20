"""CR-12 contract gap from document + engagement inheritance."""
import sys, os, base64
os.environ["BRO_TRUST_HEADER"]="1"; os.environ.pop("ANTHROPIC_API_KEY",None)
sys.path.insert(0,"/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H={"x-user":"admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _b64(t): return base64.b64encode(t).decode()
def _ve(c, band="HIGH"):
    v=c.post("/api/v2/vendors", json={"legal_name":"Acme"}, headers=H).json()["vendor_id"]
    e=c.post("/api/v2/engagements", json={"vendor_id":v,"title":"SaaS"}, headers=H).json()["engagement_id"]
    c.put(f"/api/v2/engagement-register/{e}", json={"data":{"inherent_band":band,"personal_data":True,"cross_border":True}}, headers=H)
    return v,e

def test_inherits_band_from_engagement():
    c=_c(); v,e=_ve(c,"HIGH")
    doc=_b64(b"confidentiality clause and governing law England")
    r=c.post("/api/v2/contracts/gap-from-document", json={"file":{"filename":"m.txt","content_type":"text/plain","data_b64":doc},"engagement_id":e}, headers=H).json()
    assert r["inherited_from_engagement"] is True
    assert r["inherent_band"]=="HIGH"

def test_other_vendor_requires_band():
    c=_c()
    doc=_b64(b"some contract text")
    r=c.post("/api/v2/contracts/gap-from-document", json={"file":{"filename":"m.txt","content_type":"text/plain","data_b64":doc},"other_name":"Foo Ltd"}, headers=H)
    assert r.status_code==422

def test_other_vendor_with_band_ok():
    c=_c()
    doc=_b64(b"confidentiality clause")
    r=c.post("/api/v2/contracts/gap-from-document", json={"file":{"filename":"m.txt","content_type":"text/plain","data_b64":doc},"other_name":"Foo Ltd","inherent_band":"MODERATE"}, headers=H)
    assert r.status_code==200
    assert r.json()["inherited_from_engagement"] is False

def test_extracts_terms_and_links_doc():
    c=_c(); v,e=_ve(c)
    doc=_b64(b"This contract has confidentiality, termination rights, and a limitation of liability cap.")
    r=c.post("/api/v2/contracts/gap-from-document", json={"file":{"filename":"m.txt","content_type":"text/plain","data_b64":doc},"engagement_id":e}, headers=H).json()
    assert "confidentiality" in r["extracted_terms"]["present"]
    assert r["doc_link"].startswith("/api/v2/documents/")

def test_unreadable_document_flagged():
    c=_c(); v,e=_ve(c)
    # tiny binary-ish content -> not readable as terms
    doc=_b64(b"\x00\x01")
    r=c.post("/api/v2/contracts/gap-from-document", json={"file":{"filename":"m.bin","content_type":"application/octet-stream","data_b64":doc},"engagement_id":e}, headers=H).json()
    assert r["readable"] is False

if __name__=="__main__":
    import traceback
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p+=1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p==len(tests) else 1)
