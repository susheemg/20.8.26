"""
Sanctions & AML screening — deterministic engine for the Reputation module.

Models the authoritative-source approach from the AML reference: the primary
ISSUING AUTHORITY is the system of record (OFAC, UN, EU, OFSI are the tier-1 four
that drive most global screening); commercial aggregators only add matching,
aliases and RCAs on top. This engine screens a name (a registered vendor or any
free-text entity) against a watchlist using name-normalisation + fuzzy matching,
and returns sanctions / PEP / adverse-media hits with a Clear / Review / Hit band.

IMPORTANT: the watchlist here is REPRESENTATIVE sample data (fictional entities),
not a live feed. Real registered vendors therefore screen Clear — which is the
correct, safe behaviour. Wire OFAC/UN/EU/OFSI direct downloads (Section 1 of the
reference) to make this live; the matching, banding and audit trail stay the same.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

# ---- Authoritative source catalogue (from the AML reference) ----
AUTHORITATIVE_SOURCES = {
    "tier1_note": ("OFAC, UN, EU and OFSI are the four feeds that drive the vast majority of "
                   "global screening. The issuing authority is always the system of record; "
                   "aggregators add matching and aliases but introduce a copy-lag."),
    "sanctions": [
        {"jurisdiction": "United States", "authority": "OFAC (US Treasury)",
         "lists": "SDN; Consolidated Non-SDN (SSI, FSE, NS-MBS)", "tier1": True,
         "access": "sanctionssearch.ofac.treas.gov — XML/CSV/JSON"},
        {"jurisdiction": "United Nations", "authority": "UN Security Council",
         "lists": "UNSC Consolidated List", "tier1": True, "access": "scsanctions.un.org — XML"},
        {"jurisdiction": "European Union", "authority": "EU Council / DG FISMA",
         "lists": "Consolidated Financial Sanctions List (CFSP)", "tier1": True,
         "access": "EU Financial Sanctions Files portal — XML"},
        {"jurisdiction": "United Kingdom", "authority": "OFSI (HM Treasury)",
         "lists": "UK Sanctions List; UK Consolidated List", "tier1": True,
         "access": "gov.uk OFSI — CSV/ODT/XML"},
        {"jurisdiction": "Switzerland", "authority": "SECO", "lists": "Swiss sanctions (SESAM)",
         "tier1": False, "access": "seco.admin.ch — XML"},
        {"jurisdiction": "Canada", "authority": "GAC / OSFI", "lists": "SEMA, JVCFOA, UN regs",
         "tier1": False, "access": "international.gc.ca — XML"},
        {"jurisdiction": "Australia", "authority": "DFAT", "lists": "Consolidated List",
         "tier1": False, "access": "dfat.gov.au — XLS/XML"},
        {"jurisdiction": "Singapore", "authority": "MAS", "lists": "Targeted Financial Sanctions",
         "tier1": False, "access": "mas.gov.sg"},
        {"jurisdiction": "UAE", "authority": "Executive Office for AML/CTF",
         "lists": "UAE Local Terrorist List; UN adoption", "tier1": False, "access": "uaeiec.gov.ae"},
    ],
    "pep_anchors": [
        "FATF Recommendations 12 & 22 (PEP definition baseline)",
        "EU 4th/5th/6th AML Directives + EU AML Regulation / AMLA regime",
        "Wolfsberg Group guidance (PEP definitions, RCA treatment)",
    ],
    "pep_underlying": [
        "Government & parliamentary registries (cabinet, electoral commissions, gazettes)",
        "State-owned enterprise board/officer disclosures",
        "International-organisation senior officials (IMF, World Bank, UN bodies)",
        "Judiciary, military and central-bank senior appointments",
        "Family members & close associates (RCAs) — derived analytically, quality varies",
    ],
    "adverse": [
        "Regulatory enforcement — FCA, SEC/FINRA, BaFin, MAS, FINMA registers",
        "FATF High-Risk Jurisdictions (blacklist) & Increased Monitoring (grey list)",
        "Multilateral debarment — World Bank, ADB, EBRD, IADB, AfDB",
        "Law enforcement — Interpol Red Notices, Europol, national wanted lists",
        "Corruption/fraud — DOJ/SFO enforcement; OFAC enforcement actions",
        "Court & insolvency / disqualified-director registers",
        "Beneficial ownership & non-cooperative tax-jurisdiction lists",
    ],
    "provider_checklist": [
        "Primary-issuer ingestion (OFAC/UN/EU/OFSI direct, not second-hand)",
        "Refresh cadence (target intraday for sanctions)",
        "PEP methodology (FATF/EU/Wolfsberg basis, RCA depth, declassification)",
        "Matching quality (fuzzy, transliteration, secondary identifiers, FP controls)",
        "Adverse-media scope (sources, languages, NLP/sentiment, structuring)",
        "Auditability (match-decision logging, point-in-time list reconstruction)",
        "Data lineage & residency (sub-processors, hosting, PII processing location)",
        "Coverage gaps (jurisdictions, vessels/aircraft/crypto, beneficial ownership)",
    ],
}

# ---- Representative watchlist (FICTIONAL sample — not a live feed) ----
# category: sanction | pep | adverse
_WATCHLIST = [
    {"id": "OFAC-SDN-0001", "name": "Volkov Industrial OAO", "category": "sanction",
     "source": "OFAC", "list": "SDN", "program": "RUSSIA-EO14024", "country": "RU",
     "entity_type": "entity", "aliases": ["Volkov Industries", "OAO Volkov Industrial"]},
    {"id": "OFAC-SDN-0002", "name": "Crimson Star Shipping Ltd", "category": "sanction",
     "source": "OFAC", "list": "SDN", "program": "DPRK", "country": "KP",
     "entity_type": "entity", "aliases": ["Crimson Star Maritime", "Red Star Shipping"]},
    {"id": "UN-CL-0007", "name": "Al-Marwan Financial Network", "category": "sanction",
     "source": "UN", "list": "UNSC Consolidated", "program": "ISIL (Da'esh) & Al-Qaida",
     "country": "SY", "entity_type": "entity", "aliases": ["Marwan Finance"]},
    {"id": "EU-CFSP-0042", "name": "Petrov Konstantin Andreevich", "category": "sanction",
     "source": "EU", "list": "CFSP Consolidated", "program": "Annex I (Ukraine sovereignty)",
     "country": "RU", "entity_type": "individual", "dob": "1968-03-12",
     "aliases": ["Konstantin Petrov", "K. A. Petrov"]},
    {"id": "OFSI-0019", "name": "Saber Holdings PLC", "category": "sanction",
     "source": "OFSI", "list": "UK Consolidated", "program": "Counter-Terrorism",
     "country": "GB", "entity_type": "entity", "aliases": ["Saber Group", "Saber Investments"]},
    # PEPs (representative)
    {"id": "PEP-0001", "name": "Adaeze Okonkwo", "category": "pep",
     "source": "PEP (gov registry)", "list": "Cabinet minister", "program": "Domestic PEP",
     "country": "NG", "entity_type": "individual", "aliases": ["A. Okonkwo"],
     "note": "Minister of Finance (representative)"},
    {"id": "PEP-0002", "name": "Rashid Al-Habib", "category": "pep",
     "source": "PEP (SOE disclosure)", "list": "SOE board", "program": "Foreign PEP",
     "country": "AE", "entity_type": "individual", "aliases": ["R. Al Habib"],
     "note": "Chair, state energy company (representative)"},
    {"id": "PEP-0003", "name": "Northbridge Sovereign Wealth Trust", "category": "pep",
     "source": "PEP (IO/SOE)", "list": "State-controlled entity", "program": "SOE",
     "country": "SG", "entity_type": "entity", "aliases": ["Northbridge SWF"]},
    # Adverse media / enforcement (representative)
    {"id": "ADV-0001", "name": "Helios Capital Partners", "category": "adverse",
     "source": "Regulatory enforcement (FCA)", "list": "Enforcement action", "program": "AML failings",
     "country": "GB", "entity_type": "entity", "aliases": ["Helios Capital"],
     "note": "£12m fine for AML control failings (representative)"},
    {"id": "ADV-0002", "name": "Meridian Logistics Group", "category": "adverse",
     "source": "Multilateral debarment (World Bank)", "list": "Debarred", "program": "Fraud/corruption",
     "country": "BR", "entity_type": "entity", "aliases": ["Meridian Logistica"],
     "note": "3-year debarment (representative)"},
    {"id": "ADV-0003", "name": "Dmitri Sokolov", "category": "adverse",
     "source": "Law enforcement (Interpol)", "list": "Red Notice", "program": "Financial crime",
     "country": "RU", "entity_type": "individual", "aliases": ["D. Sokolov"]},
]

_SUFFIXES = {"ltd", "limited", "inc", "incorporated", "llc", "plc", "gmbh", "ag", "sa", "bv",
             "nv", "co", "corp", "corporation", "pte", "pty", "srl", "sarl", "oao", "ojsc",
             "pjsc", "llp", "lp", "kg", "spa"}


def _norm(s: str) -> str:
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
            if t and t not in _SUFFIXES]
    return " ".join(toks)


def _score(a: str, b: str) -> int:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return round(100 * (0.45 * seq + 0.55 * jac))


def _disambiguate(base: int, e: dict, dob: str | None, nationality: str | None,
                  country: str | None) -> tuple[int, list[str]]:
    """Apply secondary identifiers (DOB, nationality/country) to refine a name match.
    Returns (adjusted_score, notes). Cuts false positives and confirms true matches."""
    score = base
    notes = []
    is_individual = (e.get("entity_type") == "individual")
    e_dob = e.get("dob")
    e_nat = (e.get("nationality") or e.get("country"))
    if is_individual and dob and e_dob:
        if dob[:10] == e_dob[:10]:
            score = min(100, score + 6); notes.append("DOB matches")
        else:
            score = max(0, score - 25); notes.append("DOB differs — likely false positive")
    if (nationality or country) and e_nat:
        q = (nationality or country).upper()
        if q == e_nat.upper():
            score = min(100, score + 4); notes.append("nationality matches")
        else:
            score = max(0, score - 8); notes.append("nationality differs")
    return score, notes


def _match_entries(name: str, entries, country=None, dob=None, nationality=None) -> list[dict]:
    hits = []
    for e in entries:
        base = _score(name, e["name"])
        for al in e.get("aliases", []):
            base = max(base, _score(name, al))
        score, notes = _disambiguate(base, e, dob, nationality, country)
        if score >= 80:
            note = e.get("note")
            disamb = "; ".join(notes)
            hits.append({
                "watchlist_id": e.get("id"), "matched_name": e["name"], "category": e["category"],
                "source": e["source"], "list": e.get("list"), "program": e.get("program"),
                "country": e.get("country"), "nationality": e.get("nationality"),
                "entity_type": e.get("entity_type"), "dob": e.get("dob"),
                "note": (note + (" · " + disamb if disamb else "")) if note else (disamb or None),
                "live": bool(e.get("live")),
                "score": score, "strength": "strong" if score >= 90 else "possible",
            })
    hits.sort(key=lambda h: -h["score"])
    return hits


def screen_name(name: str, country: str | None = None, dob: str | None = None,
                nationality: str | None = None, extra: list | None = None) -> dict:
    """Screen a name against the representative watchlist + any live/ingested entries
    (`extra`, e.g. OFSI rows from the DB), with DOB/nationality disambiguation."""
    entries = list(_WATCHLIST) + list(extra or [])
    hits = _match_entries(name, entries, country, dob, nationality)
    has_sanction_strong = any(h["category"] == "sanction" and h["strength"] == "strong" for h in hits)
    has_any_strong = any(h["strength"] == "strong" for h in hits)
    if has_sanction_strong:
        band = "Hit"
    elif has_any_strong or hits:
        band = "Review"
    else:
        band = "Clear"
    live_sources = sorted({h["source"] for h in hits if h.get("live")})
    return {
        "name": name, "country": country, "dob": dob, "nationality": nationality,
        "band": band, "hit_count": len(hits), "hits": hits,
        "sources_screened": ["OFAC", "UN", "EU", "OFSI", "PEP", "Adverse media"],
        "live_sources": live_sources,
        "representative": not bool(extra),
        "screened_at": datetime.now(timezone.utc).isoformat(),
    }


def band_tone(band: str) -> str:
    return {"Hit": "crit", "Review": "warn", "Clear": "ok"}.get(band, "mute")


def sources() -> dict:
    return AUTHORITATIVE_SOURCES


# ---- OFSI live feed (UK consolidated list, free CSV) ----
OFSI_URL = ("https://ofsistorage.blob.core.windows.net/publishlive/2022format/"
            "ConList.csv")  # OFSI consolidated list, CSV format


def fetch_ofsi(url: str | None = None, timeout: int = 30) -> str:
    """Download the OFSI consolidated-list CSV. Requires network egress to the OFSI
    host (allowlist it on the deployment). Returns raw CSV text."""
    import httpx
    return httpx.get(url or OFSI_URL, timeout=timeout, follow_redirects=True).raise_for_status().text


def load_ofsi_csv(text: str) -> list[dict]:
    """Parse the OFSI consolidated-list CSV into normalised watchlist entries.

    OFSI publishes one row per name; rows sharing a Group ID are the same target
    (primary name + AKA aliases). We group by Group ID, take the primary-name row as
    the entry and fold AKA rows in as aliases, carrying DOB / nationality / regime.
    """
    import csv
    import io
    lines = text.splitlines()
    # locate the header row (OFSI prepends a date/title preamble)
    hdr_idx = 0
    for i, ln in enumerate(lines[:8]):
        if "Group ID" in ln and ("Name 6" in ln or "Name 1" in ln):
            hdr_idx = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[hdr_idx:])))
    groups: dict[str, dict] = {}
    for row in reader:
        gid = (row.get("Group ID") or "").strip()
        if not gid:
            continue
        name = " ".join((row.get(f"Name {n}") or "").strip() for n in range(1, 7)).split()
        full = " ".join(name)
        if not full:
            continue
        alias_type = (row.get("Alias Type") or "").strip().lower()
        gtype = (row.get("Group Type") or "").strip().lower()
        g = groups.get(gid)
        if g is None:
            g = groups[gid] = {
                "id": f"OFSI-{gid}", "name": full, "aliases": [], "category": "sanction",
                "source": "OFSI (live)", "list": "UK Sanctions List",
                "program": (row.get("Regime") or "").strip() or None,
                "country": (row.get("Nationality") or row.get("Country") or "").strip()[:2].upper() or None,
                "nationality": (row.get("Nationality") or "").strip() or None,
                "entity_type": "individual" if "individual" in gtype else "entity",
                "dob": (row.get("DOB") or "").strip() or None,
                "live": True,
            }
        if alias_type.startswith("primary"):
            g["name"] = full
        elif full and full != g["name"] and full not in g["aliases"]:
            g["aliases"].append(full)
    return list(groups.values())



# ---- additional issuer feeds: OFAC (CSV), UN (XML), EU (XML) ----
FEED_URLS = {
    "OFSI": OFSI_URL,
    "OFAC": "https://www.treasury.gov/ofac/downloads/sdn.csv",
    "UN":   "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
    "EU":   "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content",
}


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def load_ofac_csv(text: str) -> list[dict]:
    """Parse the OFAC SDN.csv (headerless, positional). Columns:
    ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage,
    GRT, Vess_flag, Vess_owner, Remarks. DOB/nationality often live in Remarks."""
    import csv
    import io
    import re as _re
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 4:
            continue
        clean = [("" if c.strip() == "-0-" else c.strip()) for c in row]
        ent_num, name, stype, program = clean[0], clean[1], clean[2], clean[3]
        if not name or not ent_num.strip().isdigit():
            continue
        remarks = clean[11] if len(clean) > 11 else ""
        dob = None
        m = _re.search(r"DOB\s+([0-9]{1,2}\s+\w+\s+[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", remarks)
        if m:
            dob = m.group(1)
        nat = None
        mn = _re.search(r"[Nn]ationality\s+([A-Za-z ,]+?)(?:;|$)", remarks)
        if mn:
            nat = mn.group(1).strip()
        out.append({
            "id": f"OFAC-{ent_num.strip()}", "name": name, "aliases": [], "category": "sanction",
            "source": "OFAC (live)", "list": "SDN", "program": program or None,
            "country": None, "nationality": nat,
            "entity_type": "individual" if "individual" in stype.lower() else "entity",
            "dob": dob, "live": True,
        })
    return out


def load_un_xml(text: str) -> list[dict]:
    """Parse the UN Security Council consolidated list XML (individuals + entities)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    out = []

    def _txt(node, names):
        for ch in node:
            if _xml_local(ch.tag) in names and (ch.text or "").strip():
                return ch.text.strip()
        return None

    for el in root.iter():
        local = _xml_local(el.tag)
        if local not in ("INDIVIDUAL", "ENTITY"):
            continue
        parts = []
        for nm in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME"):
            v = _txt(el, {nm})
            if v:
                parts.append(v)
        full = " ".join(parts).strip()
        if not full:
            continue
        aliases = []
        dob = None
        nat = None
        ref = None
        for ch in el:
            cl = _xml_local(ch.tag)
            if cl in ("REFERENCE_NUMBER", "DATAID") and (ch.text or "").strip() and not ref:
                ref = ch.text.strip()
            if cl.endswith("ALIAS"):
                a = _txt(ch, {"ALIAS_NAME"})
                if a:
                    aliases.append(a)
            if cl.endswith("DATE_OF_BIRTH"):
                dob = _txt(ch, {"DATE", "YEAR", "FROM_YEAR"}) or dob
            if cl == "NATIONALITY":
                nat = _txt(ch, {"VALUE"}) or nat
        out.append({
            "id": f"UN-{ref or full[:20]}", "name": full, "aliases": aliases,
            "category": "sanction", "source": "UN (live)", "list": "UNSC Consolidated",
            "program": _txt(el, {"UN_LIST_TYPE"}), "country": None, "nationality": nat,
            "entity_type": "individual" if local == "INDIVIDUAL" else "entity",
            "dob": dob, "live": True,
        })
    return out


def load_eu_xml(text: str) -> list[dict]:
    """Parse the EU consolidated financial sanctions list XML (namespace-tolerant)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    out = []
    for el in root.iter():
        if _xml_local(el.tag) != "sanctionEntity":
            continue
        ref = el.get("euReferenceNumber") or el.get("logicalId") or ""
        name = None
        aliases = []
        etype = "entity"
        dob = None
        nat = None
        prog = el.get("regulationProgramme") or el.get("programme")
        for ch in el.iter():
            cl = _xml_local(ch.tag)
            if cl == "subjectType":
                code = (ch.get("classificationCode") or "").upper()
                etype = "individual" if code == "P" else "entity"
            elif cl == "nameAlias":
                whole = ch.get("wholeName") or " ".join(
                    filter(None, [ch.get("firstName"), ch.get("middleName"), ch.get("lastName")]))
                whole = (whole or "").strip()
                if whole:
                    if name is None:
                        name = whole
                    elif whole not in aliases:
                        aliases.append(whole)
            elif cl == "birthdate":
                dob = ch.get("birthdate") or ch.get("year") or dob
            elif cl == "citizenship":
                nat = ch.get("countryDescription") or ch.get("region") or nat
        if not name:
            continue
        out.append({
            "id": f"EU-{ref or name[:20]}", "name": name, "aliases": aliases,
            "category": "sanction", "source": "EU (live)", "list": "CFSP Consolidated",
            "program": prog, "country": None, "nationality": nat,
            "entity_type": etype, "dob": dob, "live": True,
        })
    return out


FEED_LOADERS = {
    "OFSI": load_ofsi_csv,
    "OFAC": load_ofac_csv,
    "UN": load_un_xml,
    "EU": load_eu_xml,
}


def fetch_feed(source: str, url: str | None = None, timeout: int = 30) -> str:
    import httpx
    target = url or FEED_URLS[source]
    return httpx.get(target, timeout=timeout, follow_redirects=True).raise_for_status().text


def load_feed(source: str, text: str) -> list[dict]:
    loader = FEED_LOADERS.get(source)
    if not loader:
        raise ValueError(f"unknown feed source {source}")
    return loader(text)
