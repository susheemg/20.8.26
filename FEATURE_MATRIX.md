# BRO Risk Oracle — Functional Feature Matrix

Granular, role-by-role inventory of every functional feature, audited against the
actual codebase (50 routes, web UI, 120 tests).

**Legend**
- ✓ = present and usable in the **web UI**
- ◐ = present in the **API only** (works, but no UI screen yet)
- ✗ = missing / not built

---

## 1. Authentication & Session (all users)

| Feature | Status | Notes |
|---|---|---|
| Log in with username + password | ✓ | JWT issued |
| Log out | ✓ | clears token |
| Session persists on refresh | ✓ | token in sessionStorage |
| Token expiry (8h) | ✓ | enforced server-side |
| Change own password | ✗ | no endpoint |
| Reset / forgot password | ✗ | |
| Multi-factor authentication (MFA) | ✗ | |
| Account lockout after failed attempts | ✗ | |
| Login rate limiting | ✗ | |
| "Remember me" / refresh token | ✗ | no refresh flow |
| View own profile | ✗ | |
| Edit own profile (name, email) | ✗ | |

---

## 2. Buyer / Business Lead

### Vendor management
| Feature | Status | Notes |
|---|---|---|
| Create vendor | ✓ | |
| View vendor register / list | ✓ | |
| **Edit vendor record (name, industry, country)** | ✗ | no update endpoint |
| **Change vendor contact** | ✗ | |
| Delete / archive vendor | ✗ | |
| Search / filter vendors | ✗ | list is unfiltered |
| Sort vendor list | ✗ | |
| View single vendor detail page | ✗ | only list row |
| Vendor risk history / timeline | ✗ | |

### Engagements
| Feature | Status | Notes |
|---|---|---|
| Create engagement | ✓ | |
| Set business contact on engagement | ◐ | API field exists, no UI input |
| **Edit engagement details** | ✗ | no update endpoint |
| View engagement detail | ✓ | |
| List all engagements (cross-session) | ✗ | UI tracks per-session only; no list-all API |
| Filter / search engagements | ✗ | |
| Delete / cancel engagement | ✗ | |

### Assessment workflow
| Feature | Status | Notes |
|---|---|---|
| Complete IRQ (inherent questionnaire) | ✓ | simplified question set in UI |
| Full 12-question IRQ | ◐ | engine supports it; UI uses a subset |
| See inherent band + confidence (CLS) | ✓ | |
| See straight-through routing result | ✓ | AUTO/FAST/FULL |
| Complete DDQ | ✓ | simplified control set in UI |
| See residual band + decision | ✓ | |
| Critical-control forces HIGH | ✓ | engine rule, shown |
| Re-run / amend a submitted IRQ/DDQ | ✗ | no edit, only re-submit creates new state |
| Run AI autopilot (proposes assessment) | ◐ | API only, no UI button |
| Publish assessment report | ✗ | |

### Intelligence (run engines)
| Feature | Status | Notes |
|---|---|---|
| Run Financial DD (Vera) | ✓ | |
| Run Reputation & ESG (Mira) | ✓ | |
| Run Contract terms (Matt) | ✓ | |
| Run Evidence check (Isaac) | ✓ | |
| **Upload a document for analysis** | ✓ | PDF/text, real extraction |
| Isaac auto-parses uploaded SOC 2/ISO | ✓ | verified end-to-end |
| View intel result history per vendor | ✗ | results stored, no history view |
| 4th-party / sub-processor mapping | ◐ | API only |
| 4th-party concentration flag | ◐ | API only |

### Findings / action plan
| Feature | Status | Notes |
|---|---|---|
| Raise finding | ✓ | |
| View action-plan board | ✓ | |
| Advance finding status | ✓ | |
| Edit finding (title, severity, due date) | ✗ | |
| Close / reopen finding | ◐ | advance reaches "closed"; no reopen |
| Assign finding to a user | ✗ | |
| Severity-based SLA shown | ◐ | returned by API, not surfaced in UI |
| Record risk acceptance | ◐ | API only |
| Acceptance expiry tracking | ◐ | field exists, no chase |

### Contract & onboarding
| Feature | Status | Notes |
|---|---|---|
| Generate tiered minimum terms | ◐ | API + engagement detail button |
| Contract gap review | ✗ | terms generated, no gap review logic |
| Track approval conditions to closure | ◐ | via findings |
| Capture certifications | ◐ | API only |
| View certifications per vendor | ◐ | API only |

### Monitoring & lifecycle
| Feature | Status | Notes |
|---|---|---|
| Run monitoring sweep | ✓ | financial |
| Reputation monitoring sweep | ◐ | engine exists; UI sweep is financial |
| ALERT/CRITICAL auto-raises reassessment | ✓ | |
| Evidence-expiry list | ◐ | API only |
| Evidence renewal chase by email | ✗ | no email send |
| Schedule reassessment | ◐ | API only |
| Complete reassessment | ◐ | API only |
| Periodic reassessment auto-fires on cadence | ✗ | no scheduler |
| Delta reassessment (only affected domains) | ✗ | mode flag only, no logic |
| Terminate / offboard engagement | ✓ | 8-step checklist created |
| Work through offboarding steps | ✗ | steps created, no per-step UI |

---

## 3. VRM Reviewer

| Feature | Status | Notes |
|---|---|---|
| Review / sign off engagement | ✗ | no dedicated sign-off endpoint |
| Designate critical vendor (Tier 0) | ✓ | human-only, with reason |
| Remove critical designation | ✗ | |
| Override decision (justified + 2nd approval) | ◐ | API enforces rules; no UI |
| View audit trail | ✓ | |
| Export audit trail | ✗ | stub |
| Version the methodology | ◐ | API only |
| Run intel engines | ✓ | |
| Validate / challenge IRQ scoring | ✗ | no review workflow |
| Review queue of pending sign-offs | ✗ | |

---

## 4. Administrator

| Feature | Status | Notes |
|---|---|---|
| View users | ✗ | no UI/endpoint |
| Create user | ✗ | seeded only |
| Edit user (role, status) | ✗ | |
| Deactivate / delete user | ✗ | |
| View roles & permissions | ✗ | seeded, not exposed |
| Create custom role | ✗ | |
| Edit role permissions | ✗ | |
| Configure email service | ✗ | no settings UI/endpoint |
| Manage AI provider keys | ✗ | env var only |
| Manage integrations / API tokens | ✗ | |
| Manage webhooks | ✗ | model exists, no endpoint |
| RBAC enforced on every route | ✓ | works, just not editable |

---

## 5. Vendor / Supplier

| Feature | Status | Notes |
|---|---|---|
| Vendor self-service login | ◐ | role exists; no portal UI |
| Complete own DDQ (self-serve) | ✗ | no vendor-facing form |
| Submit evidence / upload documents | ◐ | upload API exists; not vendor-scoped UI |
| Submit evidence by email | ✗ | no inbound email |
| View own engagement status | ✗ | no portal |
| Progress own findings/actions | ✗ | |
| Respond to renewal requests | ✗ | |

---

## 6. Dashboards & Reporting (Buyer/VRM/Admin)

| Feature | Status | Notes |
|---|---|---|
| Executive dashboard | ✓ | counts, residual distribution |
| Operational dashboard | ◐ | API; partly shown on main dashboard |
| Risk-posture dashboard | ◐ | API only |
| Risk-score trending over time | ✗ | no time series |
| Portfolio summary (MCP tool) | ◐ | API |
| Critical-vendor list (MCP tool) | ◐ | API |
| Overdue-findings list (MCP tool) | ◐ | API |
| Executive View (natural-language AI Q&A) | ✗ | not built |
| Regulatory report generation | ✗ | |
| Board pack / PDF export | ✗ | |
| Register export (CSV/Excel) | ✗ | |
| Scheduled reports | ✗ | |

---

## 7. Notifications & Communication

| Feature | Status | Notes |
|---|---|---|
| In-app notifications list | ◐ | API; not in UI nav |
| Unread count | ◐ | API |
| Notification on stage transitions | ✓ | written server-side |
| Mark notification read | ✗ | field exists, no endpoint |
| Email notifications (real send) | ✗ | simulation outbox only |
| Inbound email parsing (vendor → evidence) | ✗ | |
| Slack / Teams notifications | ✗ | |
| Digest / scheduled notifications | ✗ | |
| Business contact CC'd on vendor emails | ✗ | no email |

---

## 8. Governance & Assurance

| Feature | Status | Notes |
|---|---|---|
| Tamper-evident hash-chained audit | ✓ | |
| View audit trail | ✓ | |
| Verify chain integrity (one click) | ✓ | |
| Export audit | ✗ | |
| Methodology versioning | ◐ | API only |
| Business impact analysis (BIA) | ◐ | API only |
| Incident management | ◐ | API only |
| Corrective action plan (CAP) board | ◐ | API only |
| Procurement PO straight-through intake | ◐ | API only |

---

## 9. Platform / Production

| Feature | Status | Notes |
|---|---|---|
| Runs offline (SQLite, local analysers) | ✓ | |
| PostgreSQL support | ✓ | via BRO_DB_URL |
| Docker deployment | ✓ | |
| PaaS deployment (Procfile) | ✓ | |
| Interactive API docs (/docs) | ✓ | FastAPI |
| Document file storage | ✓ | local dir (S3 swap is small) |
| DB migrations (Alembic) | ✗ | create-all on boot |
| Observability / metrics / logging | ✗ | |
| Multi-tenancy | ✗ | single-org |
| OCR for scanned PDFs | ✗ | detected, not processed |
| Live LLM providers wired to calibration | ✗ | harness built, not connected |

---

## Summary tally

| Status | Count (approx) | Meaning |
|---|---|---|
| ✓ Present in UI | ~38 | usable today by a person in the browser |
| ◐ API only | ~33 | works via API, no screen yet |
| ✗ Missing | ~62 | not built |

**Reading it:** the **assessment core is strong** (IRQ→DDQ→decision, intel engines,
document upload+Isaac, audit). The biggest clusters of gaps are: **admin UIs**
(users/roles/integrations — almost entirely ✗), the **vendor self-service portal**
(mostly ✗), **editing/CRUD** on existing records (vendor edit, finding edit, etc.),
**real email** (send + inbound), and **reporting/export**. Many ◐ items are one
UI screen away from ✓ since the API already works.
