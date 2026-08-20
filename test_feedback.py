"""AI-answer feedback: record, list, summarise, mark-used, and distil into guidance."""
import sys
sys.path.insert(0, "/home/claude/tprm")

from app.bro_app import make_engine, make_session_factory
from app.features.assessment import feedback as FB


def _s():
    from app.features.domain import registry_models as RM
    eng = make_engine("sqlite:///:memory:")
    RM.Base.metadata.create_all(eng)
    return make_session_factory(eng)()


def test_record_and_summary():
    s = _s()
    FB.record(s, "alice", "management", "Q1", "A1", rating="up", comment="concise, good")
    FB.record(s, "bob", "management", "Q2", "A2", rating="down", comment="name the engagement IDs")
    s.commit()
    sm = FB.summary(s)
    assert sm["total"] == 2 and sm["up"] == 1 and sm["down"] == 1 and sm["with_comment"] == 2


def test_list_recent_newest_first_and_filter():
    s = _s()
    FB.record(s, "a", "management", "Q1", "A1", rating="up")
    FB.record(s, "b", "board", "Q2", "A2", rating="down")
    s.commit()
    items = FB.list_recent(s)
    assert items[0]["surface"] == "board"  # newest first
    assert len(FB.list_recent(s, rating="down")) == 1


def test_set_used():
    s = _s()
    fid = FB.record(s, "a", "management", "Q", "A", rating="down", comment="be specific")
    s.commit()
    FB.set_used(s, fid, True, "reviewer")
    s.commit()
    assert FB.summary(s)["used"] == 1
    FB.set_used(s, fid, False, "reviewer")
    s.commit()
    assert FB.summary(s)["used"] == 0


def test_guidance_distils_downvotes():
    s = _s()
    FB.record(s, "a", "management", "Q", "A", rating="down", comment="quantify exposure in numbers")
    FB.record(s, "b", "management", "Q", "A", rating="up", comment="liked the prioritisation")
    s.commit()
    g = FB.guidance(s, surface="management")
    assert "RECURRING USER FEEDBACK" in g
    assert "quantify exposure" in g


def test_guidance_empty_when_no_comments():
    s = _s()
    FB.record(s, "a", "management", "Q", "A", rating="up")  # no comment
    s.commit()
    assert FB.guidance(s, surface="management") == ""


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
