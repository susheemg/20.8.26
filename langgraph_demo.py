#!/usr/bin/env python3
"""Demo: python3 langgraph_demo.py [--mermaid]"""
import sys
from app.agents import langgraph_flow as LG

if "--mermaid" in sys.argv:
    print(LG.to_mermaid()); sys.exit(0)
print("=== BRO ProAssess — LangGraph topology ===\n"); print(LG.to_mermaid())
print("\n=== Executing (deterministic engine) ===\n")
final = LG.run_assessment("Cloud payments processor handling cardholder data, cross-border, FCA-regulated.",
                          dossier={"residual_band": "ELEVATED"})
for t in final["transcript"]:
    print(f"  [Stage {t['stage']}] {t['agent']:<10} {t['body'][:96]}")
v = final.get("verdict") or {}
print(f"\n  VERDICT ({v.get('residual_band')}): {v.get('decision')}")
