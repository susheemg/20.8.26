"""Platform notification engine (Build 2). Every notifiable event catalogued;
ALL OFF by default. emit() writes an in-app row only if enabled (or force=True
for notable incidents that must always reach management)."""
from __future__ import annotations
import time
from typing import Optional
from sqlalchemy import text as _sql

CATALOGUE = [
    {"id": "assessment.completed",    "group": "Assessments", "label": "Assessment completed", "desc": "A ProAssess/BroAssess run reaches a verdict."},
    {"id": "assessment.residual_high","group": "Assessments", "label": "Residual risk HIGH",   "desc": "Any assessment lands a HIGH residual band."},
    {"id": "decision.pending",        "group": "Assessments", "label": "Decision awaiting approver", "desc": "An engagement decision needs sign-off."},
    {"id": "ddq.returned",            "group": "Assessments", "label": "DDQ returned by vendor", "desc": "A vendor submits DDQ responses."},
    {"id": "monitoring.alert",        "group": "Monitoring",  "label": "Monitoring alert raised", "desc": "A continuous-monitoring sweep raises ALERT/CRITICAL."},
    {"id": "monitoring.sweep_failed", "group": "Monitoring",  "label": "Scheduled sweep failed", "desc": "A scheduled monitoring run errors."},
    {"id": "sanctions.hit",           "group": "Monitoring",  "label": "Sanctions/AML screening hit", "desc": "Screening returns a potential match."},
    {"id": "watchlist.added",         "group": "Monitoring",  "label": "Vendor added to watchlist", "desc": "A vendor enters the DORA/CTP watchlist."},
    {"id": "fdd.distress",            "group": "Monitoring",  "label": "Financial distress signal", "desc": "Vera/FDD flags deteriorating financial health."},
    {"id": "reputation.adverse",      "group": "Monitoring",  "label": "Adverse media signal", "desc": "Reputation scan finds adverse coverage."},
    {"id": "contract.expiry",         "group": "Lifecycle",   "label": "Contract expiry approaching", "desc": "A contract enters its renewal/expiry window."},
    {"id": "cert.expiry",             "group": "Lifecycle",   "label": "Certification expiring", "desc": "ISO/SOC certificate nears expiry."},
    {"id": "finding.overdue",         "group": "Lifecycle",   "label": "Finding past due", "desc": "A remediation finding passes its due date."},
    {"id": "escrow.event",            "group": "Lifecycle",   "label": "Escrow release event", "desc": "A software-escrow release condition triggers."},
    {"id": "exit.trigger",            "group": "Lifecycle",   "label": "Exit trigger fired", "desc": "A live exit trigger opens on a vendor."},
    {"id": "vendor.created",          "group": "Lifecycle",   "label": "Vendor created", "desc": "A new vendor enters the register (incl. CSV import)."},
    {"id": "incident.logged",         "group": "Incidents",   "label": "Incident logged", "desc": "A new third-party incident is recorded."},
    {"id": "incident.notable",        "group": "Incidents",   "label": "NOTABLE EVENT flagged", "desc": "An incident is flagged notable — always reaches management (bypasses the off switch)."},
    {"id": "incident.sla_breach",     "group": "Incidents",   "label": "Incident SLA breached", "desc": "Response clock exceeds the severity SLA."},
    {"id": "ai.budget_exceeded",      "group": "Platform",    "label": "AI daily budget reached", "desc": "The AI call cap blocks further calls today."},
    {"id": "security.lockout",        "group": "Platform",    "label": "Account locked out", "desc": "Repeated failed logins lock an account."},
    {"id": "import.completed",        "group": "Platform",    "label": "Bulk import completed", "desc": "A CSV vendor import commits."},
    {"id": "webhook.failure",         "group": "Platform",    "label": "Webhook delivery failure", "desc": "An outbound webhook fails."},
    {"id": "schedule.changed",        "group": "Platform",    "label": "Schedule changed", "desc": "An admin alters a scheduled sweep."},
]
AUDIENCES = ["management", "risk_team", "all_users"]

def ensure_table(s) -> None:
    s.execute(_sql("CREATE TABLE IF NOT EXISTS notif_log (id INTEGER PRIMARY KEY, ts TEXT, "
        "type TEXT, title TEXT, body TEXT, audience TEXT, link TEXT, is_read INTEGER DEFAULT 0, "
        "forced INTEGER DEFAULT 0)")); s.commit()

def get_settings(s) -> dict:
    from app.features.domain import config_store as CFG
    saved = CFG.get_json(s, "notification_settings", {}) or {}
    out = {}
    for c in CATALOGUE:
        e = saved.get(c["id"], {})
        out[c["id"]] = {"enabled": bool(e.get("enabled", False)), "audience": e.get("audience", "management")}
    return out

def set_settings(s, updates: dict) -> dict:
    from app.features.domain import config_store as CFG
    cur = get_settings(s); ids = {c["id"] for c in CATALOGUE}
    for k, v in (updates or {}).items():
        if k in ids and isinstance(v, dict):
            cur[k] = {"enabled": bool(v.get("enabled", cur[k]["enabled"])),
                      "audience": v.get("audience", cur[k]["audience"]) if v.get("audience") in AUDIENCES else cur[k]["audience"]}
    CFG.upsert_json(s, "notification_settings", cur, updated_by="admin", category="notifications"); s.commit()
    return cur

def emit(s, ntype: str, title: str, body: str = "", link: str = "", audience: Optional[str] = None, force: bool = False) -> bool:
    try:
        cfg = get_settings(s).get(ntype, {"enabled": False, "audience": "management"})
        if not (cfg["enabled"] or force):
            return False
        ensure_table(s)
        s.execute(_sql("INSERT INTO notif_log (ts, type, title, body, audience, link, is_read, forced) "
            "VALUES (:ts,:t,:ti,:b,:a,:l,0,:f)"),
            {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "t": ntype, "ti": title[:200],
             "b": (body or "")[:600], "a": audience or cfg["audience"], "l": link or "", "f": 1 if force else 0})
        s.commit(); return True
    except Exception:
        return False

def inbox(s, n: int = 50) -> list:
    ensure_table(s)
    rows = s.execute(_sql("SELECT id, ts, type, title, body, audience, link, is_read, forced "
        "FROM notif_log ORDER BY id DESC LIMIT :n"), {"n": n}).fetchall()
    keys = ["id", "ts", "type", "title", "body", "audience", "link", "is_read", "forced"]
    return [dict(zip(keys, r)) for r in rows]

def mark_read(s, nid: Optional[int] = None) -> None:
    ensure_table(s)
    s.execute(_sql("UPDATE notif_log SET is_read=1 WHERE id=:i" if nid else "UPDATE notif_log SET is_read=1"),
              {"i": nid} if nid else {})
    s.commit()

def unread_count(s) -> int:
    ensure_table(s)
    return int(s.execute(_sql("SELECT COUNT(*) FROM notif_log WHERE is_read=0")).scalar() or 0)


# ============ Notification templates (admin-authored, multi-group) ============
import json as _json

def ensure_templates_table(s) -> None:
    s.execute(_sql("CREATE TABLE IF NOT EXISTS notif_template (id INTEGER PRIMARY KEY, "
        "name TEXT, subject TEXT, body TEXT, groups TEXT, enabled INTEGER DEFAULT 1, "
        "updated_by TEXT, updated_at TEXT)")); s.commit()

def _tpl_row(r):
    keys = ["id", "name", "subject", "body", "groups", "enabled", "updated_by", "updated_at"]
    d = dict(zip(keys, r))
    try: d["groups"] = _json.loads(d["groups"] or "[]")
    except Exception: d["groups"] = []
    d["enabled"] = bool(d["enabled"])
    return d

def list_templates(s) -> list:
    ensure_templates_table(s)
    rows = s.execute(_sql("SELECT id,name,subject,body,groups,enabled,updated_by,updated_at "
        "FROM notif_template ORDER BY id")).fetchall()
    return [_tpl_row(r) for r in rows]

def get_template(s, tid: int):
    ensure_templates_table(s)
    r = s.execute(_sql("SELECT id,name,subject,body,groups,enabled,updated_by,updated_at "
        "FROM notif_template WHERE id=:i"), {"i": tid}).fetchone()
    return _tpl_row(r) if r else None

def create_template(s, name: str, subject: str, body: str, groups: list, actor="admin") -> dict:
    ensure_templates_table(s)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cur = s.execute(_sql("INSERT INTO notif_template (name,subject,body,groups,enabled,updated_by,updated_at) "
        "VALUES (:n,:su,:b,:g,1,:by,:ts)"),
        {"n": name[:120], "su": (subject or "")[:200], "b": body or "",
         "g": _json.dumps(groups or []), "by": actor, "ts": ts})
    s.commit()
    return get_template(s, cur.lastrowid)

def update_template(s, tid: int, fields: dict, actor="admin"):
    ensure_templates_table(s)
    cur = get_template(s, tid)
    if not cur: return None
    name = fields.get("name", cur["name"]); subject = fields.get("subject", cur["subject"])
    body = fields.get("body", cur["body"]); groups = fields.get("groups", cur["groups"])
    enabled = fields.get("enabled", cur["enabled"])
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s.execute(_sql("UPDATE notif_template SET name=:n,subject=:su,body=:b,groups=:g,"
        "enabled=:e,updated_by=:by,updated_at=:ts WHERE id=:i"),
        {"n": (name or "")[:120], "su": (subject or "")[:200], "b": body or "",
         "g": _json.dumps(groups or []), "e": 1 if enabled else 0, "by": actor, "ts": ts, "i": tid})
    s.commit()
    return get_template(s, tid)

def delete_template(s, tid: int) -> bool:
    ensure_templates_table(s)
    s.execute(_sql("DELETE FROM notif_template WHERE id=:i"), {"i": tid}); s.commit()
    return True

def resolve_recipients(s, groups: list) -> list:
    """Users (with an email) whose role.key is in the selected groups."""
    from app.features.domain.models_db import User, Role
    from sqlalchemy import select as _sel
    if not groups: return []
    rows = s.scalars(_sel(User).join(Role, User.role_id == Role.id)
                     .where(Role.key.in_(groups), User.is_active == True)).all()
    return [{"username": u.username, "email": u.email, "role": u.role.key}
            for u in rows if u.email]

def trigger_template(s, tid: int, actor="admin") -> dict:
    """Render a template to its target groups: one in-app notification per group
    plus an outbound email per resolved recipient (SMTP or simulation)."""
    tpl = get_template(s, tid)
    if not tpl: return {"error": "not found"}
    ensure_table(s)
    recips = resolve_recipients(s, tpl["groups"])
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for g in tpl["groups"]:
        s.execute(_sql("INSERT INTO notif_log (ts,type,title,body,audience,link,is_read,forced) "
            "VALUES (:ts,'template.triggered',:ti,:b,:a,'',0,1)"),
            {"ts": ts, "ti": tpl["subject"] or tpl["name"], "b": (tpl["body"] or "")[:600], "a": g})
    s.commit()
    emailed = 0
    try:
        from app.features.admin import email_service as EM
        from app.features.domain.models_feature import EmailOutbox
        for r in recips:
            sent = False
            try:
                sent = EM.send_email(r["email"], tpl["subject"] or tpl["name"], tpl["body"] or "")
            except Exception:
                sent = False
            s.add(EmailOutbox(to_addr=r["email"], subject=(tpl["subject"] or tpl["name"]),
                              body=(tpl["body"] or ""), sent=sent))
            emailed += 1
        s.commit()
    except Exception:
        pass
    return {"triggered": True, "groups": tpl["groups"],
            "recipients": len(recips), "emailed": emailed}

DEFAULT_TEMPLATES = [
    {"name": "Assessment overdue", "subject": "Action required: assessment overdue",
     "groups": ["buyer", "vrm"],
     "body": "Hello,\n\nAn assessment you own has passed its due date. Please review the engagement and complete the outstanding steps in ProAssess.\n\nThank you,\nBrata Risk Office"},
    {"name": "Certificate expiring", "subject": "Certificate expiring within 30 days",
     "groups": ["buyer", "controller"],
     "body": "Hello,\n\nA supplier certification you manage expires within 30 days. Please request the renewed evidence and upload it to the vendor record.\n\nThank you,\nBrata Risk Office"},
    {"name": "Welcome / access granted", "subject": "Your Brata access is ready",
     "groups": ["buyer"],
     "body": "Welcome to Brata.\n\nYour account is active. You can now raise engagements, run ProAssess and use BRO Chat. Reach out to the Risk Office with any questions.\n\nBrata Risk Office"},
]

def seed_templates(s):
    ensure_templates_table(s)
    n = s.execute(_sql("SELECT COUNT(*) FROM notif_template")).scalar() or 0
    if n == 0:
        for t in DEFAULT_TEMPLATES:
            create_template(s, t["name"], t["subject"], t["body"], t["groups"], actor="seed")
