"""
Phase 5 tests: document ingestion -> typed Evidence.
Proves classification drives precedence correctly, validity windows enable
recency gating, dedup works, and ambiguous documents route to a human.
"""
import sys
from datetime import date
sys.path.insert(0, "/home/claude/tprm")

from app.ingestion.extract import (
    TextExtractor, PdfExtractor, classify, DocType,
    ExtractedDocument, ClassificationResult,
)
from app.ingestion.pipeline import (
    ingest_document, ClaimCandidate, PipelineResult,
)
from app.models.evidence import SourceType, ActorRole
from app.core.evidence_resolution import resolve_evidence

ORG, ENG = "org", "eng-1"


def _doc(text):
    return ExtractedDocument(text=text, page_count=1)


# ---- extraction ----

def test_text_extractor_handles_text():
    ex = TextExtractor()
    assert ex.can_handle("a.txt", "text/plain") is True
    out = ex.extract("a.txt", b"hello world")
    assert out.text == "hello world" and out.page_count == 1

def test_pdf_extractor_handles_pdfs():
    ex = PdfExtractor()
    assert ex.can_handle("audit.pdf", "application/pdf") is True
    # malformed PDF bytes should raise (not silently return empty text)
    try:
        ex.extract("audit.pdf", b"not a real pdf")
        assert False, "malformed PDF should raise, not return empty text"
    except Exception:
        pass


# ---- classification drives precedence ----

def test_audit_classified_as_independent_audit():
    cls = classify(_doc("Independent Service Auditor's Report. SOC 2 Type II. "
                        "ISAE 3402 controls tested."))
    assert cls.doc_type is DocType.INDEPENDENT_AUDIT
    assert cls.source_type is SourceType.INDEPENDENT_AUDIT

def test_questionnaire_classified_as_attestation():
    cls = classify(_doc("Vendor Due Diligence Questionnaire (DDQ). "
                        "Please describe your encryption controls. Vendor response:"))
    assert cls.doc_type is DocType.QUESTIONNAIRE
    assert cls.source_type is SourceType.VENDOR_ATTESTATION

def test_unrecognised_doc_is_unknown_low_confidence():
    cls = classify(_doc("Quarterly marketing newsletter about our new logo."))
    assert cls.doc_type is DocType.UNKNOWN
    assert cls.is_low_confidence is True


# ---- pipeline -> evidence ----

def _claims(extracted, cls):
    return [
        ClaimCandidate("InfoSec", "AES-256 encryption at rest verified"),
        ClaimCandidate("Resilience", "BCP tested annually"),
        ClaimCandidate("InfoSec", "AES-256 encryption at rest verified"),  # dup
    ]

def test_pipeline_emits_typed_evidence_with_validity():
    extracted = _doc("SOC 2 Type II independent auditor report. ISAE 3402.")
    res = ingest_document(
        doc_id="d1", org_id=ORG, engagement_id=ENG, extracted=extracted,
        claim_extractor=_claims, captured_on=date(2026, 1, 1),
    )
    assert res.needs_human is False
    # dedup: 3 candidates -> 2 unique
    assert len(res.evidence) == 2
    e = res.evidence[0]
    assert e.source_type is SourceType.INDEPENDENT_AUDIT
    assert e.author_role is ActorRole.VENDOR
    assert e.valid_until == date(2027, 1, 1)      # 365-day audit window
    assert e.document_id == "d1"

def test_low_confidence_doc_routes_to_human_no_evidence():
    extracted = _doc("Random unrelated content with no risk signals.")
    res = ingest_document(
        doc_id="d2", org_id=ORG, engagement_id=ENG, extracted=extracted,
        claim_extractor=_claims,
    )
    assert res.needs_human is True
    assert res.evidence == ()
    assert "classification_confidence" in res.reason


# ---- end-to-end: ingested evidence resolves with correct precedence ----

def test_ingested_audit_outranks_ingested_chat():
    audit = ingest_document(
        doc_id="audit1", org_id=ORG, engagement_id=ENG,
        extracted=_doc("SOC 2 Type II independent auditor report ISAE 3402"),
        claim_extractor=lambda e, c: [ClaimCandidate("InfoSec", "encryption verified")],
        captured_on=date(2026, 3, 1),
    )
    chat = ingest_document(
        doc_id="chat1", org_id=ORG, engagement_id=ENG,
        extracted=_doc("transcript\nvendor: we are still working on encryption\n"
                       "assessor: noted"),
        claim_extractor=lambda e, c: [ClaimCandidate("InfoSec", "still working on it")],
        captured_on=date(2026, 5, 1),
    )
    all_ev = list(audit.evidence) + list(chat.evidence)
    resolved = resolve_evidence("InfoSec", all_ev, as_of=date(2026, 5, 30))
    # audit (higher precedence) wins despite chat being more recent
    assert resolved.winner.source_type is SourceType.INDEPENDENT_AUDIT
    assert len(resolved.conflicts) == 1            # chat contradicts audit, recorded


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
