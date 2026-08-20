"""Dump-to-Draft: upload documents on a form; AI fills feasible fields. Live model
when configured; deterministic label-matching fallback offline."""
from __future__ import annotations
import io, re, zipfile
from typing import Optional


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass


def extract_text(filename: str, data: bytes) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    try:
        if ext in ("txt", "md", "csv", "json", "eml"):
            return data.decode("utf-8", errors="replace")
        if ext == "pdf":
            from pypdf import PdfReader
            rd = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in rd.pages[:40])
        if ext == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", xml)
    except Exception as _e:
        _obs_swallow('draftfill.py', _e)
    return ""

def heuristic_fill(fields: list, text: str) -> dict:
    out = {}; lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for f in fields or []:
        label = (f.get("label") or "").strip()
        if not label:
            continue
        pat = re.compile(rf"^{re.escape(label)}\s*[:\-–]\s*(.+)$", re.I)
        for ln in lines:
            m = pat.match(ln)
            if m and m.group(1).strip():
                out[f["id"]] = m.group(1).strip()[:500]; break
    return out

def ai_fill(s, fields: list, text: str, context: str = "") -> Optional[dict]:
    from app.agents import llm_config
    from app.features.assessment import prompts as PROMPTS
    from app.features.assessment.ai_json import parse_json_strict, wrap_untrusted, UNTRUSTED_PREAMBLE
    if not llm_config.status().get("live_ready"):
        return None
    spec = "\n".join(f"- {f['id']}: {f.get('label','')}" + (f" (options: {', '.join(f['options'])})" if f.get("options") else "") for f in fields)
    system = (UNTRUSTED_PREAMBLE + "\n\n" + PROMPTS.resolve(s, "dump_to_draft")
              + "\n\nFORM FIELDS:\n" + spec + (f"\n\nFORM CONTEXT: {context}" if context else ""))
    raw = llm_config.complete(system, wrap_untrusted(text[:24000]), domain="forms", max_tokens=1500)
    return parse_json_strict(raw) if raw else None
