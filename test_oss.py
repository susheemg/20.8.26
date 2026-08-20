"""OSS register tests: SBOM parsing, licence classification, scoring,
engagement tagging, blast-radius and concentration."""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.bro_app import make_engine, make_session_factory
from app.features.intelligence import oss as OSS


def _s():
    from app.features.domain import registry_models as RM
    eng = make_engine("sqlite:///:memory:")
    RM.Base.metadata.create_all(eng)
    return make_session_factory(eng)(), RM


_CDX = {"bomFormat": "CycloneDX", "specVersion": "1.5",
        "metadata": {"timestamp": "2026-06-01T00:00:00Z", "tools": [{"name": "syft"}]},
        "components": [
            {"name": "log4j-core", "version": "2.14.1", "purl": "pkg:maven/log4j-core@2.14.1",
             "licenses": [{"license": {"id": "Apache-2.0"}}], "supplier": {"name": "Apache"}},
            {"name": "ghostscript", "version": "10.02.1", "purl": "pkg:generic/ghostscript@10.02.1",
             "licenses": [{"license": {"id": "AGPL-3.0"}}]}]}
_SPDX = {"spdxVersion": "SPDX-2.3",
         "creationInfo": {"created": "2026-06-01T00:00:00Z", "creators": ["Tool: trivy"]},
         "packages": [{"name": "openssl", "versionInfo": "3.0.0", "licenseConcluded": "Apache-2.0",
                       "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:generic/openssl@3.0.0"}]}]}


def test_parse_cyclonedx():
    p = OSS.parse_sbom(_CDX)
    assert p["fmt"] == "cyclonedx" and len(p["components"]) == 2
    assert p["components"][0]["purl"].startswith("pkg:maven/log4j-core")


def test_parse_spdx():
    p = OSS.parse_sbom(_SPDX)
    assert p["fmt"] == "spdx" and p["components"][0]["version"] == "3.0.0"


def test_parse_rejects_unknown():
    try:
        OSS.parse_sbom({"foo": "bar"})
        assert False, "should have raised"
    except ValueError:
        pass


def test_classify_licence():
    assert OSS.classify_licence("AGPL-3.0") == "prohibited"
    assert OSS.classify_licence("GPL-3.0") == "restricted"
    assert OSS.classify_licence("MIT") == "allowed"
    assert OSS.classify_licence("NOASSERTION") == "review"


def test_component_risk_kev_is_critical():
    score, band = OSS.component_risk("allowed", "healthy", [{"cvss": 10.0, "kev": True}])
    assert band == "CRITICAL" and score >= 85


def test_vex_suppresses():
    score, band = OSS.component_risk("allowed", "healthy", [{"cvss": 10.0, "kev": True, "vex_status": "not_affected"}])
    assert band == "LOW"


def test_ntia_assess_range():
    score, label = OSS.ntia_assess(OSS.parse_sbom(_CDX))
    assert 0 <= score <= 100 and label in ("complete", "partial", "minimal")


def test_ingest_tags_engagement_and_blast_radius():
    s, RM = _s()
    s.add(RM.VendorRecord(vendor_id="VEN-1", legal_name="Acme"))
    s.add(RM.EngagementRecord(engagement_id="ENG-1", vendor_id="VEN-1", title="App A"))
    s.add(RM.EngagementRecord(engagement_id="ENG-2", vendor_id="VEN-1", title="App B"))
    s.commit()
    OSS.ingest_sbom(s, "ENG-1", "App A", "1.0", _CDX)
    OSS.ingest_sbom(s, "ENG-2", "App B", "1.0", _CDX)
    s.commit()
    b = OSS.blast_radius(s, "log4j-core")
    assert b["engagement_count"] == 2 and b["vendor_count"] == 1


def test_ingest_attaches_kev_and_scores_critical():
    s, RM = _s()
    s.add(RM.VendorRecord(vendor_id="VEN-1", legal_name="Acme"))
    s.add(RM.EngagementRecord(engagement_id="ENG-1", vendor_id="VEN-1", title="App A"))
    s.commit()
    OSS.ingest_sbom(s, "ENG-1", "App A", "1.0", _CDX)
    s.commit()
    comp = next(c for c in OSS.components(s, q="log4j-core"))
    assert comp["band"] == "CRITICAL"
    det = OSS.component_detail(s, comp["id"])
    assert any(v["cve"] == "CVE-2021-44228" and v["kev"] for v in det["vulnerabilities"])


def test_supersede_keeps_one_active_sbom():
    s, RM = _s()
    s.add(RM.VendorRecord(vendor_id="VEN-1", legal_name="Acme"))
    s.add(RM.EngagementRecord(engagement_id="ENG-1", vendor_id="VEN-1", title="App A"))
    s.commit()
    OSS.ingest_sbom(s, "ENG-1", "App A", "1.0", _CDX)
    OSS.ingest_sbom(s, "ENG-1", "App A", "1.0", _SPDX)  # supersedes prior
    s.commit()
    active = [r for r in OSS.coverage(s) if r["engagement_id"] == "ENG-1" and r["has_sbom"]]
    assert len(active) == 1


def test_prohibited_licence_flagged():
    s, RM = _s()
    s.add(RM.VendorRecord(vendor_id="VEN-1", legal_name="Acme"))
    s.add(RM.EngagementRecord(engagement_id="ENG-1", vendor_id="VEN-1", title="App A"))
    s.commit()
    OSS.ingest_sbom(s, "ENG-1", "App A", "1.0", _CDX)
    s.commit()
    lic = OSS.licences(s)
    assert lic["by_category"]["prohibited"] >= 1
    assert any(f["name"] == "ghostscript" for f in lic["flagged"])


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
