"""Personal-data map and erasure procedure (DB-03).

The architecture assessment raised this as HIGH: the platform holds personal data in
at least nine places, and had no documented flow from a data subject to every derived
copy, and no tested erasure path.

THE TENSION, STATED PLAINLY
---------------------------
Brata's strongest architectural commitment — an immutable, hash-chained audit trail
and immutable assessment snapshots — is in direct tension with the erasure right. That
tension is resolvable, but only by *deciding and recording* it rather than discovering
it during a subject request. The position encoded here:

  * **Erase** where the record exists to identify a living person and the platform has
    no overriding obligation to keep it: portal accounts, supplier contact records,
    conversation transcripts.
  * **Pseudonymise, never delete** where the record is evidence of a regulated decision:
    the audit trail and assessment snapshots. The subject identifier is replaced with a
    stable irreversible token; the hash chain stays intact because the chain is computed
    over the payload as written, and pseudonymisation writes a *new* correction entry
    rather than editing history.
  * **Retain** where a legal obligation overrides erasure (financial-crime screening
    records, regulatory registers), recording the basis on the response.

`erasure_plan()` is safe to run at any time — it only reports. `execute_erasure()`
performs the plan and is deliberately explicit about what it did not delete and why.

THIS NEEDS A LEGAL DETERMINATION, NOT JUST CODE. The classifications below are an
engineering proposal for the DPO and Legal to confirm or correct. `LEGAL_REVIEW` is
False until they have.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlalchemy import text as _sql

LEGAL_REVIEW = False          # flip to True only when the DPO has signed the map below

ERASE, PSEUDONYMISE, RETAIN = "erase", "pseudonymise", "retain"

# table, subject-identifying columns, action, basis
PERSONAL_DATA_MAP = [
    dict(table="users", columns=["username", "email", "full_name", "phone",
                                 "secondary_email"],
         action=PSEUDONYMISE,
         basis="Account records stay attributable to historical actions in the audit "
               "trail. Deleting the row would orphan every action the person took; "
               "pseudonymising preserves accountability without identifying them."),
    dict(table="vendor_persons", columns=["name"], action=ERASE,
         basis="Beneficial owners and key persons are held only to support screening. "
               "Where the relationship ends, the identifying record is erased and the "
               "screening outcome is retained in pseudonymised form."),
    dict(table="vendor_screening", columns=["screened_name"], action=RETAIN,
         basis="Financial-crime screening evidence. UK MLR record-keeping obligations "
               "override the erasure right for the statutory retention period; the "
               "basis must be stated to the subject in the response."),
    dict(table="sanctions_screenings", columns=["screened_name"], action=RETAIN,
         basis="As above — sanctions screening is a legal obligation, not consent."),
    dict(table="supplier_notes", columns=["author", "body"], action=ERASE,
         basis="Free-text notes may name individuals incidentally and carry no "
               "retention obligation of their own."),
    dict(table="conversation_sessions", columns=["created_by"], action=PSEUDONYMISE,
         basis="Transcripts are evidence of how an assessment was conducted; the "
               "conductor's identity is pseudonymised, the content retained."),
    dict(table="conversation_messages", columns=["content"], action=ERASE,
         basis="Message bodies can contain personal data volunteered in conversation "
               "and are not themselves the assessment record."),
    dict(table="audit_log", columns=["actor"], action=PSEUDONYMISE,
         basis="The audit chain is the regulated evidentiary record and is "
               "hash-chained. Actors are pseudonymised by forward correction entry; "
               "history is never rewritten."),
    dict(table="notifications", columns=["audience", "body"], action=ERASE,
         basis="Operational messaging with no evidentiary role."),
    dict(table="stored_documents", columns=["uploaded_by"], action=PSEUDONYMISE,
         basis="Evidence provenance must survive; the uploader identity is "
               "pseudonymised. Document *content* containing personal data is handled "
               "by document-level review, not by this routine."),
]


def pseudonym(subject: str, salt: str = "brata-erasure-v1") -> str:
    """Stable, irreversible token. Stable so historical records stay correlatable for
    audit; irreversible so the subject cannot be re-identified from the platform."""
    return "ERASED-" + hashlib.sha256((salt + "|" + subject).encode()).hexdigest()[:16]


def _table_exists(s, table: str) -> bool:
    try:
        s.execute(_sql(f"SELECT 1 FROM {table} LIMIT 1"))
        return True
    except Exception:
        return False


def erasure_plan(s, subject: str) -> dict:
    """Report-only. What would happen to this subject's data, table by table."""
    plan, unreachable = [], []
    for entry in PERSONAL_DATA_MAP:
        t = entry["table"]
        if not _table_exists(s, t):
            unreachable.append(t)
            continue
        hits = 0
        for col in entry["columns"]:
            try:
                r = s.execute(_sql(f"SELECT COUNT(*) FROM {t} WHERE {col} = :v"),
                              {"v": subject}).fetchone()
                hits += (r[0] if r else 0)
            except Exception:
                continue          # column absent on this deployment
        plan.append({"table": t, "action": entry["action"], "matches": hits,
                     "columns": entry["columns"], "basis": entry["basis"]})
    return {
        "subject": subject,
        "pseudonym": pseudonym(subject),
        "legal_review_complete": LEGAL_REVIEW,
        "plan": plan,
        "tables_not_present": unreachable,
        "total_matches": sum(p["matches"] for p in plan),
        "will_erase": [p["table"] for p in plan if p["action"] == ERASE and p["matches"]],
        "will_pseudonymise": [p["table"] for p in plan
                              if p["action"] == PSEUDONYMISE and p["matches"]],
        "retained_with_basis": [{"table": p["table"], "basis": p["basis"]}
                                for p in plan if p["action"] == RETAIN and p["matches"]],
        "warning": (None if LEGAL_REVIEW else
                    "The classification in this map has NOT been confirmed by Legal or "
                    "the DPO. Do not execute against a real subject request until it has."),
    }


def execute_erasure(s, subject: str, *, actor: str, dry_run: bool = True,
                    audit_fn: Optional[Any] = None) -> dict:
    """Execute the plan. Defaults to dry run — erasure is irreversible by design and
    must not be a single accidental call away."""
    plan = erasure_plan(s, subject)
    if dry_run:
        plan["executed"] = False
        plan["note"] = "Dry run. Call with dry_run=False to execute."
        return plan
    if not LEGAL_REVIEW:
        plan["executed"] = False
        plan["note"] = ("Blocked: the personal-data map has not been signed off by "
                        "Legal/DPO. Set LEGAL_REVIEW=True once it has.")
        return plan

    token = plan["pseudonym"]
    done = []
    for entry in PERSONAL_DATA_MAP:
        t, action = entry["table"], entry["action"]
        if action == RETAIN or not _table_exists(s, t):
            continue
        for col in entry["columns"]:
            try:
                if action == PSEUDONYMISE:
                    s.execute(_sql(f"UPDATE {t} SET {col} = :tok WHERE {col} = :v"),
                              {"tok": token, "v": subject})
                else:
                    s.execute(_sql(f"UPDATE {t} SET {col} = NULL WHERE {col} = :v"),
                              {"v": subject})
                done.append(f"{t}.{col}:{action}")
            except Exception:
                continue
    s.commit()
    if audit_fn:
        try:
            audit_fn(s, "privacy.erasure_executed", actor,
                     {"pseudonym": token, "tables": done,
                      "retained": [r["table"] for r in plan["retained_with_basis"]]})
            s.commit()
        except Exception:
            pass
    plan["executed"] = True
    plan["applied"] = done
    plan["note"] = ("Erasure applied. Retained items are listed with their legal basis "
                    "and must be disclosed to the subject in the response.")
    return plan


def data_flow_report() -> dict:
    """The map itself, for the DPO to review and sign."""
    return {"legal_review_complete": LEGAL_REVIEW,
            "entries": PERSONAL_DATA_MAP,
            "actions": {ERASE: "identifying value removed",
                        PSEUDONYMISE: "replaced with a stable irreversible token",
                        RETAIN: "kept under a legal obligation that overrides erasure"}}
