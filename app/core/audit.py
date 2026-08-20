"""
Append-only, hash-chained audit trail.

Every consequential event (policy resolved, snapshot taken, AI verdict emitted,
human validation, override with reason code) becomes an immutable entry. Each
entry embeds the hash of the previous entry, forming a chain: altering any past
entry breaks every subsequent hash, making tampering evident.

This is tamper-EVIDENT, not tamper-PROOF — sufficient for GRC defensibility
without a specialist ledger DB. In Postgres this maps to an append-only table
with a trigger preventing UPDATE/DELETE; here we model the chain logic itself
so it can be unit-tested independently of storage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

GENESIS_HASH = "0" * 64


def _entry_hash(
    prev_hash: str,
    seq: int,
    org_id: str,
    event_type: str,
    actor: str,
    timestamp: str,
    payload: dict[str, Any],
) -> str:
    material = json.dumps(
        {
            "prev_hash": prev_hash,
            "seq": seq,
            "org_id": org_id,
            "event_type": event_type,
            "actor": actor,
            "timestamp": timestamp,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    org_id: str
    event_type: str
    actor: str               # human user id, or "system"/agent id
    timestamp: str           # ISO 8601 UTC
    payload: dict[str, Any]  # provenance: control versions, confidence, reason codes
    prev_hash: str
    entry_hash: str


class AuditTrail:
    """In-memory chain. Storage layer persists each AuditEntry append-only."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @property
    def head_hash(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS_HASH

    def append(
        self,
        org_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> AuditEntry:
        seq = len(self._entries)
        prev = self.head_hash
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        h = _entry_hash(prev, seq, org_id, event_type, actor, ts, payload)
        entry = AuditEntry(
            seq=seq,
            org_id=org_id,
            event_type=event_type,
            actor=actor,
            timestamp=ts,
            payload=payload,
            prev_hash=prev,
            entry_hash=h,
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> bool:
        """Recompute the chain; returns False if any entry was altered."""
        prev = GENESIS_HASH
        for i, e in enumerate(self._entries):
            if e.seq != i or e.prev_hash != prev:
                return False
            recomputed = _entry_hash(
                e.prev_hash, e.seq, e.org_id, e.event_type,
                e.actor, e.timestamp, e.payload,
            )
            if recomputed != e.entry_hash:
                return False
            prev = e.entry_hash
        return True

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)
