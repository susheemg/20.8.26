"""BroCall — live voice TPRM assessment powered by OpenAI's Realtime API.

Design: OpenAI Realtime (gpt-realtime) is the *voice shell* — it hears, speaks and
handles turn-taking in the browser over WebRTC. The BroAssess methodology stays the
*authority*: the model is instructed to RECORD everything through tools that this
router executes, and it must NOT improvise the verdict — it calls compute_verdict,
which this server derives deterministically from the recorded dossier + findings.

This keeps the eight-stage methodology, the dossier and a full audit trail intact
while gaining a natural spoken interface. A BroCall session reuses ConversationSession,
so it can be captured to an assessment exactly like a BRO Chat.

Runtime note: the live call needs OPENAI_API_KEY set on the server (to mint the
browser's short-lived Realtime token) and a microphone in the browser. Everything
else — session, consent, tools, verdict, transcript, audit, Calendly webhook — runs
without any external dependency and is what this module tests.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .deps import RouterDeps
from app.features.domain.models_feature import ConversationSession, ConversationMessage
from app.features.assessment import agents as A
from app.features.domain import config_store as CFG

_STAGES = ["Context", "Intake", "IRQ", "Inherent rating", "Scoping",
           "Due diligence", "Residual", "Decision"]

_DECISION = {
    "LOW": "APPROVE — annual review cadence.",
    "MODERATE": "APPROVE WITH CONDITIONS — 6-month review.",
    "ELEVATED": "ESCALATE to CISO before proceeding.",
    "HIGH": "DO NOT PROCEED — requires CISO + Legal + CRO sign-off.",
}
_SEV_FLOOR = {"critical": "HIGH", "severe": "HIGH", "high": "ELEVATED",
              "moderate": "MODERATE", "medium": "MODERATE", "low": "LOW"}
_BAND_RANK = {"LOW": 1, "MODERATE": 2, "ELEVATED": 3, "HIGH": 4}

# ---- OpenAI Realtime tool schema (function calling) -----------------------------
_TOOLS = [
    {"type": "function", "name": "update_dossier",
     "description": "Record durable facts learned on the call (vendor, service, data types, "
                    "deployment, tier, jurisdictions, contract value, inherent_band, residual_band). "
                    "Call whenever a new fact is established so nothing is re-asked.",
     "parameters": {"type": "object", "properties": {
         "updates": {"type": "object", "description": "key/value facts to merge into the dossier"}},
         "required": ["updates"]}},
    {"type": "function", "name": "set_stage",
     "description": "Advance the assessment to a stage (0 Context, 1 Intake, 2 IRQ, 3 Inherent "
                    "rating, 4 Scoping, 5 Due diligence, 6 Residual, 7 Decision).",
     "parameters": {"type": "object", "properties": {
         "stage": {"type": "integer", "minimum": 0, "maximum": 7},
         "rationale": {"type": "string"}}, "required": ["stage"]}},
    {"type": "function", "name": "record_finding",
     "description": "Record a risk finding/observation in a domain with a severity.",
     "parameters": {"type": "object", "properties": {
         "domain": {"type": "string"},
         "severity": {"type": "string", "enum": ["low", "moderate", "high", "critical"]},
         "detail": {"type": "string"}}, "required": ["domain", "severity", "detail"]}},
    {"type": "function", "name": "request_document",
     "description": "Ask the caller to screenshare or upload a specific evidence document.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string"}}, "required": ["name"]}},
    {"type": "function", "name": "compute_verdict",
     "description": "At Stage 7 only. Returns the authoritative residual band and decision derived "
                    "from the recorded dossier and findings. Read out exactly what it returns; do "
                    "not invent a decision.",
     "parameters": {"type": "object", "properties": {}}},
]


def _instructions() -> str:
    bro = A.AGENT_BRIEFS.get("bro", "Senior TPRM consultant and lead orchestrator.")
    return (
        "You are Bro, the Risk Oracle, running a LIVE VOICE third-party risk assessment call. "
        + bro + "\n\n"
        "FIRST, before anything else, disclose that you are an AI assistant and that the call is "
        "being transcribed for the assessment record — this disclosure is mandatory.\n\n"
        + A.METHODOLOGY + "\n\n"
        "On the call: speak naturally and concisely; ONE question at a time; lead with the answer; "
        "never re-ask what is already established; always end each turn with a single clear ASK. "
        "Record everything durable through your tools — call update_dossier for each new fact, "
        "set_stage as you move through the eight stages, record_finding for each risk observation, "
        "and request_document when you need evidence the caller can screenshare or upload. "
        "Do NOT improvise the final decision: at Stage 7 call compute_verdict and read out exactly "
        "what it returns. Keep the caller informed of which stage you are in."
    )


def build_brocall_router(deps: RouterDeps) -> APIRouter:
    r = APIRouter(tags=["brocall"])
    db = deps.db
    require = deps.require
    audit = deps.audit

    def _load(s: Session, sid: int) -> ConversationSession:
        sess = s.get(ConversationSession, sid)
        if not sess:
            raise HTTPException(404, "BroCall session not found")
        return sess

    def _dossier(sess) -> dict:
        return json.loads(sess.dossier_json or "{}")

    def _save_dossier(sess, d):
        sess.dossier_json = json.dumps(d)

    # ---- session lifecycle ---------------------------------------------------
    @r.post("/api/v1/brocall/session")
    def create_session(b: dict = Body(default={}), s: Session = Depends(db),
                       u=Depends(require("engagement.view"))):
        sess = ConversationSession(engagement_id=b.get("engagement_id"),
                                   actor_role="assessor", stage=0, active_agent="bro",
                                   dossier_json=json.dumps({"_channel": "brocall"}))
        s.add(sess); s.flush()
        audit(s, "brocall.session_created", u.username, {"session_id": sess.id})
        s.commit()
        return {"session_id": sess.id, "stage": 0, "stages": _STAGES,
                "instructions": _instructions(), "tools": _TOOLS}

    @r.post("/api/v1/brocall/session/{sid}/consent")
    def consent(sid: int, b: dict = Body(...), s: Session = Depends(db),
                u=Depends(require("engagement.view"))):
        sess = _load(s, sid)
        d = _dossier(sess)
        d["consent"] = {"ai_disclosure": bool(b.get("ai_disclosure")),
                        "recording": bool(b.get("recording")),
                        "by": u.username, "at": int(time.time())}
        _save_dossier(sess, d)
        s.add(ConversationMessage(session_id=sid, role="system", agent="bro", stage=sess.stage,
              body="Consent recorded — AI disclosure acknowledged and recording/transcription "
                   "consent captured for the assessment record."))
        audit(s, "brocall.consent", u.username, {"session_id": sid, **d["consent"]})
        s.commit()
        return {"ok": True, "consent": d["consent"]}

    @r.post("/api/v1/brocall/session/{sid}/token")
    def mint_token(sid: int, s: Session = Depends(db),
                   u=Depends(require("engagement.view"))):
        """Mint a short-lived OpenAI Realtime token for the browser. The server's real
        API key never reaches the client. Returns enabled:false (not an error) when no
        key is configured, so the UI can degrade gracefully."""
        sess = _load(s, sid)
        if not _dossier(sess).get("consent", {}).get("ai_disclosure"):
            raise HTTPException(400, "Consent (AI disclosure) must be recorded before starting the call")
        key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("BROCALL_MODEL", "gpt-realtime")
        voice = os.environ.get("BROCALL_VOICE", "cedar")
        if not key:
            return {"enabled": False,
                    "reason": "Set OPENAI_API_KEY on the server to enable live BroCall.",
                    "model": model, "voice": voice,
                    "instructions": _instructions(), "tools": _TOOLS}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        secret = expires = None
        try:
            resp = httpx.post("https://api.openai.com/v1/realtime/client_secrets",
                              headers=headers, json={"session": {"type": "realtime", "model": model}},
                              timeout=15)
            if resp.status_code >= 400:
                resp = httpx.post("https://api.openai.com/v1/realtime/sessions",
                                  headers=headers, json={"model": model, "voice": voice}, timeout=15)
            data = resp.json()
            secret = (data.get("client_secret") or {}).get("value") or data.get("value")
            expires = data.get("expires_at") or (data.get("client_secret") or {}).get("expires_at")
        except Exception as e:  # noqa
            return {"enabled": False, "reason": f"OpenAI token request failed: {e}",
                    "model": model, "voice": voice, "instructions": _instructions(), "tools": _TOOLS}
        if not secret:
            return {"enabled": False, "reason": "OpenAI did not return a client secret",
                    "model": model, "voice": voice, "instructions": _instructions(), "tools": _TOOLS}
        audit(s, "brocall.token_minted", u.username, {"session_id": sid, "model": model})
        s.commit()
        return {"enabled": True, "client_secret": secret, "expires_at": expires,
                "model": model, "voice": voice,
                "instructions": _instructions(), "tools": _TOOLS}

    # ---- the tool bridge (BroAssess methodology as the authority) -------------
    def _t_update_dossier(sess, args):
        d = _dossier(sess)
        ups = args.get("updates") or {}
        if isinstance(ups, dict):
            d.update(ups)
        _save_dossier(sess, d)
        return {"ok": True, "dossier_keys": sorted(k for k in d.keys() if not k.startswith("_"))}

    def _t_set_stage(sess, args):
        st = int(args.get("stage", sess.stage))
        st = max(0, min(7, st))
        sess.stage = st
        return {"ok": True, "stage": st, "stage_name": _STAGES[st]}

    def _t_record_finding(sess, args):
        d = _dossier(sess)
        findings = d.setdefault("findings", [])
        findings.append({"domain": args.get("domain"), "severity": (args.get("severity") or "moderate").lower(),
                         "detail": args.get("detail"), "at": int(time.time())})
        d["findings"] = findings[-100:]
        _save_dossier(sess, d)
        return {"ok": True, "finding_count": len(findings)}

    def _t_request_document(sess, args):
        return {"ok": True, "message": f"Ask the caller to screenshare or upload: {args.get('name')}",
                "upload_hint": "Documents can be attached in the BroCall panel and are stored for audit."}

    def _t_compute_verdict(sess, args):
        d = _dossier(sess)
        inherent = str(d.get("inherent_band") or "MODERATE").upper()
        # residual: model's recorded residual, else derived from findings + inherent (risk-averse)
        residual = str(d.get("residual_band") or "").upper()
        floor = "LOW"
        for f in d.get("findings", []):
            fb = _SEV_FLOOR.get(str(f.get("severity", "")).lower(), "LOW")
            if _BAND_RANK[fb] > _BAND_RANK[floor]:
                floor = fb
        if residual not in _BAND_RANK:
            # derive: not better than inherent, not better than the worst-finding floor
            base = inherent if inherent in _BAND_RANK else "MODERATE"
            residual = base if _BAND_RANK[base] >= _BAND_RANK[floor] else floor
        else:
            # even a model-set residual cannot beat a critical-finding floor
            if _BAND_RANK[floor] > _BAND_RANK[residual]:
                residual = floor
        decision = _DECISION.get(residual, _DECISION["MODERATE"])
        d["residual_band"] = residual
        d["verdict"] = {"residual_band": residual, "decision": decision, "at": int(time.time())}
        _save_dossier(sess, d)
        return {"residual_band": residual, "decision": decision,
                "inherent_band": inherent, "findings_count": len(d.get("findings", [])),
                "rationale": "Residual derived from recorded inherent exposure and findings; a "
                             "critical/severe finding floors residual at HIGH regardless of arithmetic."}

    _DISPATCH = {"update_dossier": _t_update_dossier, "set_stage": _t_set_stage,
                 "record_finding": _t_record_finding, "request_document": _t_request_document,
                 "compute_verdict": _t_compute_verdict}

    @r.post("/api/v1/brocall/session/{sid}/tool")
    def call_tool(sid: int, b: dict = Body(...), s: Session = Depends(db),
                  u=Depends(require("engagement.view"))):
        sess = _load(s, sid)
        name = b.get("name")
        args = b.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        fn = _DISPATCH.get(name)
        if not fn:
            raise HTTPException(400, f"unknown tool: {name}")
        result = fn(sess, args)
        audit(s, "brocall.tool", u.username, {"session_id": sid, "tool": name})
        s.commit()
        return {"tool": name, "result": result, "stage": sess.stage}

    @r.post("/api/v1/brocall/session/{sid}/transcript")
    def append_transcript(sid: int, b: dict = Body(...), s: Session = Depends(db),
                          u=Depends(require("engagement.view"))):
        sess = _load(s, sid)
        turns = b.get("turns") or []
        for t in turns:
            role = "user" if (t.get("role") == "user") else "agent"
            txt = (t.get("text") or "").strip()
            if txt:
                s.add(ConversationMessage(session_id=sid, role=role, agent="bro",
                                          stage=sess.stage, body=txt))
        s.commit()
        return {"ok": True, "added": len(turns)}

    @r.get("/api/v1/brocall/session/{sid}")
    def get_session(sid: int, s: Session = Depends(db),
                    u=Depends(require("engagement.view"))):
        sess = _load(s, sid)
        from sqlalchemy import select
        msgs = s.scalars(select(ConversationMessage)
                         .where(ConversationMessage.session_id == sid)
                         .order_by(ConversationMessage.id)).all()
        return {"session_id": sid, "stage": sess.stage, "stage_name": _STAGES[sess.stage],
                "dossier": _dossier(sess),
                "transcript": [{"role": m.role, "body": m.body} for m in msgs]}

    # ---- Calendly webhook: provision a BroCall session on booking -------------
    @r.post("/api/v1/brocall/calendly/webhook")
    async def calendly_webhook(request: Request, s: Session = Depends(db)):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        event = payload.get("event")
        if event and event != "invitee.created":
            return {"ignored": event}
        p = payload.get("payload") or {}
        invitee = {"name": p.get("name"), "email": p.get("email"),
                   "event_uri": p.get("event"), "scheduled_at": p.get("scheduled_event", {}).get("start_time")}
        sess = ConversationSession(actor_role="assessor", stage=0, active_agent="bro",
                                   dossier_json=json.dumps({"_channel": "brocall",
                                                            "booking": invitee}))
        s.add(sess); s.flush()
        CFG.upsert_json(s, f"brocall_booking_{sess.id}", invitee, updated_by="calendly",
                        category="_brocall")
        audit(s, "brocall.provisioned_from_calendly", "calendly",
              {"session_id": sess.id, "email": invitee.get("email")})
        s.commit()
        return {"provisioned": True, "session_id": sess.id}

    return r
