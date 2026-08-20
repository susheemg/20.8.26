"""
Email service: real SMTP send with a simulation-outbox fallback.

Production-grade pattern: if SMTP is configured (BRO_SMTP_HOST etc.), mail is
actually sent; otherwise every message is written to the email_outbox table as
sent=False so the workflow is fully demonstrable offline (matches the original
BRO "simulation mode"). Either way the send is recorded for audit.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Optional


def smtp_configured() -> bool:
    return bool(os.environ.get("BRO_SMTP_HOST"))


def send_email(to_addr: str, subject: str, body: str) -> bool:
    """Send via SMTP if configured. Returns True if actually sent, False if
    it should be recorded to the simulation outbox by the caller."""
    if not smtp_configured():
        return False
    host = os.environ["BRO_SMTP_HOST"]
    port = int(os.environ.get("BRO_SMTP_PORT", "587"))
    user = os.environ.get("BRO_SMTP_USER")
    pw = os.environ.get("BRO_SMTP_PASSWORD")
    sender = os.environ.get("BRO_SMTP_FROM", user or "noreply@bro.example")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as s:
        s.starttls()
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return True
