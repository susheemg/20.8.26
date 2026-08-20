# BRO Risk Oracle — seeded demonstrator

This package includes a fully-populated demonstrator database, `bro_demo.db`, with:

- **100 vendors** — real, well-known names (AWS, Microsoft, Visa, SWIFT, SAP,
  Salesforce, Workday, ServiceNow, Snowflake, S&P Global, Moody's, Accenture, TCS, Equinix,
  and many more), each with realistic HQ country, sector, listing status, ticker, spend band,
  segmentation, substitutability and sponsoring business unit.
- **275 engagements** distributed across the vendors, each with an inherent and residual band,
  annual value, status, service type, and **delivery / receiving locations**.
- **5 critical vendors** (AWS, Microsoft, Visa, SWIFT) and **7 critical engagements**,
  set through the authoritative criticality override.
- Risk attributes on every vendor: cyber (certifications, external rating, breach flag),
  privacy (processing role, DPA, cross-border), resilience (BCP, RTO/RPO, exit plan), ESG,
  three screening checks (sanctions / adverse media / PEP), and insurance.
- ~90 document-backed certificates, ~126 assessments, 51 performance scorecards across three
  quarters, ~40 findings, 5 shared fourth parties (creating concentration hubs), and contracts.

## Run the demonstrator

Point the app at the seeded database via the `BRO_DB_URL` environment variable:

```
BRO_DB_URL=sqlite:///bro_demo.db  uvicorn app.bro_app:app --host 0.0.0.0 --port 8000
```

Or with Docker, set `BRO_DB_URL=sqlite:///bro_demo.db` in the environment.

Sign in with `admin` / `admin`. The Management > Supply Chain tab shows the concentration
network and delivery-location world map; Vendor Register lists all 100 vendors; Vendor 360,
Certificates, Performance, Open Assessments and Contracts are all populated.

## Regenerate

To rebuild the seed from scratch: `python seed_demo.py` (writes `bro_demo.db`).
