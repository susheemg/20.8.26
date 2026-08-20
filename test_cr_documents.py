"""CR-5 document-backed certificates + document store."""
import sys, os, base64
os.environ["BRO_TRUST_HEADER"]="1"; os.environ.pop("ANTHROPIC_API_KEY",None)
sys.path.insert(0,"/home/claude/tprm")
from fastapi.testclient import TestClient
from app.bro_app import create_app
H={"x-user":"admin"}
def _c(): return TestClient(create_app("sqlite:///:memory:"))
def _v(c): return c.post("/api/v2/vendors", json={"legal_name":"Acme"}, headers=H).json()["vendor_id"]
def _b64(t): return base64.b64encode(t).decode()

def test_cert_ingest_creates_linked_record():
    c=_c(); v=_v(c)
    doc=_b64(b"ISO 27001:2022 Issued by: BSI 2024-01-01 2027-01-01")
    r=c.post("/api/v2/certificates/ingest", json={"vendor_id":v,"files":[{"filename":"c.txt","content_type":"text/plain","data_b64":doc}]}, headers=H).json()
    cert=r["certificates"][0]
    assert cert["type"]=="ISO 27001"
    assert cert["artefact_id"].startswith("ART-")
    assert cert["doc_link"].startswith("/api/v2/documents/DOC-")

def test_uploaded_doc_retrievable():
    c=_c(); v=_v(c)
    doc=_b64(b"SOC 2 Type II report")
    r=c.post("/api/v2/certificates/ingest", json={"vendor_id":v,"files":[{"filename":"s.txt","content_type":"text/plain","data_b64":doc}]}, headers=H).json()
    did=r["certificates"][0]["doc_id"]
    g=c.get(f"/api/v2/documents/{did}", headers=H)
    assert g.status_code==200 and b"SOC 2" in g.content

def test_multi_doc_upload():
    c=_c(); v=_v(c)
    files=[{"filename":f"c{i}.txt","content_type":"text/plain","data_b64":_b64(b"ISO 9001 2024-01-01 2026-01-01")} for i in range(3)]
    r=c.post("/api/v2/certificates/ingest", json={"vendor_id":v,"files":files}, headers=H).json()
    assert len(r["certificates"])==3

def test_size_guard():
    c=_c()
    big=_b64(b"x"*(16*1024*1024))
    r=c.post("/api/v2/documents/upload", json={"files":[{"filename":"b.bin","data_b64":big}]}, headers=H)
    assert r.status_code==422

def test_cert_links_in_artefact_list():
    c=_c(); v=_v(c)
    doc=_b64(b"Cyber Essentials 2025-01-01 2026-01-01")
    c.post("/api/v2/certificates/ingest", json={"vendor_id":v,"files":[{"filename":"ce.txt","content_type":"text/plain","data_b64":doc}]}, headers=H)
    al=c.get(f"/api/v2/artefacts?vendor_id={v}", headers=H).json()
    assert any(a.get("doc_link") for a in al)

def test_gap_when_unreadable():
    c=_c(); v=_v(c)
    doc=_b64(b"random unrelated text with no cert markers")
    r=c.post("/api/v2/certificates/ingest", json={"vendor_id":v,"files":[{"filename":"x.txt","content_type":"text/plain","data_b64":doc}]}, headers=H).json()
    assert len(r["certificates"][0]["gaps"])>0  # risk-averse: flags gaps, doesn't invent

if __name__=="__main__":
    import traceback
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    p=0
    for t in tests:
        try: t(); print(f"PASS  {t.__name__}"); p+=1
        except Exception: print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(tests)} passed"); sys.exit(0 if p==len(tests) else 1)
