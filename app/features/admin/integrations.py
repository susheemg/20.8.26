"""Enterprise integration suite — outbound connectors to external TPRM, ERP and
risk-intelligence systems.

Supported connectors
--------------------
* ``sap``              SAP S/4HANA / Ariba — vendor master & annual spend (ERP)
* ``processunity``     ProcessUnity — assessment status, tier & findings (GRC)
* ``rapidratings``     RapidRatings — Financial Health Rating (FHR) & CoreScore
* ``interos``          Interos — multi-factor resilience (financial/operational/
                       cyber/geographic/ESG/restrictions) & concentration
* ``securityscorecard``SecurityScorecard — cyber security grade (A–F / 0–100)
* ``riskrecon``        RiskRecon (a Mastercard company) — cyber rating (A–F / 0–10)

Design
------
* **Offline-safe.** With no credentials configured a connector returns a
  deterministic, clearly-badged ``stub`` payload so the integration is fully
  demonstrable without live keys. When a real key is present it issues the live
  HTTP request. Every result carries a ``mode`` of ``live`` or ``stub`` — the
  platform never disguises sample data as real.
* **Secure config.** Non-secret config (base URL, external-id mapping, enabled)
  lives in ``connector_config``; the API credential is referenced by a secret
  name resolved through ``secrets.get_secret`` (env / file / AWS / Vault) and is
  never returned by the API or written to logs.
* **Normalised landing.** Each connector maps its native payload onto Brata's
  ``VendorMonitorSignal`` stream (and ``VendorMasterExt`` rating fields), so all
  external intelligence flows into one risk picture.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.features.domain.models_db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _obs_swallow(_ctx, _exc):
    try:
        from app.features.admin.security import log_json as _lj
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
class ConnectorConfig(Base):
    __tablename__ = "connector_config"
    connector_key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[Optional[str]] = mapped_column(String, default=None)
    secret_name: Mapped[Optional[str]] = mapped_column(String, default=None)  # name only, never the value
    config_json: Mapped[Optional[str]] = mapped_column(Text, default=None)    # non-secret JSON
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    last_status: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_by: Mapped[Optional[str]] = mapped_column(String, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ConnectorSyncLog(Base):
    __tablename__ = "connector_sync_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_key: Mapped[str] = mapped_column(String)
    vendor_id: Mapped[Optional[str]] = mapped_column(String, default=None)
    action: Mapped[str] = mapped_column(String, default="sync")
    mode: Mapped[Optional[str]] = mapped_column(String, default=None)   # live | stub
    status: Mapped[str] = mapped_column(String, default="ok")           # ok | error
    records: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------------------------------------------------------------------------
# base connector
# ---------------------------------------------------------------------------
class BaseConnector:
    key: str = "base"
    name: str = "Base"
    category: str = "generic"
    description: str = ""
    default_base_url: str = ""
    auth_scheme: str = "bearer"          # bearer | token | apikey | oauth2 | basic
    signal_types: tuple = ()
    # how a Brata vendor is identified in the remote system
    external_id_field: str = "external_id"
    docs_url: str = ""

    def __init__(self, cfg: Optional["ConnectorConfig"] = None):
        self.cfg = cfg

    # ---- credential resolution (never returns to caller) -------------------
    def _secret(self) -> Optional[str]:
        name = (self.cfg.secret_name if self.cfg else None) or self._default_secret_name()
        if not name:
            return None
        try:
            from app.features.admin import secrets as S
            return S.get_secret(name)
        except Exception as e:
            _obs_swallow('integrations._secret', e)
            return None

    def _default_secret_name(self) -> str:
        return f"BRO_CONN_{self.key.upper()}_KEY"

    def is_live(self) -> bool:
        return bool(self._secret())

    def base_url(self) -> str:
        return (self.cfg.base_url if self.cfg and self.cfg.base_url else self.default_base_url)

    # ---- connection test ---------------------------------------------------
    def test_connection(self) -> dict:
        if not self.is_live():
            return {"connector": self.key, "mode": "stub", "ok": True,
                    "detail": "No credential configured — connector runs in stub mode "
                              "(deterministic sample data). Set the secret to go live."}
        try:
            ok, detail = self._live_ping()
            return {"connector": self.key, "mode": "live", "ok": ok, "detail": detail}
        except Exception as e:
            return {"connector": self.key, "mode": "live", "ok": False,
                    "detail": f"{type(e).__name__}: {str(e)[:160]}"}

    def _live_ping(self):
        # subclasses may override; default does a no-op auth-presence check
        return True, "Credential present; reachability check not implemented for this connector."

    # ---- pull + normalise --------------------------------------------------
    def pull(self, external_id: str) -> dict:
        """Return a normalised payload: {mode, signals:[{type,value,source}], ext:{...}}."""
        if self.is_live():
            try:
                raw = self._live_pull(external_id)
                return {"mode": "live", **self.normalise(raw, external_id)}
            except Exception as e:
                _obs_swallow('integrations.pull', e)
                return {"mode": "live", "error": f"{type(e).__name__}: {str(e)[:160]}",
                        "signals": [], "ext": {}}
        return {"mode": "stub", **self.normalise(self._stub_raw(external_id), external_id)}

    def _live_pull(self, external_id: str) -> dict:
        raise NotImplementedError

    def _stub_raw(self, external_id: str) -> dict:
        return {}

    def normalise(self, raw: dict, external_id: str) -> dict:
        return {"signals": [], "ext": {}}

    # deterministic pseudo-value from an id so stubs are stable per vendor
    def _seed(self, external_id: str, mod: int) -> int:
        return sum(ord(c) for c in (external_id or "x")) % mod

    def manifest(self) -> dict:
        return {
            "key": self.key, "name": self.name, "category": self.category,
            "description": self.description, "auth_scheme": self.auth_scheme,
            "default_base_url": self.default_base_url, "signal_types": list(self.signal_types),
            "external_id_field": self.external_id_field, "docs_url": self.docs_url,
            "secret_name": self._default_secret_name(),
        }


# ---------------------------------------------------------------------------
# concrete connectors
# ---------------------------------------------------------------------------
class SAPConnector(BaseConnector):
    key = "sap"; name = "SAP S/4HANA / Ariba"; category = "erp"
    description = "Vendor master (Business Partner) and annual spend from SAP ERP / Ariba."
    default_base_url = "https://my-s4hana.example.com/sap/opu/odata/sap/API_BUSINESS_PARTNER"
    auth_scheme = "oauth2"; external_id_field = "sap_bp_number"
    signal_types = ("spend", "vendor_master")
    docs_url = "https://api.sap.com/api/API_BUSINESS_PARTNER"

    def _stub_raw(self, external_id):
        spend = 250_000 + self._seed(external_id, 40) * 75_000
        return {"BusinessPartner": external_id or "0001000123",
                "BusinessPartnerName": "Sample Supplier GmbH",
                "Country": ["DE", "GB", "US", "IN"][self._seed(external_id, 4)],
                "AnnualSpend": spend, "Currency": "USD",
                "BlockedIndicator": False}

    def _live_pull(self, external_id):
        import httpx
        tok = self._secret()
        url = f"{self.base_url()}/A_BusinessPartner('{external_id}')?$format=json"
        r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        r.raise_for_status()
        return r.json().get("d", r.json())

    def normalise(self, raw, external_id):
        spend = raw.get("AnnualSpend")
        ext = {"trading_name": raw.get("BusinessPartnerName"),
               "incorporation_country": raw.get("Country")}
        signals = []
        if spend is not None:
            signals.append({"type": "spend", "value": f"{spend:,.0f} {raw.get('Currency','USD')}",
                            "source": "SAP"})
        if raw.get("BlockedIndicator"):
            signals.append({"type": "vendor_master", "value": "BLOCKED in SAP", "source": "SAP"})
        return {"signals": signals, "ext": ext}


class ProcessUnityConnector(BaseConnector):
    key = "processunity"; name = "ProcessUnity"; category = "grc"
    description = "Assessment status, inherent tier and open findings from ProcessUnity TPRM."
    default_base_url = "https://api.processunity.com/v1"
    auth_scheme = "apikey"; external_id_field = "pu_vendor_id"
    signal_types = ("assessment_status", "external_tier", "open_findings")
    docs_url = "https://help.processunity.com/"

    def _stub_raw(self, external_id):
        tiers = ["Tier 1", "Tier 2", "Tier 3"]
        statuses = ["Completed", "In Review", "In Progress", "Overdue"]
        return {"vendorId": external_id or "PU-10293",
                "assessmentStatus": statuses[self._seed(external_id, 4)],
                "inherentTier": tiers[self._seed(external_id, 3)],
                "openFindings": self._seed(external_id, 6),
                "lastAssessed": "2026-04-18"}

    def _live_pull(self, external_id):
        import httpx
        r = httpx.get(f"{self.base_url()}/vendors/{external_id}/assessment",
                      headers={"X-API-Key": self._secret()}, timeout=20)
        r.raise_for_status()
        return r.json()

    def normalise(self, raw, external_id):
        signals = [
            {"type": "assessment_status", "value": raw.get("assessmentStatus"), "source": "ProcessUnity"},
            {"type": "external_tier", "value": raw.get("inherentTier"), "source": "ProcessUnity"},
            {"type": "open_findings", "value": str(raw.get("openFindings", 0)), "source": "ProcessUnity"},
        ]
        return {"signals": [s for s in signals if s["value"] is not None], "ext": {}}


class RapidRatingsConnector(BaseConnector):
    key = "rapidratings"; name = "RapidRatings"; category = "financial"
    description = "Financial Health Rating (FHR 0–100) and CoreScore for financial-distress monitoring."
    default_base_url = "https://api.rapidratings.com/v2"
    auth_scheme = "bearer"; external_id_field = "rr_company_id"
    signal_types = ("financial_health",)
    docs_url = "https://www.rapidratings.com/"

    def _band(self, fhr: int) -> str:
        return ("Very Strong" if fhr >= 75 else "Strong" if fhr >= 60 else
                "Medium" if fhr >= 40 else "Weak" if fhr >= 25 else "Very Weak")

    def _stub_raw(self, external_id):
        fhr = 35 + self._seed(external_id, 60)
        return {"companyId": external_id or "RR-55812", "fhr": fhr,
                "coreScore": max(1, fhr - self._seed(external_id, 8)),
                "asOf": "2026-03-31"}

    def _live_pull(self, external_id):
        import httpx
        r = httpx.get(f"{self.base_url()}/companies/{external_id}/fhr",
                      headers={"Authorization": f"Bearer {self._secret()}"}, timeout=20)
        r.raise_for_status()
        return r.json()

    def normalise(self, raw, external_id):
        fhr = raw.get("fhr")
        signals, ext = [], {}
        if fhr is not None:
            band = self._band(int(fhr))
            signals.append({"type": "financial_health",
                            "value": f"FHR {fhr} ({band})", "source": "RapidRatings"})
            ext = {"financial_health_band": band, "credit_rating": f"FHR {fhr}",
                   "credit_rating_date": raw.get("asOf")}
        return {"signals": signals, "ext": ext}


class InterosConnector(BaseConnector):
    key = "interos"; name = "Interos"; category = "supply_chain"
    description = "Multi-factor resilience (financial, operational, cyber, geographic, ESG, restrictions) and concentration."
    default_base_url = "https://api.interos.ai/v2"
    auth_scheme = "oauth2"; external_id_field = "interos_entity_id"
    signal_types = ("resilience", "concentration", "restrictions")
    docs_url = "https://www.interos.ai/"

    def _stub_raw(self, external_id):
        s = self._seed(external_id, 40)
        return {"entityId": external_id or "INT-7741",
                "scores": {"financial": 60 + s % 35, "operational": 55 + s % 40,
                            "cyber": 50 + s % 45, "geographic": 65 + s % 30,
                            "esg": 58 + s % 38, "restrictions": 80 + s % 20},
                "nthPartyCount": 40 + s, "restrictedParties": s % 3}

    def _live_pull(self, external_id):
        import httpx
        r = httpx.get(f"{self.base_url()}/entities/{external_id}/scores",
                      headers={"Authorization": f"Bearer {self._secret()}"}, timeout=20)
        r.raise_for_status()
        return r.json()

    def normalise(self, raw, external_id):
        sc = raw.get("scores", {})
        signals = [{"type": "resilience",
                    "value": "Interos resilience — " + ", ".join(f"{k}:{v}" for k, v in sc.items()),
                    "source": "Interos"}]
        if raw.get("nthPartyCount") is not None:
            signals.append({"type": "concentration",
                            "value": f"{raw['nthPartyCount']} nth-party dependencies", "source": "Interos"})
        if raw.get("restrictedParties"):
            signals.append({"type": "restrictions",
                            "value": f"{raw['restrictedParties']} restricted-party hit(s)", "source": "Interos"})
        return {"signals": signals, "ext": {}}


class SecurityScorecardConnector(BaseConnector):
    key = "securityscorecard"; name = "SecurityScorecard"; category = "cyber"
    description = "External cyber-security grade (A–F) and score (0–100) across ten factor groups."
    default_base_url = "https://api.securityscorecard.io"
    auth_scheme = "token"; external_id_field = "primary_domain"
    signal_types = ("cyber_rating",)
    docs_url = "https://securityscorecard.readme.io/"

    def _grade(self, score: int) -> str:
        return ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else
                "D" if score >= 60 else "F")

    def _stub_raw(self, external_id):
        score = 60 + self._seed(external_id, 40)
        return {"domain": external_id or "supplier.example.com", "score": score,
                "grade": self._grade(score), "asOf": "2026-06-15"}

    def _live_pull(self, external_id):
        import httpx
        r = httpx.get(f"{self.base_url()}/companies/{external_id}/factors",
                      headers={"Authorization": f"Token {self._secret()}"}, timeout=20)
        r.raise_for_status()
        d = r.json()
        return {"domain": external_id, "score": d.get("score"),
                "grade": d.get("grade"), "asOf": d.get("date")}

    def normalise(self, raw, external_id):
        grade, score = raw.get("grade"), raw.get("score")
        signals, ext = [], {}
        if grade:
            signals.append({"type": "cyber_rating",
                            "value": f"SecurityScorecard {grade} ({score})", "source": "SecurityScorecard"})
            ext = {"external_rating": f"SSC {grade}", "external_rating_date": raw.get("asOf")}
        return {"signals": signals, "ext": ext}


class RiskReconConnector(BaseConnector):
    key = "riskrecon"; name = "RiskRecon (Mastercard)"; category = "cyber"
    description = "External cyber rating (A–F / 0–10) with issue-level findings by security domain."
    default_base_url = "https://api.riskrecon.com/v1"
    auth_scheme = "bearer"; external_id_field = "toe_id"
    signal_types = ("cyber_rating",)
    docs_url = "https://docs.riskrecon.com/"

    def _grade(self, rating: float) -> str:
        return ("A" if rating >= 9 else "B" if rating >= 8 else "C" if rating >= 7 else
                "D" if rating >= 6 else "F")

    def _stub_raw(self, external_id):
        rating = round(6.0 + self._seed(external_id, 40) / 10.0, 1)
        return {"toeId": external_id or "RR-TOE-3391", "rating": rating,
                "grade": self._grade(rating), "asOf": "2026-06-10"}

    def _live_pull(self, external_id):
        import httpx
        r = httpx.get(f"{self.base_url()}/performance/toe/{external_id}",
                      headers={"Authorization": f"Bearer {self._secret()}"}, timeout=20)
        r.raise_for_status()
        d = r.json()
        return {"toeId": external_id, "rating": d.get("rating"),
                "grade": d.get("grade"), "asOf": d.get("asOf")}

    def normalise(self, raw, external_id):
        grade, rating = raw.get("grade"), raw.get("rating")
        signals, ext = [], {}
        if grade:
            signals.append({"type": "cyber_rating",
                            "value": f"RiskRecon {grade} ({rating})", "source": "RiskRecon"})
            ext = {"external_rating": f"RiskRecon {grade}", "external_rating_date": raw.get("asOf")}
        return {"signals": signals, "ext": ext}


# ---------------------------------------------------------------------------
# registry + service
# ---------------------------------------------------------------------------
_CONNECTORS = {c.key: c for c in [
    SAPConnector, ProcessUnityConnector, RapidRatingsConnector,
    InterosConnector, SecurityScorecardConnector, RiskReconConnector,
]}


def catalog() -> list:
    return [cls().manifest() for cls in _CONNECTORS.values()]


def get_connector(s: Session, key: str) -> Optional[BaseConnector]:
    cls = _CONNECTORS.get(key)
    if not cls:
        return None
    cfg = s.get(ConnectorConfig, key)
    return cls(cfg)


def config_row(s: Session, key: str) -> dict:
    cls = _CONNECTORS.get(key)
    if not cls:
        return {}
    cfg = s.get(ConnectorConfig, key)
    conn = cls(cfg)
    man = conn.manifest()
    return {**man, "enabled": bool(cfg.enabled) if cfg else False,
            "base_url": (cfg.base_url if cfg and cfg.base_url else man["default_base_url"]),
            "secret_name": (cfg.secret_name if cfg and cfg.secret_name else man["secret_name"]),
            "credential_present": conn.is_live(),
            "last_sync_at": cfg.last_sync_at.isoformat() if cfg and cfg.last_sync_at else None,
            "last_status": cfg.last_status if cfg else None,
            "config": json.loads(cfg.config_json) if (cfg and cfg.config_json) else {}}


def upsert_config(s: Session, key: str, *, enabled=None, base_url=None,
                  secret_name=None, config=None, actor="admin") -> dict:
    if key not in _CONNECTORS:
        raise KeyError(key)
    cfg = s.get(ConnectorConfig, key) or ConnectorConfig(connector_key=key)
    if enabled is not None:
        cfg.enabled = bool(enabled)
    if base_url is not None:
        cfg.base_url = base_url or None
    if secret_name is not None:
        cfg.secret_name = secret_name or None
    if config is not None:
        cfg.config_json = json.dumps(config)
    cfg.updated_by = actor
    cfg.updated_at = _now()
    s.add(cfg)
    s.flush()
    return config_row(s, key)


def _external_id(s: Session, conn: BaseConnector, vendor_id: str) -> Optional[str]:
    """Resolve the vendor's id in the remote system from connector config map
    (config['id_map'][vendor_id]) or fall back to the Brata vendor_id."""
    cfg = conn.cfg
    if cfg and cfg.config_json:
        try:
            idmap = json.loads(cfg.config_json).get("id_map", {})
            if vendor_id in idmap:
                return idmap[vendor_id]
        except Exception as e:
            _obs_swallow('integrations._external_id', e)
    return vendor_id


def sync_vendor(s: Session, key: str, vendor_id: str, actor="system") -> dict:
    conn = get_connector(s, key)
    if not conn:
        raise KeyError(key)
    ext_id = _external_id(s, conn, vendor_id)
    payload = conn.pull(ext_id)
    mode = payload.get("mode")
    if payload.get("error"):
        log = ConnectorSyncLog(connector_key=key, vendor_id=vendor_id, mode=mode,
                               status="error", records=0, message=payload["error"])
        s.add(log)
        _touch(s, key, "error")
        s.flush()
        return {"vendor_id": vendor_id, "connector": key, "mode": mode,
                "status": "error", "message": payload["error"], "signals": 0}
    # write monitor signals
    n = 0
    try:
        from app.features.domain import master_service as MS
        for sig in payload.get("signals", []):
            if sig.get("value") is None:
                continue
            MS.add_monitor_signal(s, vendor_id, sig["type"], sig["value"], source=sig.get("source", key))
            n += 1
        # update VendorMasterExt rating fields
        ext = payload.get("ext", {})
        if ext:
            _apply_ext(s, vendor_id, ext)
    except Exception as e:
        _obs_swallow('integrations.sync_vendor.write', e)
    log = ConnectorSyncLog(connector_key=key, vendor_id=vendor_id, mode=mode,
                           status="ok", records=n,
                           message=f"{n} signal(s) ingested")
    s.add(log)
    _touch(s, key, "ok")
    s.flush()
    return {"vendor_id": vendor_id, "connector": key, "mode": mode,
            "status": "ok", "signals": n, "detail": payload.get("signals", [])}


def _apply_ext(s: Session, vendor_id: str, ext: dict):
    """Apply normalised rating fields to the correct extension model:
    financial/master fields land on VendorMasterExt; cyber rating fields land
    on VendorCyber."""
    try:
        from app.features.domain import master_ext as MX
        CYBER_FIELDS = {"external_rating", "external_rating_date", "assurance_status"}
        master = {k: v for k, v in ext.items() if k not in CYBER_FIELDS}
        cyber = {k: v for k, v in ext.items() if k in CYBER_FIELDS}
        if master:
            row = s.scalar(select(MX.VendorMasterExt).where(MX.VendorMasterExt.vendor_id == vendor_id))
            if not row:
                row = MX.VendorMasterExt(vendor_id=vendor_id); s.add(row)
            for k, v in master.items():
                if v is not None and hasattr(row, k):
                    setattr(row, k, v)
        if cyber and hasattr(MX, "VendorCyber"):
            crow = s.scalar(select(MX.VendorCyber).where(MX.VendorCyber.vendor_id == vendor_id))
            if not crow:
                crow = MX.VendorCyber(vendor_id=vendor_id); s.add(crow)
            for k, v in cyber.items():
                if v is not None and hasattr(crow, k):
                    setattr(crow, k, v)
        s.flush()
    except Exception as e:
        _obs_swallow('integrations._apply_ext', e)


def _touch(s: Session, key: str, status: str):
    cfg = s.get(ConnectorConfig, key) or ConnectorConfig(connector_key=key)
    cfg.last_sync_at = _now()
    cfg.last_status = status
    s.add(cfg)


def sync_all_vendors(s: Session, key: str, vendor_ids: list, actor="system") -> dict:
    ok = err = sig = 0
    for vid in vendor_ids:
        r = sync_vendor(s, key, vid, actor=actor)
        if r["status"] == "ok":
            ok += 1; sig += r.get("signals", 0)
        else:
            err += 1
    return {"connector": key, "vendors": len(vendor_ids), "ok": ok,
            "errors": err, "signals": sig}


def recent_logs(s: Session, key: Optional[str] = None, limit: int = 50) -> list:
    stmt = select(ConnectorSyncLog).order_by(ConnectorSyncLog.id.desc()).limit(limit)
    if key:
        stmt = select(ConnectorSyncLog).where(ConnectorSyncLog.connector_key == key)\
            .order_by(ConnectorSyncLog.id.desc()).limit(limit)
    return [{"id": l.id, "connector": l.connector_key, "vendor_id": l.vendor_id,
             "action": l.action, "mode": l.mode, "status": l.status, "records": l.records,
             "message": l.message,
             "created_at": l.created_at.isoformat() if l.created_at else None}
            for l in s.scalars(stmt).all()]
