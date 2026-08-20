# GAP REGISTER — Deep-dive audit (UI reachability)

Method: backend workflow simulation (31/31 substantive checks pass across R1-R6 + ProAssess),
full nav audit (25/25 screens render, 0 JS errors), form-depth audit. Backend is sound;
every gap is UI-layer — built and tested but not reachable or not surfaced as primary.

| ID | Sev | Req | Finding | Fix |
|----|-----|-----|---------|-----|
| G1 | HIGH | R4 | No `performance` nav item and no view. Vendor Performance Management is entirely unreachable. | Add nav item + full V.performance view (scorecard list, dimensions/KPIs, agree/publish, QBR, CAPA), gated to critical vendors. |
| G2 | HIGH | R1 | Primary "New vendor" form has only 6 fields vs ~50 in master. The rich Master-record + 9-tab Attributes editors are no longer reachable (the "Master record" button is gone from the vendor modal). | Restore reachable links to openVendorMaster + openVendorAttributes from the vendor row/modal; make master the primary record. |
| G3 | MED | R5 | ProAssess backend complete + tested but no nav item / no run screen. | Add nav item + V.proassess view (IRQ inputs, docs, run, render report, register). |
| G4 | LOW | R2 | Engagement register exposes Contract tab (good); contracts not also shown inline on vendor 360 contract list beyond count. | Minor: surface contract list rows in 360 (already shows count + critical count). Defer. |

## Execution order
G1 (performance screen) -> G2 (restore R1 master/attributes reachability) -> G3 (ProAssess screen) -> re-verify all in browser -> full regression.
