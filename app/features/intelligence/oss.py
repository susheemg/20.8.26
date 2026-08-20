"""Open-Source Software register, tagged to vendor engagements.

Deterministic-first (DQ-01): parsing, identifier normalisation, licence
classification and risk scoring are rule-based and reproducible — the same SBOM
always yields the same result. Populated from vendor-supplied SBOMs (CycloneDX +
SPDX JSON) and tagged: component -> SBOM -> engagement -> vendor, so blast-radius
and concentration questions are answerable in one hop. Threat-intel here is a
seeded, illustrative library standing in for live OSV/NVD/GHSA/KEV/EPSS feeds.
"""
from __future__ import annotations
import hashlib, json
from datetime import date, timedelta

# ---------------- licence policy (LIC-02) ----------------
LICENCE_POLICY = {
    "prohibited": {"AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0", "BUSL-1.1", "Commons-Clause"},
    "restricted": {"GPL-2.0", "GPL-2.0-only", "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
                   "LGPL-2.1", "LGPL-3.0", "MPL-2.0", "EPL-2.0", "CDDL-1.0", "CC-BY-NC-4.0"},
    "allowed": {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense",
                "Zlib", "0BSD", "PostgreSQL", "Python-2.0", "CC0-1.0", "BSL-1.0", "OpenSSL"},
}
_BANDS = [(25, "LOW"), (45, "MODERATE"), (65, "ELEVATED"), (85, "HIGH"), (101, "CRITICAL")]


def band(score):
    for hi, b in _BANDS:
        if score < hi:
            return b
    return "CRITICAL"


def classify_licence(lic):
    if not lic or lic.upper() in ("NOASSERTION", "NONE", "UNKNOWN"):
        return "review"
    tok = lic.replace("(", " ").replace(")", " ").split()
    for cat in ("prohibited", "restricted", "allowed"):
        for t in tok:
            if t in LICENCE_POLICY[cat]:
                return cat
    return "review"


# ---------------- seeded component + vulnerability intel ----------------
# (name, ecosystem, licence, [versions...])  — versions[0] is the "current/safe" pick
_LIB = [
    ("log4j-core", "maven", "Apache-2.0", ["2.21.1", "2.14.1"]),
    ("spring-core", "maven", "Apache-2.0", ["6.1.5", "5.3.17"]),
    ("jackson-databind", "maven", "Apache-2.0", ["2.16.1", "2.9.10"]),
    ("commons-text", "maven", "Apache-2.0", ["1.11.0", "1.9"]),
    ("tomcat-embed-core", "maven", "Apache-2.0", ["10.1.19"]),
    ("netty-handler", "maven", "Apache-2.0", ["4.1.107"]),
    ("guava", "maven", "Apache-2.0", ["33.1.0"]),
    ("bcprov-jdk18on", "maven", "MIT", ["1.77"]),
    ("snakeyaml", "maven", "Apache-2.0", ["2.2", "1.30"]),
    ("mysql-connector-j", "maven", "GPL-2.0", ["8.3.0"]),
    ("postgresql", "maven", "BSD-2-Clause", ["42.7.3"]),
    ("openssl", "generic", "Apache-2.0", ["3.2.1", "3.0.0"]),
    ("zlib", "generic", "Zlib", ["1.3.1"]),
    ("curl", "generic", "MIT", ["8.6.0", "7.86.0"]),
    ("libxml2", "generic", "MIT", ["2.12.5"]),
    ("openssh", "generic", "BSD-3-Clause", ["9.6"]),
    ("lodash", "npm", "MIT", ["4.17.21", "4.17.15"]),
    ("axios", "npm", "MIT", ["1.6.7", "0.21.0"]),
    ("express", "npm", "MIT", ["4.18.3"]),
    ("react", "npm", "MIT", ["18.2.0"]),
    ("vue", "npm", "MIT", ["3.4.21"]),
    ("minimist", "npm", "MIT", ["1.2.8", "1.2.5"]),
    ("node-fetch", "npm", "MIT", ["3.3.2", "2.6.6"]),
    ("moment", "npm", "MIT", ["2.30.1"]),
    ("jquery", "npm", "MIT", ["3.7.1", "3.4.0"]),
    ("bootstrap", "npm", "MIT", ["5.3.3"]),
    ("ws", "npm", "MIT", ["8.16.0"]),
    ("semver", "npm", "ISC", ["7.6.0"]),
    ("requests", "pypi", "Apache-2.0", ["2.31.0"]),
    ("urllib3", "pypi", "MIT", ["2.2.1", "1.26.4"]),
    ("pyyaml", "pypi", "MIT", ["6.0.1"]),
    ("cryptography", "pypi", "Apache-2.0", ["42.0.5", "3.2"]),
    ("pillow", "pypi", "MIT", ["10.2.0", "9.0.0"]),
    ("numpy", "pypi", "BSD-3-Clause", ["1.26.4"]),
    ("flask", "pypi", "BSD-3-Clause", ["3.0.2"]),
    ("django", "pypi", "BSD-3-Clause", ["5.0.3", "3.2.0"]),
    ("certifi", "pypi", "MPL-2.0", ["2024.2.2"]),
    ("paramiko", "pypi", "LGPL-2.1", ["3.4.0"]),
    ("golang.org/x/crypto", "golang", "BSD-3-Clause", ["0.21.0", "0.16.0"]),
    ("golang.org/x/net", "golang", "BSD-3-Clause", ["0.22.0"]),
    ("github.com/gin-gonic/gin", "golang", "MIT", ["1.9.1"]),
    ("serde", "cargo", "MIT", ["1.0.197"]),
    ("tokio", "cargo", "MIT", ["1.36.0"]),
    ("openssl-sys", "cargo", "MIT", ["0.9.101"]),
    ("ghostscript", "generic", "AGPL-3.0", ["10.02.1"]),
    ("readline", "generic", "GPL-3.0", ["8.2"]),
    ("ffmpeg", "generic", "LGPL-2.1", ["6.1"]),
    ("mongodb-driver", "maven", "SSPL-1.0", ["4.11.1"]),
    ("protobuf-java", "maven", "BSD-3-Clause", ["3.25.3"]),
    ("kafka-clients", "maven", "Apache-2.0", ["3.7.0"]),
]
# vulnerabilities keyed by "name@version"
_VULNS = {
    "log4j-core@2.14.1": [("CVE-2021-44228", "GHSA", 10.0, 0.975, True,
                           "Log4Shell — JNDI remote code execution in Log4j 2.")],
    "spring-core@5.3.17": [("CVE-2022-22965", "NVD", 9.8, 0.94, True,
                            "Spring4Shell — RCE via data binding on JDK 9+.")],
    "commons-text@1.9": [("CVE-2022-42889", "NVD", 9.8, 0.88, True,
                          "Text4Shell — RCE via StringSubstitutor interpolation.")],
    "jackson-databind@2.9.10": [("CVE-2020-36518", "GHSA", 7.5, 0.42, False,
                                 "Deeply nested JSON causes denial of service.")],
    "snakeyaml@1.30": [("CVE-2022-1471", "GHSA", 9.8, 0.61, False,
                        "Unsafe deserialization via SnakeYAML Constructor.")],
    "openssl@3.0.0": [("CVE-2022-3602", "NVD", 7.5, 0.12, False,
                       "X.509 email address 4-byte buffer overflow (punycode).")],
    "curl@7.86.0": [("CVE-2023-38545", "NVD", 9.8, 0.55, True,
                     "SOCKS5 heap buffer overflow in curl.")],
    "lodash@4.17.15": [("CVE-2020-8203", "GHSA", 7.4, 0.21, False,
                        "Prototype pollution in lodash.")],
    "axios@0.21.0": [("CVE-2021-3749", "GHSA", 7.5, 0.18, False,
                      "Regular-expression denial of service (ReDoS) in axios.")],
    "minimist@1.2.5": [("CVE-2021-44906", "GHSA", 9.8, 0.30, False,
                        "Prototype pollution in minimist.")],
    "node-fetch@2.6.6": [("CVE-2022-0235", "GHSA", 6.1, 0.09, False,
                          "node-fetch leaks sensitive headers on redirect.")],
    "jquery@3.4.0": [("CVE-2020-11022", "GHSA", 6.1, 0.14, False,
                      "Cross-site scripting via jQuery.htmlPrefilter.")],
    "urllib3@1.26.4": [("CVE-2021-33503", "GHSA", 7.5, 0.20, False,
                        "ReDoS in urllib3 URL parsing.")],
    "cryptography@3.2": [("CVE-2020-25659", "GHSA", 5.9, 0.06, False,
                          "Bleichenbacher timing oracle in RSA decryption.")],
    "pillow@9.0.0": [("CVE-2022-22817", "GHSA", 9.8, 0.33, False,
                      "PIL.ImageMath.eval arbitrary code execution.")],
    "django@3.2.0": [("CVE-2021-35042", "NVD", 9.8, 0.47, True,
                     "SQL injection via QuerySet.order_by.")],
    "golang.org/x/crypto@0.16.0": [("CVE-2023-48795", "GHSA", 5.9, 0.40, False,
                                    "Terrapin — SSH transcript truncation attack.")],
}
_EOL = {"log4j-core@2.14.1", "spring-core@5.3.17", "jackson-databind@2.9.10",
        "openssl@3.0.0", "django@3.2.0", "minimist@1.2.5"}
_POPULAR = ["log4j-core", "openssl", "jackson-databind", "spring-core", "lodash",
            "axios", "requests", "urllib3", "guava", "netty-handler", "snakeyaml", "curl"]


def _h(*p):
    return int(hashlib.sha1("|".join(map(str, p)).encode()).hexdigest(), 16)


def _r(*p):
    return (_h(*p) % 100000) / 100000.0


def _coord(name, version, purl=None):
    return purl or f"{name}@{version or '?'}"


# ---------------- SBOM parsing (STD-01/02/05) ----------------
def parse_sbom(obj):
    """Parse a CycloneDX or SPDX JSON SBOM into a normalised structure. Deterministic."""
    if not isinstance(obj, dict):
        raise ValueError("SBOM must be a JSON object")
    if obj.get("bomFormat") == "CycloneDX" or "components" in obj:
        return _parse_cyclonedx(obj)
    if "spdxVersion" in obj or "packages" in obj:
        return _parse_spdx(obj)
    raise ValueError("Unrecognised SBOM format (expected CycloneDX or SPDX JSON)")


def _lic_from_cdx(c):
    for l in (c.get("licenses") or []):
        if isinstance(l, dict):
            if l.get("expression"):
                return l["expression"]
            li = l.get("license") or {}
            return li.get("id") or li.get("name")
    return None


def _parse_cyclonedx(obj):
    comps = []
    for c in (obj.get("components") or []):
        h = None
        for hh in (c.get("hashes") or []):
            if hh.get("alg", "").upper().startswith("SHA"):
                h = hh.get("content"); break
        comps.append({"name": c.get("name"), "version": c.get("version"),
                      "purl": c.get("purl"), "cpe": c.get("cpe"), "hash": h,
                      "licence": _lic_from_cdx(c),
                      "supplier": (c.get("supplier") or {}).get("name") or c.get("publisher"),
                      "dep_type": "direct"})
    meta = obj.get("metadata") or {}
    return {"fmt": "cyclonedx", "spec_version": obj.get("specVersion"),
            "sbom_type": (meta.get("lifecycles") or [{}])[0].get("phase") if meta.get("lifecycles") else None,
            "author": bool((meta.get("authors") or meta.get("tools"))),
            "timestamp": meta.get("timestamp"), "components": comps}


def _parse_spdx(obj):
    comps = []
    for p in (obj.get("packages") or []):
        purl = None
        for ref in (p.get("externalRefs") or []):
            if ref.get("referenceType") in ("purl", "package-url"):
                purl = ref.get("referenceLocator")
        h = None
        for ck in (p.get("checksums") or []):
            if (ck.get("algorithm") or "").upper().startswith("SHA"):
                h = ck.get("checksumValue"); break
        lic = p.get("licenseConcluded")
        if not lic or lic == "NOASSERTION":
            lic = p.get("licenseDeclared")
        comps.append({"name": p.get("name"), "version": p.get("versionInfo"),
                      "purl": purl, "cpe": None, "hash": h, "licence": lic,
                      "supplier": (p.get("supplier") or "").replace("Organization:", "").strip() or None,
                      "dep_type": "direct"})
    ci = obj.get("creationInfo") or {}
    return {"fmt": "spdx", "spec_version": obj.get("spdxVersion"),
            "sbom_type": None, "author": bool(ci.get("creators")),
            "timestamp": ci.get("created"), "components": comps}


def ntia_assess(parsed):
    """NTIA Minimum Elements coverage (STD-04): supplier, name, version, identifier,
    dependency, author, timestamp."""
    comps = parsed["components"] or []
    n = max(1, len(comps))
    have_name = sum(1 for c in comps if c.get("name")) / n
    have_ver = sum(1 for c in comps if c.get("version")) / n
    have_id = sum(1 for c in comps if c.get("purl")) / n
    have_sup = sum(1 for c in comps if c.get("supplier")) / n
    doc = (1.0 if parsed.get("author") else 0.0) + (1.0 if parsed.get("timestamp") else 0.0)
    score = round((have_name + have_ver + have_id + have_sup + (doc / 2) + 1.0) / 6 * 100, 1)  # +1 = dependency present
    label = "complete" if score >= 90 else "partial" if score >= 60 else "minimal"
    return score, label


# ---------------- scoring (deterministic) ----------------
def component_risk(licence_category, maintenance, vulns):
    base = 8
    for v in vulns:
        if (v.get("vex_status") or "affected") in ("not_affected", "fixed"):
            continue
        if v.get("kev"):
            s = 92
        else:
            c = v.get("cvss") or 0
            s = 90 if c >= 9 else 66 if c >= 7 else 44 if c >= 4 else 22 if c > 0 else 0
        base = max(base, s)
    if licence_category == "prohibited":
        base += 18
    elif licence_category == "restricted":
        base += 8
    elif licence_category == "review":
        base += 5
    if maintenance == "eol":
        base += 15
    elif maintenance == "unmaintained":
        base += 10
    score = min(100, base)
    return float(score), band(score)


def severity_of(cvss, kev):
    if kev:
        return "KEV"
    if cvss is None:
        return "UNKNOWN"
    return "CRITICAL" if cvss >= 9 else "HIGH" if cvss >= 7 else "MEDIUM" if cvss >= 4 else "LOW"


# ---------------- DB service ----------------
def _upsert_component(s, name, version, purl, cpe, hsh, licence, supplier, ecosystem):
    from app.features.domain.registry_models import OssComponent
    key = _coord(name, version, purl)
    comp = s.query(OssComponent).filter_by(key=key).first()
    if comp:
        return comp
    cat = classify_licence(licence)
    maint = "eol" if f"{name}@{version}" in _EOL else "healthy"
    comp = OssComponent(key=key, name=name, version=version, ecosystem=ecosystem, purl=purl,
                        cpe=cpe, hash=hsh, licence=licence, licence_category=cat, supplier=supplier,
                        maintenance=maint, first_seen=date.today().isoformat())
    s.add(comp); s.flush()
    # attach seeded intel for this exact coordinate
    for (cve, src, cvss, epss, kev, summ) in _VULNS.get(f"{name}@{version}", []):
        from app.features.domain.registry_models import OssVuln
        s.add(OssVuln(component_id=comp.id, cve=cve, source=src, cvss=cvss, epss=epss,
                      kev=kev, severity=severity_of(cvss, kev), summary=summ))
    s.flush()
    _score_component(s, comp)
    return comp


def _score_component(s, comp):
    from app.features.domain.registry_models import OssVuln
    vulns = [{"cvss": v.cvss, "kev": v.kev, "vex_status": v.vex_status}
             for v in s.query(OssVuln).filter_by(component_id=comp.id).all()]
    comp.risk_score, comp.risk_band = component_risk(comp.licence_category, comp.maintenance, vulns)


def ingest_sbom(s, engagement_id, product, product_version, sbom_obj,
                channel="upload", store_raw=True):
    """Parse + store a vendor SBOM, tag its components to the engagement, supersede prior."""
    from app.features.domain.registry_models import OssSbom, OssUsage, EngagementRecord
    eng = s.query(EngagementRecord).filter_by(engagement_id=engagement_id).first()
    if not eng:
        raise ValueError(f"unknown engagement {engagement_id}")
    parsed = parse_sbom(sbom_obj)
    ntia, qlabel = ntia_assess(parsed)
    # supersede prior SBOMs for same engagement + product + version
    for prior in s.query(OssSbom).filter_by(engagement_id=engagement_id, product=product,
                                            product_version=product_version, superseded=False).all():
        prior.superseded = True
    sb = OssSbom(engagement_id=engagement_id, vendor_id=eng.vendor_id, product=product,
                 product_version=product_version, fmt=parsed["fmt"], spec_version=parsed["spec_version"],
                 sbom_type=parsed.get("sbom_type"), component_count=len(parsed["components"]),
                 ntia_score=ntia, quality_label=qlabel, source_channel=channel,
                 raw_json=(json.dumps(sbom_obj)[:200000] if store_raw else None),
                 created_at=date.today().isoformat())
    s.add(sb); s.flush()
    for c in parsed["components"]:
        if not c.get("name"):
            continue
        eco = None
        if c.get("purl") and c["purl"].startswith("pkg:"):
            eco = c["purl"][4:].split("/")[0]
        comp = _upsert_component(s, c["name"], c.get("version"), c.get("purl"), c.get("cpe"),
                                 c.get("hash"), c.get("licence"), c.get("supplier"), eco)
        s.add(OssUsage(component_id=comp.id, sbom_id=sb.id, engagement_id=engagement_id,
                       vendor_id=eng.vendor_id, dep_type=c.get("dep_type", "direct"),
                       scope=c.get("scope", "runtime"), depth=c.get("depth", 0)))
    s.flush()
    recompute_counts(s)
    return {"sbom_id": sb.id, "components": len(parsed["components"]), "ntia": ntia,
            "quality": qlabel, "fmt": parsed["fmt"], "spec_version": parsed["spec_version"]}


def recompute_counts(s):
    from app.features.domain.registry_models import OssComponent, OssUsage
    from sqlalchemy import func
    rows = s.query(OssUsage.component_id,
                   func.count(func.distinct(OssUsage.engagement_id)),
                   func.count(func.distinct(OssUsage.vendor_id))).group_by(OssUsage.component_id).all()
    m = {cid: (e, v) for cid, e, v in rows}
    for comp in s.query(OssComponent).all():
        e, v = m.get(comp.id, (0, 0))
        comp.usage_count, comp.vendor_count = e, v
    s.flush()


# ---------- read/query helpers ----------
def _eng_label(s, eid, cache):
    from app.features.domain.registry_models import EngagementRecord
    if eid in cache:
        return cache[eid]
    e = s.query(EngagementRecord).filter_by(engagement_id=eid).first()
    cache[eid] = (e.title if e else eid, e.vendor_id if e else None)
    return cache[eid]


def summary(s):
    from app.features.domain.registry_models import OssComponent, OssSbom, OssUsage, OssVuln, EngagementRecord
    from sqlalchemy import func
    total_eng = s.query(EngagementRecord).count()
    covered = s.query(func.count(func.distinct(OssSbom.engagement_id))).filter_by(superseded=False).scalar() or 0
    comps = s.query(OssComponent).count()
    sboms = s.query(OssSbom).filter_by(superseded=False).count()
    dist = {b: 0 for b in ("LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL")}
    for (b, n) in s.query(OssComponent.risk_band, func.count(OssComponent.id)).group_by(OssComponent.risk_band).all():
        dist[b or "LOW"] = n
    kev = s.query(func.count(func.distinct(OssVuln.component_id))).filter_by(kev=True).scalar() or 0
    prohibited = s.query(OssComponent).filter_by(licence_category="prohibited").count()
    restricted = s.query(OssComponent).filter_by(licence_category="restricted").count()
    top_vuln = [{"id": c.id, "name": c.name, "version": c.version, "risk": c.risk_score,
                 "band": c.risk_band, "usage": c.usage_count}
                for c in s.query(OssComponent).order_by(OssComponent.risk_score.desc(),
                                                        OssComponent.usage_count.desc()).limit(8).all()]
    top_conc = [{"id": c.id, "name": c.name, "version": c.version, "usage": c.usage_count,
                 "vendors": c.vendor_count, "band": c.risk_band}
                for c in s.query(OssComponent).order_by(OssComponent.usage_count.desc()).limit(8).all()]
    return {"total_engagements": total_eng, "covered_engagements": covered,
            "coverage_pct": round(covered / max(1, total_eng) * 100, 1),
            "components": comps, "sboms": sboms, "risk_dist": dist,
            "kev_components": kev, "prohibited_licences": prohibited, "restricted_licences": restricted,
            "top_vulnerable": top_vuln, "top_concentration": top_conc}


def components(s, q=None, licence=None, band_filter=None, limit=200):
    from app.features.domain.registry_models import OssComponent
    qry = s.query(OssComponent)
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func, or_
        qry = qry.filter(or_(func.lower(OssComponent.name).like(like),
                             func.lower(OssComponent.purl).like(like)))
    if licence:
        qry = qry.filter(OssComponent.licence_category == licence)
    if band_filter:
        qry = qry.filter(OssComponent.risk_band == band_filter)
    qry = qry.order_by(OssComponent.risk_score.desc(), OssComponent.usage_count.desc())
    return [{"id": c.id, "name": c.name, "version": c.version, "ecosystem": c.ecosystem,
             "purl": c.purl, "licence": c.licence, "licence_category": c.licence_category,
             "maintenance": c.maintenance, "risk": c.risk_score, "band": c.risk_band,
             "usage": c.usage_count, "vendors": c.vendor_count} for c in qry.limit(limit).all()]


def component_detail(s, cid):
    from app.features.domain.registry_models import OssComponent, OssVuln, OssUsage
    c = s.query(OssComponent).filter_by(id=cid).first()
    if not c:
        return None
    vulns = [{"cve": v.cve, "source": v.source, "cvss": v.cvss, "severity": v.severity,
              "epss": v.epss, "kev": v.kev, "vex_status": v.vex_status, "summary": v.summary}
             for v in s.query(OssVuln).filter_by(component_id=cid).order_by(OssVuln.cvss.desc()).all()]
    cache = {}
    usages = s.query(OssUsage).filter_by(component_id=cid).all()
    affected = {}
    for u in usages:
        title, vid = _eng_label(s, u.engagement_id, cache)
        affected.setdefault(u.engagement_id, {"engagement_id": u.engagement_id, "title": title,
                                              "vendor_id": vid, "dep_type": u.dep_type, "scope": u.scope})
    return {"id": c.id, "name": c.name, "version": c.version, "ecosystem": c.ecosystem,
            "purl": c.purl, "licence": c.licence, "licence_category": c.licence_category,
            "maintenance": c.maintenance, "risk": c.risk_score, "band": c.risk_band,
            "usage": c.usage_count, "vendors": c.vendor_count,
            "vulnerabilities": vulns, "affected_engagements": list(affected.values())}


def blast_radius(s, q, version=None):
    """OBJ-04 / RPT-01: which engagements & vendors are exposed to component q (± version)."""
    from app.features.domain.registry_models import OssComponent, OssUsage
    from sqlalchemy import func, or_
    like = f"%{(q or '').lower()}%"
    cq = s.query(OssComponent).filter(or_(func.lower(OssComponent.name).like(like),
                                          func.lower(OssComponent.purl).like(like)))
    if version:
        cq = cq.filter(OssComponent.version == version)
    comps = cq.all()
    cache = {}
    engs, vendors, prods = {}, set(), set()
    matched = []
    for c in comps:
        matched.append({"id": c.id, "name": c.name, "version": c.version, "band": c.risk_band,
                        "risk": c.risk_score, "licence_category": c.licence_category})
        for u in s.query(OssUsage).filter_by(component_id=c.id).all():
            title, vid = _eng_label(s, u.engagement_id, cache)
            engs.setdefault(u.engagement_id, {"engagement_id": u.engagement_id, "title": title,
                                              "vendor_id": vid, "dep_type": u.dep_type})
            if vid:
                vendors.add(vid)
    return {"query": q, "version": version, "matched_components": matched,
            "engagement_count": len(engs), "vendor_count": len(vendors),
            "engagements": list(engs.values())}


def engagement_oss(s, eid):
    from app.features.domain.registry_models import OssSbom, OssUsage, OssComponent, EngagementRecord
    eng = s.query(EngagementRecord).filter_by(engagement_id=eid).first()
    sboms = s.query(OssSbom).filter_by(engagement_id=eid, superseded=False).all()
    usages = s.query(OssUsage).filter_by(engagement_id=eid).all()
    cids = {u.component_id: u for u in usages}
    comps = s.query(OssComponent).filter(OssComponent.id.in_(list(cids.keys()) or [-1])).all()
    maxrisk = max([c.risk_score for c in comps], default=0)
    nhigh = sum(1 for c in comps if c.risk_band in ("HIGH", "CRITICAL"))
    nkev = sum(1 for c in comps if any(True for _ in []))  # placeholder, computed below
    from app.features.domain.registry_models import OssVuln
    kevids = {v.component_id for v in s.query(OssVuln).filter(OssVuln.kev == True,
              OssVuln.component_id.in_(list(cids.keys()) or [-1])).all()}
    nkev = len([c for c in comps if c.id in kevids])
    nproh = sum(1 for c in comps if c.licence_category == "prohibited")
    signal = min(100, maxrisk + min(12, nhigh * 3))
    return {"engagement_id": eid, "title": eng.title if eng else eid,
            "vendor_id": eng.vendor_id if eng else None,
            "sbom_count": len(sboms), "component_count": len(comps),
            "signal": round(signal, 1), "band": band(signal),
            "high_risk_components": nhigh, "kev_components": nkev, "prohibited_licences": nproh,
            "components": sorted([{"id": c.id, "name": c.name, "version": c.version,
                                   "band": c.risk_band, "risk": c.risk_score,
                                   "licence_category": c.licence_category,
                                   "dep_type": cids[c.id].dep_type, "scope": cids[c.id].scope}
                                  for c in comps], key=lambda x: -x["risk"])}


def concentration(s, limit=20):
    from app.features.domain.registry_models import OssComponent
    rows = s.query(OssComponent).order_by(OssComponent.usage_count.desc()).limit(limit).all()
    return [{"id": c.id, "name": c.name, "version": c.version, "ecosystem": c.ecosystem,
             "usage": c.usage_count, "vendors": c.vendor_count, "band": c.risk_band,
             "risk": c.risk_score, "licence_category": c.licence_category} for c in rows]


def licences(s):
    from app.features.domain.registry_models import OssComponent
    from sqlalchemy import func
    by_cat = {c: 0 for c in ("allowed", "restricted", "prohibited", "review")}
    for (cat, n) in s.query(OssComponent.licence_category, func.count(OssComponent.id)).group_by(OssComponent.licence_category).all():
        by_cat[cat or "review"] = n
    flagged = [{"id": c.id, "name": c.name, "version": c.version, "licence": c.licence,
                "category": c.licence_category, "usage": c.usage_count}
               for c in s.query(OssComponent).filter(OssComponent.licence_category.in_(("prohibited", "restricted")))
               .order_by(OssComponent.usage_count.desc()).limit(60).all()]
    return {"policy": {k: sorted(v) for k, v in LICENCE_POLICY.items()}, "by_category": by_cat, "flagged": flagged}


def vulnerabilities(s, limit=120):
    from app.features.domain.registry_models import OssComponent, OssVuln
    rows = s.query(OssVuln, OssComponent).join(OssComponent, OssComponent.id == OssVuln.component_id)\
        .order_by(OssVuln.kev.desc(), OssVuln.cvss.desc()).limit(limit).all()
    return [{"cve": v.cve, "source": v.source, "cvss": v.cvss, "severity": v.severity, "epss": v.epss,
             "kev": v.kev, "vex_status": v.vex_status, "component_id": c.id, "component": c.name,
             "version": c.version, "usage": c.usage_count, "summary": v.summary} for (v, c) in rows]


def coverage(s):
    from app.features.domain.registry_models import OssSbom, EngagementRecord
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    have = {}
    for sb in s.query(OssSbom).filter_by(superseded=False).all():
        cur = have.get(sb.engagement_id)
        if not cur or (sb.created_at or "") > cur["last"]:
            have[sb.engagement_id] = {"last": sb.created_at or "", "ntia": sb.ntia_score,
                                      "quality": sb.quality_label, "fmt": sb.fmt}
    rows = []
    for e in s.query(EngagementRecord).all():
        h = have.get(e.engagement_id)
        rows.append({"engagement_id": e.engagement_id, "title": e.title, "vendor_id": e.vendor_id,
                     "has_sbom": bool(h), "last": h["last"] if h else None,
                     "stale": bool(h and h["last"] and h["last"] < cutoff),
                     "ntia": h["ntia"] if h else None, "quality": h["quality"] if h else None,
                     "fmt": h["fmt"] if h else None})
    return rows


# ---------------- synthetic seed ----------------
def seed_all(s, coverage_rate=0.66):
    from app.features.domain.registry_models import (OssComponent, OssVuln, OssSbom, OssUsage, EngagementRecord)
    for M in (OssUsage, OssSbom, OssVuln, OssComponent):
        s.query(M).delete()
    s.flush()
    engs = s.query(EngagementRecord).all()
    today = date.today()
    for e in engs:
        if _r("oss-cov", e.engagement_id) > coverage_rate:
            continue
        eid = e.engagement_id
        nc = 8 + int(_r("oss-n", eid) * 16)
        chosen = []
        # popular components (drive concentration + blast radius)
        for pop in _POPULAR:
            if _r("oss-pop", eid, pop) < 0.34:
                chosen.append(pop)
        # fill from library
        idx = _h("oss-fill", eid)
        for k in range(nc):
            lib = _LIB[(idx + k * 7) % len(_LIB)]
            if lib[0] not in chosen:
                chosen.append(lib[0])
        chosen = chosen[:nc + 4]
        fmt_cdx = _h("oss-fmt", eid) % 2 == 0
        spec = "1.5" if fmt_cdx else "SPDX-2.3"
        prod = (e.title or eid)[:60]
        pv = f"{1+int(_r('oss-v1',eid)*8)}.{int(_r('oss-v2',eid)*12)}.{int(_r('oss-v3',eid)*9)}"
        age = 20 + int(_r("oss-age", eid) * 320)   # some > 180 => stale
        created = (today - timedelta(days=age)).isoformat()
        ntia = round(0.62 + _r("oss-ntia", eid) * 0.38, 2)
        sb = OssSbom(engagement_id=eid, vendor_id=e.vendor_id, product=prod, product_version=pv,
                     fmt=("cyclonedx" if fmt_cdx else "spdx"), spec_version=spec,
                     sbom_type=("Build" if fmt_cdx else "Source"),
                     component_count=len(chosen), ntia_score=round(ntia * 100, 1),
                     quality_label=("complete" if ntia >= 0.9 else "partial" if ntia >= 0.6 else "minimal"),
                     source_channel="seed", created_at=created)
        s.add(sb); s.flush()
        for ci, cname in enumerate(chosen):
            lib = next((x for x in _LIB if x[0] == cname), None)
            if not lib:
                continue
            _, eco, lic, versions = lib
            # sometimes pick the vulnerable/older version
            ver = versions[-1] if (len(versions) > 1 and _r("oss-ver", eid, cname) < 0.5) else versions[0]
            comp = _upsert_component(s, cname, ver, f"pkg:{eco}/{cname}@{ver}", None, None, lic, None, eco)
            dep = "direct" if _r("oss-dep", eid, cname) < 0.35 else "transitive"
            scope = "runtime" if _r("oss-scope", eid, cname) < 0.7 else "build"
            s.add(OssUsage(component_id=comp.id, sbom_id=sb.id, engagement_id=eid, vendor_id=e.vendor_id,
                           dep_type=dep, scope=scope, depth=(0 if dep == "direct" else 1 + ci % 3)))
    s.flush()
    recompute_counts(s)
    return {"sboms": s.query(OssSbom).count(), "components": s.query(OssComponent).count(),
            "usages": s.query(OssUsage).count()}
