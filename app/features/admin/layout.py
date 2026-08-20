"""Navigation & Layout config — structural (not text) overrides for the app shell.

Admins can show/hide and reorder navigation items and groups from the "Admin Change"
section. Config is stored in `layout_setting` and applied client-side to the nav on
load. This is a bounded layout capability (nav visibility + ordering), distinct from
the free-form page-builder that remains out of scope. Reading the config is public
(so the shell renders correctly for everyone); editing requires admin.content.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from app.features.domain.models_db import Base

def _now(): return datetime.now(timezone.utc)

# admin-gated items are managed by role, not layout (kept out of the layout catalogue)
GATED_ITEMS = ['adminchange', 'config', 'methodology']

# baked default nav structure: ordered groups -> ordered items
NAV_CATALOG = [{'slug': 'top',
  'label': '',
  'items': [{'datav': 'home', 'label': 'Home'},
            {'datav': 'methodology', 'label': 'Methodology'},
            {'datav': 'dashboards', 'label': 'Dashboards'},
            {'datav': 'learnings', 'label': 'Learnings'},
            {'datav': 'dashboard', 'label': 'Snapshot'}]},
 {'slug': 'assess',
  'label': 'Assess',
  'items': [{'datav': 'assess', 'label': 'BRO Chat'},
            {'datav': 'proassess', 'label': 'ProAssess'},
            {'datav': 'assessments', 'label': 'Assessments'},
            {'datav': 'engagements', 'label': 'Engagements'},
            {'datav': 'vendors', 'label': 'Vendor Register'},
            {'datav': 'artefacts', 'label': 'Certifications'},
            {'datav': 'fdd', 'label': 'Financial DD'},
            {'datav': 'reputation', 'label': 'Reputation'},
            {'datav': 'oss', 'label': 'Open Source (SBOM)'},
            {'datav': 'review', 'label': 'Review Queue'}]},
 {'slug': 'monitor_manage',
  'label': 'Monitor & Manage',
  'items': [{'datav': 'vendor360', 'label': 'Vendor 360'},
            {'datav': 'documents', 'label': 'Documents'},
            {'datav': 'performance', 'label': 'Performance'},
            {'datav': 'slamgmt', 'label': 'SLA Management'},
            {'datav': 'perfissues', 'label': 'Performance Issues'},
            {'datav': 'findings', 'label': 'Findings'},
            {'datav': 'issues', 'label': 'Issues Log'},
            {'datav': 'incidents', 'label': 'Supplier Incidents'},
            {'datav': 'remediation', 'label': 'Remediation Plans'},
            {'datav': 'fourthparties', 'label': '4th Party Register'},
            {'datav': 'contracts', 'label': 'Contracts'},
            {'datav': 'exit', 'label': 'Exit Planning'},
            {'datav': 'notifications', 'label': 'Notifications'},
            {'datav': 'schedules', 'label': 'Schedules'},
            {'datav': 'connections', 'label': 'Connections'}]},
 {'slug': 'analyse',
  'label': 'Analyse',
  'items': [{'datav': 'pestle', 'label': 'PESTLE Intelligence'},
            {'datav': 'intel', 'label': 'Intelligence'},
            {'datav': 'advanced', 'label': 'Overview'},
            {'datav': 'integrity', 'label': 'Data Integrity'},
            {'datav': 'entitygraph', 'label': 'Entity Graph'},
            {'datav': 'exposure', 'label': 'BU Exposure'},
            {'datav': 'geopolitical', 'label': 'Geopolitical'},
            {'datav': 'criticality', 'label': 'Critical Vendor Modelling'},
            {'datav': 'scenario', 'label': 'Scenario Simulator'},
            {'datav': 'stressradar', 'label': 'Stress Radar'}]},
 {'slug': 'understand',
  'label': 'Understand',
  'items': [{'datav': 'copilot', 'label': 'Ask Anything'},
            {'datav': 'management', 'label': 'Management'},
            {'datav': 'globalreg', 'label': 'Global Regulations'},
            {'datav': 'boardpack', 'label': 'Board / Regulator Pack'},
            {'datav': 'reports', 'label': 'Reports'},
            {'datav': 'aireports', 'label': 'AI Reports'},
            {'datav': 'evidence', 'label': 'Evidence on Demand'},
            {'datav': 'lifecycle', 'label': 'Lifecycle'},
            {'datav': 'governance', 'label': 'Governance'},
            {'datav': 'audit', 'label': 'Audit Trail'}]},
 {'slug': 'documentation',
  'label': 'Documentation',
  'items': [{'datav': 'sop', 'label': 'SOP'},
            {'datav': 'techdetails', 'label': 'Technical Details'},
            {'datav': 'versions', 'label': 'Version Control'}]},
 {'slug': 'miscellaneous',
  'label': 'Miscellaneous',
  'items': [{'datav': 'guideddemo', 'label': 'Guided Demo'},
            {'datav': 'admin', 'label': 'Admin'},
            {'datav': 'adminchange', 'label': 'Admin Change'},
            {'datav': 'aicontrol', 'label': 'AI Control'},
            {'datav': 'config', 'label': 'Configuration'},
            {'datav': 'settings', 'label': 'Settings'},
            {'datav': 'language', 'label': 'Translation workbench'},
            {'datav': 'feedback', 'label': 'Feedback'}]}]

_ITEM_GROUP = {}
_DEFAULT_ORDER = {}
for _gi, _g in enumerate(NAV_CATALOG):
    for _ii, _it in enumerate(_g["items"]):
        _ITEM_GROUP[_it["datav"]] = _g["slug"]
        _DEFAULT_ORDER[_it["datav"]] = _gi * 100 + _ii


class LayoutSetting(Base):
    __tablename__ = "layout_setting"
    scope: Mapped[str] = mapped_column(String, primary_key=True)   # 'item' | 'group'
    ref: Mapped[str] = mapped_column(String, primary_key=True)     # data-v key or group slug
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    updated_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _rows(s: Session):
    return {(r.scope, r.ref): r for r in s.scalars(select(LayoutSetting)).all()}

def layout_config(s: Session) -> dict:
    """Public map the client applies: {items:{datav:{hidden,order}}, groups:{slug:{hidden,order}}}."""
    rows = _rows(s)
    items, groups = {}, {}
    for (scope, ref), r in rows.items():
        entry = {}
        if r.hidden: entry["hidden"] = True
        if r.sort_order is not None: entry["order"] = r.sort_order
        if not entry: continue
        (items if scope == "item" else groups)[ref] = entry
    return {"items": items, "groups": groups}

def catalog(s: Session) -> dict:
    """Admin view: full nav structure annotated with current hidden/order."""
    rows = _rows(s)
    out_groups = []
    for gi, g in enumerate(NAV_CATALOG):
        grow = rows.get(("group", g["slug"]))
        items = []
        for ii, it in enumerate(g["items"]):
            if it["datav"] in GATED_ITEMS:
                continue
            irow = rows.get(("item", it["datav"]))
            items.append({
                "datav": it["datav"], "label": it["label"],
                "hidden": bool(irow and irow.hidden),
                "order": irow.sort_order if (irow and irow.sort_order is not None) else _DEFAULT_ORDER[it["datav"]],
            })
        items.sort(key=lambda x: x["order"])
        out_groups.append({
            "slug": g["slug"], "label": g["label"] or "General",
            "hidden": bool(grow and grow.hidden),
            "order": grow.sort_order if (grow and grow.sort_order is not None) else gi * 100,
            "items": items,
        })
    out_groups.sort(key=lambda x: x["order"])
    hidden_items = sum(1 for it in rows.values() if False)  # placeholder
    return {"groups": out_groups,
            "hidden_items": sum(1 for (sc, rf), r in rows.items() if sc == "item" and r.hidden),
            "hidden_groups": sum(1 for (sc, rf), r in rows.items() if sc == "group" and r.hidden)}

def _upsert(s: Session, scope: str, ref: str, hidden=None, sort_order=None, actor="admin"):
    row = s.get(LayoutSetting, (scope, ref)) or LayoutSetting(scope=scope, ref=ref)
    if hidden is not None: row.hidden = bool(hidden)
    if sort_order is not None: row.sort_order = int(sort_order)
    row.updated_by = actor; row.updated_at = _now()
    s.add(row); s.flush()
    # clean up no-op rows (visible + default order) to keep config minimal
    if not row.hidden and row.sort_order is None:
        s.delete(row); s.flush()
        return {"scope": scope, "ref": ref, "reset": True}
    return {"scope": scope, "ref": ref, "hidden": row.hidden, "order": row.sort_order}

def set_item(s: Session, datav: str, hidden=None, sort_order=None, actor="admin"):
    if datav not in _ITEM_GROUP:
        raise KeyError(datav)
    if datav in GATED_ITEMS:
        raise ValueError("gated item is managed by role, not layout")
    return _upsert(s, "item", datav, hidden, sort_order, actor)

def set_group(s: Session, slug: str, hidden=None, sort_order=None, actor="admin"):
    if slug not in {g["slug"] for g in NAV_CATALOG}:
        raise KeyError(slug)
    return _upsert(s, "group", slug, hidden, sort_order, actor)

def reorder_group(s: Session, slug: str, ordered_datavs: list, actor="admin"):
    """Persist an explicit order for the items within a group."""
    base = next((gi for gi, g in enumerate(NAV_CATALOG) if g["slug"] == slug), 0) * 100
    for i, dv in enumerate(ordered_datavs):
        if dv in _ITEM_GROUP and dv not in GATED_ITEMS:
            _upsert(s, "item", dv, sort_order=base + i, actor=actor)
    return {"slug": slug, "count": len(ordered_datavs)}

def reset_all(s: Session):
    n = 0
    for r in s.scalars(select(LayoutSetting)).all():
        s.delete(r); n += 1
    s.flush(); return {"reset": n}
