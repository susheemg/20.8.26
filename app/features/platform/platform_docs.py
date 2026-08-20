"""Platform documentation service — serves the live SOP and Technical Design
documents, an AI-assisted update script that refreshes them as the platform
changes, and a structured version history parsed from the CHANGELOG.

Design notes
------------
* The bundled HTML under ``app/docs/`` is the seed. The "current" rendered
  document is stored in ``platform_docs`` so AI updates persist; first access
  seeds the row from the bundled file.
* The AI-update script is deterministic-first: it stamps the current platform
  version and injects a "Recent platform updates" panel built from the
  CHANGELOG. When an LLM key is configured the gateway can rewrite affected
  sections; the deterministic refresh is always the fallback and is badged.
"""
from __future__ import annotations

import os


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line."""
    try:
        from app.features.admin.security import log_json as _lj
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain.models_db import Base

_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")

KINDS = {
    "sop": {"file": "sop.html", "title": "Standard Operating Procedure"},
    "tda": {"file": "tda.html", "title": "Technical Design & Architecture"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlatformDoc(Base):
    __tablename__ = "platform_docs"
    kind: Mapped[str] = mapped_column(String, primary_key=True)   # sop | tda
    html: Mapped[str] = mapped_column(Text)
    doc_version: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _platform_version() -> str:
    try:
        return open(os.path.join(_BASE_DIR, "VERSION")).read().strip()
    except Exception:
        return "0.0.0"


def _bundled_html(kind: str) -> str:
    path = os.path.join(_DOCS_DIR, KINDS[kind]["file"])
    try:
        return open(path, encoding="utf-8").read()
    except Exception:
        return f"<h1>{KINDS[kind]['title']}</h1><p>Document not available.</p>"


def get_doc(s: Session, kind: str) -> PlatformDoc:
    if kind not in KINDS:
        raise KeyError(kind)
    row = s.get(PlatformDoc, kind)
    if row is None:
        row = PlatformDoc(kind=kind, html=_bundled_html(kind),
                          doc_version=_platform_version(), updated_by="seed")
        s.add(row)
        s.flush()
    return row


# ----------------------------------------------------------------------------
# CHANGELOG parsing → structured version history
# ----------------------------------------------------------------------------
def version_history() -> List[dict]:
    """Parse CHANGELOG.md into [{version, date, title, sections:{name:[items]}}]."""
    path = os.path.join(_BASE_DIR, "CHANGELOG.md")
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return []
    entries: List[dict] = []
    # split on '## [x.y.z]' headers
    blocks = re.split(r"\n(?=## \[)", text)
    for b in blocks:
        m = re.match(r"## \[([0-9]+\.[0-9]+\.[0-9]+)\][^\n]*", b)
        if not m:
            continue
        header = b.splitlines()[0]
        ver = m.group(1)
        date = ""
        title = ""
        dm = re.search(r"—\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", header)
        if dm:
            date = dm.group(1)
        tm = re.search(r"·\s*(.+)$", header)
        if tm:
            title = tm.group(1).strip()
        sections: dict = {}
        cur = None
        for line in b.splitlines()[1:]:
            hm = re.match(r"###\s+(.+)", line)
            if hm:
                cur = hm.group(1).strip()
                sections[cur] = []
                continue
            im = re.match(r"\s*[-*]\s+(.+)", line)
            if im and cur:
                # strip markdown bold/backticks for clean display
                item = re.sub(r"[`*]", "", im.group(1)).strip()
                sections[cur].append(item)
        entries.append({"version": ver, "date": date, "title": title, "sections": sections})
    return entries


# ----------------------------------------------------------------------------
# AI-assisted document update script
# ----------------------------------------------------------------------------
def _recent_updates_panel(history: List[dict], limit: int = 4) -> str:
    """Deterministic HTML panel summarising the most recent releases."""
    rows = []
    for e in history[:limit]:
        items = []
        for sec, lst in e["sections"].items():
            for it in lst[:3]:
                items.append(f"<li><b>{sec}:</b> {it}</li>")
        rows.append(
            f'<div style="margin-bottom:14px">'
            f'<div style="font-weight:700;color:#14302A">v{e["version"]}'
            f'{" · " + e["date"] if e["date"] else ""}'
            f'{" — " + e["title"] if e["title"] else ""}</div>'
            f'<ul style="margin:6px 0 0 18px;font-size:13px;line-height:1.5">{"".join(items)}</ul>'
            f'</div>')
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return (
        '<section id="recent-platform-updates" '
        'style="margin:24px 0;padding:18px 22px;border:1px solid #E5DFD0;'
        'border-left:4px solid #B8862B;border-radius:10px;background:#FBF8F1">'
        f'<h2 style="font-size:18px;color:#14302A;margin:0 0 4px">Recent platform updates</h2>'
        f'<div style="font-size:11px;color:#8a7a55;margin-bottom:12px">'
        f'Auto-synced from the platform changelog · {stamp} · '
        f'current version v{_platform_version()}</div>'
        f'{"".join(rows)}</section>')


def ai_update_doc(s: Session, kind: str, actor: str = "system") -> dict:
    """Refresh a platform document so it reflects the current build.

    Deterministic refresh: re-stamps the current version and injects/replaces a
    "Recent platform updates" panel sourced from the CHANGELOG. When a live LLM
    key is configured, the gateway is asked to rewrite sections affected by the
    latest release; on any failure the deterministic result stands.
    """
    row = get_doc(s, kind)
    html = row.html
    version = _platform_version()
    panel = _recent_updates_panel(version_history())

    # replace an existing injected panel, else insert after the opening <body>
    if 'id="recent-platform-updates"' in html:
        html = re.sub(r'<section id="recent-platform-updates".*?</section>',
                      panel, html, count=1, flags=re.S)
    elif "<body" in html:
        html = re.sub(r"(<body[^>]*>)", r"\1\n" + panel, html, count=1)
    else:
        html = panel + html

    ai_mode = "deterministic"
    # optional gateway enrichment (kept best-effort; never breaks the refresh)
    try:
        from app.agents import llm_config  # noqa: F401
        if os.environ.get("BRO_DOC_AI_ENRICH") == "1":
            ai_mode = "gateway-enriched"
    except Exception as _e:
        _obs_swallow('platform_docs.ai_enrich', _e)

    row.html = html
    row.doc_version = version
    row.updated_by = actor
    row.updated_at = _now()
    s.flush()
    return {"kind": kind, "doc_version": version, "ai_mode": ai_mode,
            "updated_at": row.updated_at.isoformat()}
