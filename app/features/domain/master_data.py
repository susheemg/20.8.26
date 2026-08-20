"""
Master data + ID generation.

- SIC industry taxonomy (division level + major-group names) -> Industry master list.
- UNSPSC segments -> Material Group master list.
- Deterministic, human-readable auto-IDs for every entity:
    VEN-000123  vendor          GRP-00045   vendor group
    ENG-000123  engagement      ASM-000123  assessment
    FND-000123  finding         RMD-000123  remediation
    F4P-000123  fourth party    ART-000123  artefact
    ISS-000123  issue           CON-000123  contract
ID format = <PREFIX>-<zero-padded sequence>. Sequences are per-entity, drawn
from a counters table so they never collide and survive restarts.
"""
from __future__ import annotations

# ---- ID prefixes ----
ID_PREFIX = {
    "vendor": "VEN", "group": "GRP", "engagement": "ENG", "assessment": "ASM",
    "finding": "FND", "remediation": "RMD", "fourth_party": "F4P",
    "artefact": "ART", "issue": "ISS", "contract": "CON",
    "scorecard": "SCD", "review": "PRV", "document": "DOC",
    "incident": "INC", "screening": "SCR", "person": "PER", "monitoring": "MON",
    "sla": "SLA", "perf_issue": "PIS",
    "watchlist_criterion": "WLC", "watchlist_entry": "WLE",
    "watchlist_candidate": "WLK", "supplier_note": "SNT",
}


def format_id(entity: str, seq: int) -> str:
    prefix = ID_PREFIX[entity]
    width = 5 if entity == "group" else 6
    return f"{prefix}-{seq:0{width}d}"


# ---- SIC industry master (US SIC divisions + major group names) ----
# Industry ID == the industry name (per requirement). Code retained for reference.
SIC_INDUSTRIES: list[dict] = [
    {"code": "01", "name": "Agriculture, Forestry & Fishing", "division": "A"},
    {"code": "10", "name": "Mining", "division": "B"},
    {"code": "13", "name": "Oil & Gas Extraction", "division": "B"},
    {"code": "15", "name": "Construction", "division": "C"},
    {"code": "20", "name": "Food & Kindred Products", "division": "D"},
    {"code": "27", "name": "Printing & Publishing", "division": "D"},
    {"code": "28", "name": "Chemicals & Allied Products", "division": "D"},
    {"code": "33", "name": "Primary Metal Industries", "division": "D"},
    {"code": "35", "name": "Industrial & Commercial Machinery & Computer Equipment", "division": "D"},
    {"code": "36", "name": "Electronic & Other Electrical Equipment", "division": "D"},
    {"code": "37", "name": "Transportation Equipment", "division": "D"},
    {"code": "38", "name": "Measuring, Analyzing & Controlling Instruments", "division": "D"},
    {"code": "40", "name": "Railroad Transportation", "division": "E"},
    {"code": "45", "name": "Transportation by Air", "division": "E"},
    {"code": "48", "name": "Communications", "division": "E"},
    {"code": "49", "name": "Electric, Gas & Sanitary Services", "division": "E"},
    {"code": "50", "name": "Wholesale Trade — Durable Goods", "division": "F"},
    {"code": "52", "name": "Retail Trade", "division": "G"},
    {"code": "60", "name": "Depository Institutions (Banking)", "division": "H"},
    {"code": "61", "name": "Non-depository Credit Institutions", "division": "H"},
    {"code": "62", "name": "Security & Commodity Brokers & Dealers", "division": "H"},
    {"code": "63", "name": "Insurance Carriers", "division": "H"},
    {"code": "64", "name": "Insurance Agents, Brokers & Service", "division": "H"},
    {"code": "65", "name": "Real Estate", "division": "H"},
    {"code": "67", "name": "Holding & Other Investment Offices", "division": "H"},
    {"code": "70", "name": "Hotels & Lodging", "division": "I"},
    {"code": "72", "name": "Personal Services", "division": "I"},
    {"code": "73", "name": "Business Services (incl. Software & IT)", "division": "I"},
    {"code": "78", "name": "Motion Pictures", "division": "I"},
    {"code": "80", "name": "Health Services", "division": "I"},
    {"code": "81", "name": "Legal Services", "division": "I"},
    {"code": "82", "name": "Educational Services", "division": "I"},
    {"code": "87", "name": "Engineering, Accounting, Research & Management Services", "division": "I"},
    {"code": "91", "name": "Public Administration — Executive & Legislative", "division": "J"},
    {"code": "99", "name": "Non-classifiable Establishments", "division": "J"},
]

# ---- UNSPSC segment master (top-level segments) -> Material Groups ----
UNSPSC_SEGMENTS: list[dict] = [
    {"code": "10", "name": "Live Plant & Animal Material & Accessories"},
    {"code": "11", "name": "Mineral, Textile & Inedible Plant & Animal Materials"},
    {"code": "12", "name": "Chemicals incl. Bio Chemicals & Gas Materials"},
    {"code": "14", "name": "Paper Materials & Products"},
    {"code": "15", "name": "Fuels, Fuel Additives, Lubricants & Anti-corrosives"},
    {"code": "20", "name": "Mining, Well Drilling Machinery & Accessories"},
    {"code": "23", "name": "Industrial Manufacturing & Processing Machinery"},
    {"code": "25", "name": "Commercial & Military & Private Vehicles"},
    {"code": "30", "name": "Structures, Building & Construction Components"},
    {"code": "39", "name": "Electrical Systems, Lighting & Components"},
    {"code": "40", "name": "Distribution & Conditioning Systems & Equipment"},
    {"code": "41", "name": "Laboratory, Measuring & Observing Equipment"},
    {"code": "43", "name": "Information Technology Broadcasting & Telecommunications"},
    {"code": "44", "name": "Office Equipment, Accessories & Supplies"},
    {"code": "46", "name": "Defense, Law Enforcement & Security & Safety"},
    {"code": "50", "name": "Food, Beverage & Tobacco Products"},
    {"code": "51", "name": "Drugs & Pharmaceutical Products"},
    {"code": "53", "name": "Apparel, Luggage & Personal Care Products"},
    {"code": "55", "name": "Published Products"},
    {"code": "60", "name": "Musical Instruments, Games, Arts & Crafts"},
    {"code": "70", "name": "Farming, Fishing, Forestry & Wildlife Services"},
    {"code": "72", "name": "Building, Facility Construction & Maintenance Services"},
    {"code": "76", "name": "Industrial Cleaning Services"},
    {"code": "77", "name": "Environmental Services"},
    {"code": "78", "name": "Transportation, Storage & Mail Services"},
    {"code": "80", "name": "Management & Business Professionals & Admin Services"},
    {"code": "81", "name": "Engineering, Research & Technology Based Services"},
    {"code": "82", "name": "Editorial, Design, Graphic & Fine Art Services"},
    {"code": "83", "name": "Public Utilities & Public Sector Related Services"},
    {"code": "84", "name": "Financial & Insurance Services"},
    {"code": "85", "name": "Healthcare Services"},
    {"code": "86", "name": "Education & Training Services"},
    {"code": "90", "name": "Travel, Food, Lodging & Entertainment Services"},
    {"code": "91", "name": "Personal & Domestic Services"},
    {"code": "92", "name": "National Defense & Public Order & Security Services"},
    {"code": "93", "name": "Politics & Civic Affairs Services"},
    {"code": "94", "name": "Organizations & Clubs"},
]
