"""
Inbound email certificate intake.

A mail-receiver service (e.g. SendGrid Inbound Parse, Mailgun Routes, or an IMAP
poller) is configured at deploy time to POST parsed inbound emails to the
webhook endpoint. This module is the processing pipeline behind that endpoint:

  match sender -> vendor  ->  file attachment as a NEW artefact (ART-xxxxxx)
  -> supersede the prior certificate of the same name  ->  auto-close any open
     expired-certificate Issue for that vendor/artefact.

The pipeline is fully testable with a synthetic payload (no live mail needed);
only the *receiving* hookup is deployment-specific.
"""
from __future__ import annotations

import base64
import re
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.domain import registry_service as RS
from app.features.domain.registry_models import ArtefactRecord, ContactRecord, VendorRecord


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



def _match_vendor_by_email(s: Session, sender: str) -> Optional[str]:
    """Find the vendor whose primary/any contact email matches the sender, or
    whose domain matches the sender's domain."""
    sender = (sender or "").strip().lower()
    if not sender:
        return None
    # exact contact email match (vendor-owned contacts)
    for c in s.scalars(select(ContactRecord).where(
            ContactRecord.owner_type == "vendor")).all():
        if (c.email or "").strip().lower() == sender:
            return c.owner_id
    # domain match against vendor website
    dom = sender.split("@")[-1] if "@" in sender else ""
    if dom:
        for v in s.scalars(select(VendorRecord)).all():
            site = (v.website or "").lower()
            if dom and dom in site:
                return v.vendor_id
    return None


_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _guess_expiry(text: str) -> Optional[str]:
    """Best-effort expiry extraction from certificate text (deterministic)."""
    t = (text or "").lower()
    # look for an explicit 'valid until / expires / expiry' line
    for kw in ("valid until", "valid through", "expires", "expiry", "expiration"):
        idx = t.find(kw)
        if idx != -1:
            m = _DATE_RE.search(t[idx:idx + 60])
            if m:
                y, mo, d = m.groups()
                try:
                    return date(int(y), int(mo), int(d)).isoformat()
                except ValueError as _e:
                    _obs_swallow('email_intake.py', _e)
    # otherwise the latest date present
    dates = []
    for m in _DATE_RE.finditer(t):
        y, mo, d = m.groups()
        try:
            dates.append(date(int(y), int(mo), int(d)))
        except ValueError as _e:
            _obs_swallow('email_intake.py', _e)
    return max(dates).isoformat() if dates else None


def process_inbound_email(s: Session, *, sender: str, subject: str,
                          attachment_name: str,
                          attachment_b64: Optional[str] = None,
                          body_text: str = "",
                          vendor_id: Optional[str] = None) -> dict:
    """Process one inbound email carrying a refreshed certificate.

    Returns a result dict. If the sender can't be matched to a vendor and none is
    supplied, the email is parked (status='unmatched') for manual triage.
    """
    vid = vendor_id or _match_vendor_by_email(s, sender)
    if not vid:
        return {"status": "unmatched", "sender": sender,
                "reason": "no vendor matched sender email/domain"}

    # decode attachment text if provided (for expiry extraction)
    text = body_text or ""
    if attachment_b64:
        try:
            raw = base64.b64decode(attachment_b64)
            # text-readable portion only; PDFs would route through the extractor
            text += " " + raw.decode("utf-8", errors="ignore")
        except Exception as _e:
            _obs_swallow('email_intake.py', _e)

    name = (subject or attachment_name or "Certificate").strip()
    expiry = _guess_expiry(text)

    # find the prior current artefact of the same name to supersede
    prior = None
    for a in s.scalars(select(ArtefactRecord).where(
            ArtefactRecord.vendor_id == vid,
            ArtefactRecord.is_current == True)).all():  # noqa: E712
        if a.name.split()[0].lower() in name.lower() or name.lower() in a.name.lower():
            prior = a
            break

    art = RS.create_artefact(
        s, vendor_id=vid, name=name, artefact_type="certificate",
        expiry_date=(expiry + "T00:00:00") if expiry else None,
        received_via="email", supersedes=prior.artefact_id if prior else None)

    return {"status": "filed", "vendor_id": vid, "artefact_id": art.artefact_id,
            "artefact_status": art.status, "expiry_date": expiry,
            "superseded": prior.artefact_id if prior else None}
