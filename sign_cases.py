#!/usr/bin/env python3
"""Assessor sign-off for evaluation cases (AI-02, step 2).

WHY THIS EXISTS
---------------
The evaluation suite reports that its cases are engineer-authored rather than signed
by a second-line assessor, and the roadmap named assessor sign-off as the single most
valuable next action. It had not happened for a mundane reason: there was no way to do
it. An assessor cannot review a Python literal in a source file, and asking them to
edit one would be both unreasonable and unauditable.

This gives them a reviewable queue and records the signature as evidence:

    python3 tools/sign_cases.py --list                 # what is awaiting review
    python3 tools/sign_cases.py --show BAND-01         # one case, in full
    python3 tools/sign_cases.py --sign BAND-01 \\
            --by "j.smith" --role "VRM Lead" --verdict agree \\
            --comment "Matches SOP R-RES-1."
    python3 tools/sign_cases.py --status               # coverage by dimension

A signature is a claim about the *expected outcome*, not about the code. The assessor
is asserting: given these inputs, this is the answer the methodology requires. That is
exactly the judgement an engineer is not qualified to make, and exactly what turns a
conformance test into a golden case.

A verdict of `disagree` is as valuable as `agree` — it means the case is wrong, or the
methodology is ambiguous, and both are findings. Disagreed cases are excluded from the
gate and reported separately rather than quietly deleted.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_cases.json")

VERDICTS = ("agree", "disagree", "needs_discussion")


def _load():
    with open(STORE) as f:
        return json.load(f)


def _save(d):
    with open(STORE, "w") as f:
        json.dump(d, f, indent=1, default=str)


def _sig_state(c):
    s = c.get("signature")
    if not s:
        return "unsigned"
    return s.get("verdict", "unsigned")


def cmd_list(d, dimension=None, unsigned_only=True):
    rows = [c for c in d["cases"]
            if (not dimension or c["dimension"] == dimension)
            and (not unsigned_only or _sig_state(c) == "unsigned")]
    if not rows:
        print("Nothing awaiting review." if unsigned_only else "No cases match.")
        return
    print(f"{'CASE':10s} {'DIMENSION':13s} {'STATE':17s} RATIONALE")
    print("-" * 100)
    for c in rows:
        print(f"{c['id']:10s} {c['dimension']:13s} {_sig_state(c):17s} {c['why'][:56]}")
    print(f"\n{len(rows)} case(s). Review one with --show, then --sign.")


def cmd_show(d, cid):
    for c in d["cases"]:
        if c["id"] == cid:
            print(f"\nCASE      {c['id']}   ({c['dimension']})")
            print(f"STATE     {_sig_state(c)}")
            print(f"\nWHAT THE METHODOLOGY REQUIRES (the claim you are being asked to confirm):")
            print(f"  {c['why']}")
            print("\nINPUTS")
            for k, v in c.items():
                if k in ("id", "dimension", "why", "labelled_by", "signature"):
                    continue
                print(f"  {k:26s} {v}")
            if c.get("signature"):
                s = c["signature"]
                print(f"\nSIGNED    {s['verdict']} by {s['signed_by']} ({s['role']}) "
                      f"on {s['signed_at']}")
                if s.get("comment"):
                    print(f"COMMENT   {s['comment']}")
            print("\nTo sign:  python3 tools/sign_cases.py --sign "
                  f"{c['id']} --by NAME --role ROLE --verdict agree")
            return
    print(f"No such case: {cid}", file=sys.stderr)
    sys.exit(2)


def cmd_sign(d, cid, by, role, verdict, comment):
    if verdict not in VERDICTS:
        print(f"verdict must be one of {VERDICTS}", file=sys.stderr)
        sys.exit(2)
    for c in d["cases"]:
        if c["id"] == cid:
            if c.get("signature"):
                prior = c["signature"]
                print(f"NOTE: replacing a prior signature by {prior['signed_by']} "
                      f"({prior['verdict']}, {prior['signed_at']}).")
            c["signature"] = {
                "signed_by": by, "role": role, "verdict": verdict,
                "comment": comment or "",
                "signed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "methodology_version": d.get("methodology_version"),
            }
            if verdict == "agree":
                c["labelled_by"] = "assessor"
            _save(d)
            print(f"{cid}: recorded '{verdict}' by {by} ({role}).")
            if verdict == "agree":
                print("  → promoted to a golden case; it now counts toward gate coverage.")
            else:
                print("  → excluded from the gate. A disagreement means the case is wrong or "
                      "the methodology is ambiguous; both are findings worth raising.")
            return
    print(f"No such case: {cid}", file=sys.stderr)
    sys.exit(2)


def cmd_status(d):
    dims = {}
    for c in d["cases"]:
        s = dims.setdefault(c["dimension"], {"total": 0, "agree": 0, "disagree": 0,
                                             "discuss": 0, "unsigned": 0})
        s["total"] += 1
        st = _sig_state(c)
        s[{"agree": "agree", "disagree": "disagree",
           "needs_discussion": "discuss", "unsigned": "unsigned"}[st]] += 1

    print(f"\nMethodology version: {d.get('methodology_version')}")
    print(f"{'DIMENSION':14s} {'TOTAL':>6s} {'SIGNED':>7s} {'DISAGREE':>9s} "
          f"{'DISCUSS':>8s} {'UNSIGNED':>9s}  COVERAGE")
    print("-" * 74)
    tot = sig = 0
    for dim, s in sorted(dims.items()):
        cov = (s["agree"] / s["total"]) if s["total"] else 0
        tot += s["total"]; sig += s["agree"]
        print(f"{dim:14s} {s['total']:6d} {s['agree']:7d} {s['disagree']:9d} "
              f"{s['discuss']:8d} {s['unsigned']:9d}  {cov:6.0%}")
    print("-" * 74)
    print(f"{'ALL':14s} {tot:6d} {sig:7d} {'':9s} {'':8s} {'':9s}  {(sig/tot if tot else 0):6.0%}")
    if sig == 0:
        print("\nNo case is assessor-signed yet. The evaluation suite therefore measures")
        print("conformance to the documented methodology, not assessment quality as a")
        print("reviewer would judge it — and it says so on every run.")
    elif sig < tot:
        print(f"\n{tot - sig} case(s) still awaiting review.")
    else:
        print("\nEvery case is assessor-signed. The suite now measures reviewed judgement.")


def main():
    ap = argparse.ArgumentParser(description="Assessor sign-off for evaluation cases")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true", help="with --list, include signed cases")
    ap.add_argument("--dimension")
    ap.add_argument("--show", metavar="CASE_ID")
    ap.add_argument("--sign", metavar="CASE_ID")
    ap.add_argument("--by"); ap.add_argument("--role")
    ap.add_argument("--verdict", choices=VERDICTS)
    ap.add_argument("--comment", default="")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    d = _load()

    if a.show:
        cmd_show(d, a.show)
    elif a.sign:
        if not (a.by and a.role and a.verdict):
            print("--sign requires --by, --role and --verdict", file=sys.stderr)
            sys.exit(2)
        cmd_sign(d, a.sign, a.by, a.role, a.verdict, a.comment)
    elif a.status:
        cmd_status(d)
    else:
        cmd_list(d, a.dimension, unsigned_only=not a.all)


if __name__ == "__main__":
    main()
