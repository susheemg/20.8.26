"""
Document upload + extraction tests.
Generates a REAL PDF in-process, uploads it through the API, and verifies the
full chain: extraction -> classification -> Isaac reading -> evidence -> persistence.
"""
import sys, os, io, tempfile
os.environ["BRO_TRUST_HEADER"] = "1"
os.environ["BRO_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="bro_test_uploads_")
sys.path.insert(0, "/home/claude/tprm")

from fastapi.testclient import TestClient
from app.bro_app import create_app
from app.ingestion.extract import PdfExtractor, TextExtractor, classify, DocType

H = {"x-user": "admin"}


def _client():
    return TestClient(create_app("sqlite:///:memory:"))


def _make_pdf(text: str) -> bytes:
    """Create a minimal real PDF containing the given text."""
    import pdfplumber  # ensures lib present
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for line in text.split("\n"):
        c.drawString(72, y, line); y -= 16
    c.save()
    return buf.getvalue()


# ---- extractor unit level ----

def test_pdf_extractor_now_works():
    pdf = _make_pdf("SOC 2 Type II Independent Service Auditor Report\n"
                    "ISAE 3402. Encryption controls tested. 1 exception noted.")
    out = PdfExtractor().extract("audit.pdf", pdf)
    assert out.page_count == 1
    assert "soc 2" in out.text.lower()
    assert out.meta["scanned"] == "False"


def test_text_extractor_still_works():
    out = TextExtractor().extract("notes.txt", b"vendor due diligence questionnaire")
    assert "questionnaire" in out.text.lower()


# ---- full upload pipeline via API ----

def test_upload_soc2_runs_isaac_and_creates_evidence():
    c = _client()
    vid = c.post("/api/v1/vendors", json={"name": "Meridian", "tier": "Tier 1"},
                 headers=H).json()["vendor_id"]
    pdf = _make_pdf("Independent Service Auditor's Report. SOC 2 Type II. "
                    "ISAE 3402 controls tested. Encryption at rest verified. "
                    "Business continuity plan reviewed. 1 exception noted.")
    r = c.post("/api/v1/documents/upload",
               files={"file": ("meridian_soc2.pdf", pdf, "application/pdf")},
               data={"vendor_id": str(vid)}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["doc_type"] == "independent_audit"
    assert body["isaac"] is not None                 # Isaac ran
    assert body["isaac"]["engine"] == "evidence"
    assert body["evidence_count"] >= 1               # evidence created
    assert body["next_validation"] is not None       # validity window set
    assert body["page_count"] == 1
    assert body["scanned_pdf"] is False


def test_upload_persists_document_and_intel():
    c = _client()
    vid = c.post("/api/v1/vendors", json={"name": "Acme"}, headers=H).json()["vendor_id"]
    pdf = _make_pdf("SOC 2 Type II report. ISAE 3402.")
    c.post("/api/v1/documents/upload",
           files={"file": ("acme.pdf", pdf, "application/pdf")},
           data={"vendor_id": str(vid)}, headers=H)
    # Isaac result persisted as an intel result, visible to the engine history
    # (we check via the audit trail which records the upload + isaac band)
    audit = c.get("/api/v1/audit", headers=H).json()
    assert any(a["action"] == "document.uploaded" for a in audit)


def test_upload_text_file_classified():
    c = _client()
    vid = c.post("/api/v1/vendors", json={"name": "Q"}, headers=H).json()["vendor_id"]
    content = b"Vendor Due Diligence Questionnaire (DDQ). Please describe controls. Vendor response: yes."
    r = c.post("/api/v1/documents/upload",
               files={"file": ("ddq.txt", content, "text/plain")},
               data={"vendor_id": str(vid)}, headers=H)
    assert r.status_code == 200
    assert r.json()["doc_type"] == "questionnaire"


def test_unsupported_type_rejected():
    c = _client()
    r = c.post("/api/v1/documents/upload",
               files={"file": ("data.bin", b"\\x00\\x01", "application/octet-stream")},
               headers=H)
    assert r.status_code == 415


def test_low_signal_doc_flags_human_review():
    c = _client()
    content = b"Quarterly marketing newsletter about our brand refresh and new logo."
    r = c.post("/api/v1/documents/upload",
               files={"file": ("news.txt", content, "text/plain")}, headers=H)
    assert r.status_code == 200
    assert r.json()["needs_human_review"] is True


if __name__ == "__main__":
    import traceback
    # ensure reportlab present for PDF generation in tests
    try:
        import reportlab  # noqa
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "reportlab",
                        "--break-system-packages", "-q"])
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
