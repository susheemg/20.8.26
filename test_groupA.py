"""
Group A tests: persistence + RBAC. Proves the ported foundation works on a real
(SQLite in-memory) database with the exact role/permission model.
"""
import sys
sys.path.insert(0, "/home/claude/tprm")

from sqlalchemy import select
from app.features.domain.models_db import (
    Base, User, Vendor, Role, Permission, EngagementRow,
    make_engine, make_session_factory, hash_password, verify_password,
)
from app.features.admin.rbac import seed, has_permission, PERMISSIONS, SYSTEM_ROLES


def _session():
    eng = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return make_session_factory(eng)()


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False
    assert h != hash_password("correct horse battery staple")  # salted


def test_seed_creates_all_permissions():
    s = _session(); seed(s)
    perms = s.scalars(select(Permission)).all()
    assert len(perms) == len(PERMISSIONS)            # 49, exact
    cats = {p.category for p in perms}
    assert len(cats) == 13                           # 13 categories (added Supplier Incidents)


def test_seed_creates_system_roles():
    s = _session(); seed(s)
    roles = {r.key for r in s.scalars(select(Role)).all()}
    assert roles == {"admin", "buyer", "vrm", "vendor", "controller", "exec"}
    for r in s.scalars(select(Role)).all():
        assert r.is_system is True


def test_admin_has_all_permissions():
    s = _session(); seed(s)
    admin = s.scalars(select(User).where(User.username == "admin")).first()
    assert has_permission(admin, "engagement.override") is True
    assert has_permission(admin, "admin.roles") is True
    assert len(admin.role.permissions) == len(PERMISSIONS)


def test_vendor_role_is_least_privileged():
    s = _session(); seed(s)
    vrole = s.scalars(select(Role).where(Role.key == "vendor")).first()
    keys = {p.key for p in vrole.permissions}
    assert keys == {"portal.self", "engagement.edit", "finding.view"}
    assert "engagement.override" not in keys


def test_vrm_can_review_buyer_cannot():
    s = _session(); seed(s)
    vrm = s.scalars(select(Role).where(Role.key == "vrm")).first()
    buyer = s.scalars(select(Role).where(Role.key == "buyer")).first()
    vrm_keys = {p.key for p in vrm.permissions}
    buyer_keys = {p.key for p in buyer.permissions}
    assert "engagement.review" in vrm_keys
    assert "engagement.review" not in buyer_keys
    # only VRM designates critical vendors (our Tier 0 human-only governance)
    assert "vendor.critical" in vrm_keys
    assert "vendor.critical" not in buyer_keys


def test_seed_is_idempotent():
    s = _session()
    seed(s); seed(s)                                 # twice
    assert len(s.scalars(select(Permission)).all()) == len(PERMISSIONS)
    assert len(s.scalars(select(Role)).all()) == 6


def test_vendor_tier0_fields_separate_from_tier():
    s = _session(); seed(s)
    v = Vendor(name="Meridian Payments", tier="Tier 1",
               is_critical=True, critical_reason="PCI scope",
               critical_by="user-vrm")
    s.add(v); s.commit()
    got = s.scalars(select(Vendor).where(Vendor.name == "Meridian Payments")).first()
    # computed tier and the human Tier-0 flag coexist, neither overwrites the other
    assert got.tier == "Tier 1"
    assert got.is_critical is True
    assert got.critical_by == "user-vrm"


def test_engagement_persists_with_lifecycle_stage():
    s = _session(); seed(s)
    v = Vendor(name="Aurora"); s.add(v); s.commit()
    e = EngagementRow(vendor_id=v.id, title="Cloud hosting", stage="sourcing")
    s.add(e); s.commit()
    got = s.scalars(select(EngagementRow)).first()
    assert got.stage == "sourcing" and got.status == "draft"


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
