"""User feedback on AI-generated answers: collect, list, summarise, and distil into
prompt guidance so every reviewed AI query improves from what users told us before."""
from __future__ import annotations
from datetime import datetime, date, timedelta


def record(s, username, surface, query, answer, rating="na", comment=None, engine=None):
    from app.features.domain.registry_models import AiFeedback
    fb = AiFeedback(created_at=datetime.utcnow().isoformat(timespec="seconds"),
                    username=username, surface=surface,
                    query=(query or "")[:4000], answer=(answer or "")[:8000],
                    rating=(rating or "na"), comment=(comment or None), engine=engine)
    s.add(fb); s.flush()
    return fb.id


def list_recent(s, limit=200, surface=None, rating=None):
    from app.features.domain.registry_models import AiFeedback
    q = s.query(AiFeedback)
    if surface:
        q = q.filter(AiFeedback.surface == surface)
    if rating:
        q = q.filter(AiFeedback.rating == rating)
    rows = q.order_by(AiFeedback.id.desc()).limit(limit).all()
    return [{"id": r.id, "created_at": r.created_at, "username": r.username, "surface": r.surface,
             "query": r.query, "answer": (r.answer or "")[:600], "rating": r.rating,
             "comment": r.comment, "engine": r.engine, "used": r.used,
             "used_by": r.used_by, "used_at": r.used_at} for r in rows]


def summary(s):
    from app.features.domain.registry_models import AiFeedback
    from sqlalchemy import func
    total = s.query(AiFeedback).count()
    up = s.query(AiFeedback).filter_by(rating="up").count()
    down = s.query(AiFeedback).filter_by(rating="down").count()
    used = s.query(AiFeedback).filter_by(used=True).count()
    with_comment = s.query(AiFeedback).filter(AiFeedback.comment.isnot(None)).count()
    by_surface = {srf: n for (srf, n) in
                  s.query(AiFeedback.surface, func.count(AiFeedback.id)).group_by(AiFeedback.surface).all()}
    return {"total": total, "up": up, "down": down, "used": used,
            "with_comment": with_comment, "by_surface": by_surface}


def set_used(s, fid, used, username):
    from app.features.domain.registry_models import AiFeedback
    fb = s.query(AiFeedback).filter_by(id=fid).first()
    if not fb:
        return None
    fb.used = bool(used)
    fb.used_by = username if used else None
    fb.used_at = datetime.utcnow().isoformat(timespec="seconds") if used else None
    s.flush()
    return {"id": fb.id, "used": fb.used}


def guidance(s, surface=None, days=120, limit=6):
    """Distil recent feedback comments into a short, de-duplicated set of lessons to
    honour in the next answer. Down-votes (with comments) are prioritised, then
    commented up-votes (what users liked). Returns '' when there's nothing useful."""
    from app.features.domain.registry_models import AiFeedback
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    q = s.query(AiFeedback).filter(AiFeedback.comment.isnot(None))
    if surface:
        # honour both surface-specific and global lessons
        q = q.filter((AiFeedback.surface == surface) | (AiFeedback.surface.is_(None)))
    rows = q.order_by(AiFeedback.id.desc()).limit(80).all()
    seen, downs, ups = set(), [], []
    for r in rows:
        if r.created_at and r.created_at[:10] < cutoff:
            continue
        c = (r.comment or "").strip()
        key = c.lower()[:80]
        if not c or key in seen:
            continue
        seen.add(key)
        (downs if r.rating == "down" else ups).append(c[:200])
    picked = (downs + ups)[:limit]
    if not picked:
        return ""
    return ("\n\nRECURRING USER FEEDBACK ON PAST ANSWERS — apply these lessons where relevant "
            "to make THIS answer better (do not force any that don't apply):\n"
            + "\n".join(f"- {p}" for p in picked))
