"""
Phase 0 tests. These prove the three properties Phase 0 must guarantee:
  1. Resolution is deterministic and merge rules are correct.
  2. Snapshots are immutable and content-addressed.
  3. The audit chain detects tampering.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.models.policy import (
    CanonicalControl, ControlOverride, CustomControl, TenantOverlay,
    DataClassification, RiskWeight,
)
from app.core.resolution import (
    resolve_policy, controls_needing_review,
)
from app.core.snapshot import PolicySnapshot, content_hash
from app.core.audit import AuditTrail

ORG = "org-acme"

CTL_14 = CanonicalControl(
    control_id="CTL-INFOSEC-014",
    domain="Information Security",
    statement="Supplier must encrypt data at rest",
    best_practice_refs=("ISO 27001 A.8.24", "SOC2 CC6.1"),
    default_threshold="AES-256",
    default_applicability=DataClassification.CONFIDENTIAL,
    risk_weight=RiskWeight.HIGH,
    version=3,
)
CTL_20 = CanonicalControl(
    control_id="CTL-RESIL-020",
    domain="Operational Resilience",
    statement="Supplier must maintain a tested BCP",
    best_practice_refs=("ISO 22301",),
    default_threshold="Annual test",
    default_applicability=DataClassification.INTERNAL,
    risk_weight=RiskWeight.MEDIUM,
    version=1,
)
BASELINE = {CTL_14.control_id: CTL_14, CTL_20.control_id: CTL_20}


def test_bare_baseline_inherits_everything():
    overlay = TenantOverlay(org_id=ORG)
    eff = resolve_policy(BASELINE, overlay)
    c = eff["CTL-INFOSEC-014"]
    assert c.origin == "baseline"
    assert c.threshold == "AES-256"
    assert c.applicability == DataClassification.CONFIDENTIAL
    assert c.risk_weight == RiskWeight.HIGH
    assert c.needs_review is False


def test_override_wins_and_inherits_selectively():
    overlay = TenantOverlay(org_id=ORG, overrides={
        "CTL-INFOSEC-014": ControlOverride(
            control_id="CTL-INFOSEC-014",
            base_version=3,
            threshold_override="AES-256 + customer-managed keys",
            applicability_override=DataClassification.INTERNAL,
            risk_weight_override=RiskWeight.CRITICAL,
            terminology={"data classification": "data sensitivity tier"},
        )
    })
    eff = resolve_policy(BASELINE, overlay)
    c = eff["CTL-INFOSEC-014"]
    assert c.origin == "baseline+override"
    assert c.threshold == "AES-256 + customer-managed keys"
    assert c.applicability == DataClassification.INTERNAL
    assert c.risk_weight == RiskWeight.CRITICAL
    assert c.terminology["data classification"] == "data sensitivity tier"
    # untouched control still inherits
    assert eff["CTL-RESIL-020"].origin == "baseline"


def test_stale_overlay_flags_review_not_drop():
    # overlay authored against v2, baseline is now v3 -> needs_review
    overlay = TenantOverlay(org_id=ORG, overrides={
        "CTL-INFOSEC-014": ControlOverride(
            control_id="CTL-INFOSEC-014", base_version=2,
            threshold_override="AES-128",
        )
    })
    eff = resolve_policy(BASELINE, overlay)
    assert eff["CTL-INFOSEC-014"].needs_review is True
    assert controls_needing_review(eff) == ["CTL-INFOSEC-014"]


def test_custom_control_is_first_class_and_tagged():
    overlay = TenantOverlay(org_id=ORG, custom_controls={
        "CTL-CUSTOM-201": CustomControl(
            control_id="CTL-CUSTOM-201",
            domain="Compliance",
            statement="Supplier must hold local payments licence",
            threshold="Valid licence on file",
            applicability=DataClassification.PUBLIC,
            risk_weight=RiskWeight.CRITICAL,
        )
    })
    eff = resolve_policy(BASELINE, overlay)
    assert eff["CTL-CUSTOM-201"].origin == "custom"
    assert eff["CTL-CUSTOM-201"].baseline_version is None


def test_resolution_is_deterministic():
    overlay = TenantOverlay(org_id=ORG, overrides={
        "CTL-INFOSEC-014": ControlOverride(
            control_id="CTL-INFOSEC-014", base_version=3,
            threshold_override="AES-256 + CMK",
        )
    })
    h1 = content_hash(resolve_policy(BASELINE, overlay))
    h2 = content_hash(resolve_policy(BASELINE, overlay))
    assert h1 == h2


def test_snapshot_is_immutable_and_addressed():
    overlay = TenantOverlay(org_id=ORG)
    eff = resolve_policy(BASELINE, overlay)
    snap = PolicySnapshot.create("snap-1", ORG, eff)
    assert snap.content_hash == content_hash(eff)
    # different policy -> different hash
    overlay2 = TenantOverlay(org_id=ORG, overrides={
        "CTL-RESIL-020": ControlOverride(
            control_id="CTL-RESIL-020", base_version=1,
            risk_weight_override=RiskWeight.CRITICAL,
        )
    })
    snap2 = PolicySnapshot.create("snap-2", ORG, resolve_policy(BASELINE, overlay2))
    assert snap2.content_hash != snap.content_hash


def test_audit_chain_appends_and_verifies():
    trail = AuditTrail()
    trail.append(ORG, "policy.snapshot.created", "system",
                 {"snapshot_id": "snap-1", "content_hash": "abc"})
    trail.append(ORG, "ai.verdict.emitted", "agent-infosec",
                 {"control_id": "CTL-INFOSEC-014", "verdict": "PARTIAL",
                  "confidence": 0.62})
    trail.append(ORG, "human.validation", "user-analyst",
                 {"control_id": "CTL-INFOSEC-014", "decision": "override",
                  "reason_code": "EVIDENCE_INSUFFICIENT"})
    assert len(trail.entries()) == 3
    assert trail.verify() is True


def test_audit_chain_detects_tampering():
    trail = AuditTrail()
    trail.append(ORG, "ai.verdict.emitted", "agent", {"confidence": 0.62})
    trail.append(ORG, "human.validation", "user", {"decision": "confirm"})
    # tamper: mutate a past payload in place
    trail.entries()  # snapshot
    trail._entries[0].payload["confidence"] = 0.99
    assert trail.verify() is False


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
