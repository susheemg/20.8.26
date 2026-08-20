"""Multilingual layer. Display translation, user-input normalisation to English,
and document translation + logical correlation — all AI-driven (gated), with an
offline seed dictionary for the navigation chrome so the selector works without AI.

Design rule: the BACKEND OF RECORD IS ALWAYS ENGLISH. Non-English typed input and
documents are translated to English by AI for storage; the original is preserved at
the edge. Display is translated outward to the user's chosen language."""
from __future__ import annotations
import json


def _obs_swallow(_ctx, _exc):
    """Swallow a non-critical exception but emit one observable log line.
    Never raises — observability must not change control flow."""
    try:
        from app.features.admin.security import log_json as _lj
    except Exception:
        return
    try:
        _lj('swallowed_exception', where=_ctx,
            error=f'{type(_exc).__name__}: {str(_exc)[:200]}')
    except Exception:
        pass


# Top-10 business languages (endonyms). rtl flags drive document direction.
LANGUAGES = [
    {"code": "en", "native": "English", "english": "English", "rtl": False},
    {"code": "zh", "native": "中文", "english": "Chinese (Mandarin)", "rtl": False},
    {"code": "es", "native": "Español", "english": "Spanish", "rtl": False},
    {"code": "ar", "native": "العربية", "english": "Arabic", "rtl": True},
    {"code": "fr", "native": "Français", "english": "French", "rtl": False},
    {"code": "de", "native": "Deutsch", "english": "German", "rtl": False},
    {"code": "ja", "native": "日本語", "english": "Japanese", "rtl": False},
    {"code": "pt", "native": "Português", "english": "Portuguese", "rtl": False},
    {"code": "ru", "native": "Русский", "english": "Russian", "rtl": False},
    {"code": "hi", "native": "हिन्दी", "english": "Hindi", "rtl": False},
]
_LANG_BY_CODE = {l["code"]: l for l in LANGUAGES}

# Offline seed for navigation chrome — accurate Latin-script translations so the
# selector demonstrably works with no AI engine connected. Product/proper names
# (Brata, BRO Chat, ProAssess, Vendor 360, Financial DD) are intentionally left
# untranslated. AI fills every other language and any string not seeded here.
_NAV = {
    "Home":               {"es": "Inicio", "fr": "Accueil", "de": "Startseite", "pt": "Início"},
    "Dashboard":          {"es": "Panel", "fr": "Tableau de bord", "de": "Übersicht", "pt": "Painel"},
    "Assessment":         {"es": "Evaluación", "fr": "Évaluation", "de": "Bewertung", "pt": "Avaliação"},
    "Assessments":        {"es": "Evaluaciones", "fr": "Évaluations", "de": "Bewertungen", "pt": "Avaliações"},
    "Vendors":            {"es": "Proveedores", "fr": "Fournisseurs", "de": "Lieferanten", "pt": "Fornecedores"},
    "Vendor Register":    {"es": "Registro de proveedores", "fr": "Registre des fournisseurs", "de": "Lieferantenregister", "pt": "Registo de fornecedores"},
    "Engagements":        {"es": "Contrataciones", "fr": "Engagements", "de": "Beauftragungen", "pt": "Contratações"},
    "Certifications":     {"es": "Certificaciones", "fr": "Certifications", "de": "Zertifizierungen", "pt": "Certificações"},
    "Performance":        {"es": "Rendimiento", "fr": "Performance", "de": "Leistung", "pt": "Desempenho"},
    "Intelligence":       {"es": "Inteligencia", "fr": "Renseignement", "de": "Erkenntnisse", "pt": "Inteligência"},
    "Reputation":         {"es": "Reputación", "fr": "Réputation", "de": "Reputation", "pt": "Reputação"},
    "Contracts":          {"es": "Contratos", "fr": "Contrats", "de": "Verträge", "pt": "Contratos"},
    "Management":         {"es": "Dirección", "fr": "Direction", "de": "Management", "pt": "Gestão"},
    "Global Regulations": {"es": "Normativa global", "fr": "Réglementations mondiales", "de": "Globale Vorschriften", "pt": "Regulamentações globais"},
    "Advanced Analysis":  {"es": "Análisis avanzado", "fr": "Analyse avancée", "de": "Erweiterte Analyse", "pt": "Análise avançada"},
    "Overview":           {"es": "Resumen", "fr": "Aperçu", "de": "Überblick", "pt": "Visão geral"},
    "Data Integrity":     {"es": "Integridad de datos", "fr": "Intégrité des données", "de": "Datenintegrität", "pt": "Integridade de dados"},
    "Entity Graph":       {"es": "Grafo de entidades", "fr": "Graphe d'entités", "de": "Entitätsgraph", "pt": "Grafo de entidades"},
    "BU Exposure":        {"es": "Exposición por unidad", "fr": "Exposition par unité", "de": "Exposition je Geschäftsbereich", "pt": "Exposição por unidade"},
    "Geopolitical":       {"es": "Geopolítica", "fr": "Géopolitique", "de": "Geopolitik", "pt": "Geopolítica"},
    "Governance":         {"es": "Gobernanza", "fr": "Gouvernance", "de": "Governance", "pt": "Governança"},
    "Findings":           {"es": "Hallazgos", "fr": "Constats", "de": "Feststellungen", "pt": "Constatações"},
    "4th Party Register": {"es": "Registro de cuartas partes", "fr": "Registre des quatrièmes parties", "de": "Viertpartei-Register", "pt": "Registo de quartas partes"},
    "Reference & Admin":  {"es": "Referencia y administración", "fr": "Référence et administration", "de": "Referenz & Verwaltung", "pt": "Referência e administração"},
    "Documents":          {"es": "Documentos", "fr": "Documents", "de": "Dokumente", "pt": "Documentos"},
    "Methodology":        {"es": "Metodología", "fr": "Méthodologie", "de": "Methodik", "pt": "Metodologia"},
    "Settings":           {"es": "Configuración", "fr": "Paramètres", "de": "Einstellungen", "pt": "Definições"},
    "Audit":              {"es": "Auditoría", "fr": "Audit", "de": "Audit", "pt": "Auditoria"},
    "Sign out":           {"es": "Cerrar sesión", "fr": "Déconnexion", "de": "Abmelden", "pt": "Terminar sessão"},
    "Language":           {"es": "Idioma", "fr": "Langue", "de": "Sprache", "pt": "Idioma"},
    "Translation workbench": {"es": "Mesa de traducción", "fr": "Atelier de traduction", "de": "Übersetzungswerkbank", "pt": "Bancada de tradução"},
}

# runtime cache: code -> {english: translation}; seeded from _NAV
_CACHE: dict = {l["code"]: {} for l in LANGUAGES}
for _en, _m in _NAV.items():
    for _code, _t in _m.items():
        _CACHE[_code][_en] = _t


def lang_name(code: str) -> str:
    return _LANG_BY_CODE.get(code, {}).get("english", code)


def _ai():
    from app.agents import llm_config
    return llm_config


def translate_strings(strings, code: str) -> dict:
    """Return {english: translated} for the target language. Seed/cache first,
    AI for the remainder (if live). Unresolved strings are omitted (client keeps English)."""
    if code == "en" or code not in _CACHE:
        return {}
    cache = _CACHE[code]
    out, misses = {}, []
    for s in strings:
        if s in cache:
            out[s] = cache[s]
        else:
            misses.append(s)
    ai_used = False
    if misses:
        llm = _ai()
        if llm.status().get("live_ready"):
            ai_used = True
            prompt = ("Translate these UI labels to " + lang_name(code) + ". "
                      "Keep product/proper names unchanged (Brata, BRO Chat, ProAssess, Vendor 360, Financial DD). "
                      "Return ONLY a JSON object mapping each original string to its translation.\n"
                      + json.dumps(misses, ensure_ascii=False))
            try:
                raw = llm.complete("Professional UI localiser. Output only a JSON object.",
                                   prompt, domain="general", max_tokens=900)
                t = (raw or "").replace("```json", "").replace("```", "").strip()
                i, e = t.find("{"), t.rfind("}")
                if i != -1 and e != -1:
                    m = json.loads(t[i:e + 1])
                    for k, v in m.items():
                        if isinstance(v, str) and v.strip():
                            cache[k] = v.strip()
                            out[k] = v.strip()
            except Exception as _e:
                _obs_swallow('i18n.py', _e)
    return {"_map": out, "_ai": ai_used}


def to_english(text: str, code: str | None = None) -> dict:
    """Normalise non-English typed input to English for backend storage."""
    llm = _ai()
    if not text or not text.strip():
        return {"english": "", "detected_language": "unknown", "ai": False}
    if not llm.status().get("live_ready"):
        return {"english": text, "detected_language": "unknown", "ai": False, "holding": True}
    prompt = ("Detect the language of the text below and translate it to clear business English. "
              "Return ONLY JSON: {\"detected_language\":\"<English name>\",\"english\":\"<translation>\"}.\n\n" + text)
    try:
        raw = llm.complete("Professional translator. Output only JSON.", prompt,
                           domain="general", max_tokens=900)
        t = (raw or "").replace("```json", "").replace("```", "").strip()
        i, e = t.find("{"), t.rfind("}")
        d = json.loads(t[i:e + 1]) if (i != -1 and e != -1) else {}
        return {"english": d.get("english", text), "detected_language": d.get("detected_language", "unknown"), "ai": True}
    except Exception:
        return {"english": text, "detected_language": "unknown", "ai": True}


def translate_document(text: str) -> dict:
    """Translate a document to English and produce a logical risk correlation."""
    llm = _ai()
    if not text or not text.strip():
        return {"english": "", "detected_language": "unknown", "correlation": "", "ai": False}
    if not llm.status().get("live_ready"):
        return {"english": text, "detected_language": "unknown", "correlation": "",
                "ai": False, "holding": True}
    prompt = ("For the document below: (1) detect its language, (2) translate it to business English, "
              "(3) give a short logical correlation to TPRM — which risk domains it touches "
              "(information security, resilience, financial, privacy, compliance, reputation) and any "
              "obligations/red flags. Return ONLY JSON: "
              "{\"detected_language\":\"\",\"english\":\"\",\"correlation\":\"\"}.\n\n" + text[:6000])
    try:
        raw = llm.complete("Multilingual TPRM analyst. Output only JSON.", prompt,
                           domain="risk", max_tokens=1300)
        t = (raw or "").replace("```json", "").replace("```", "").strip()
        i, e = t.find("{"), t.rfind("}")
        d = json.loads(t[i:e + 1]) if (i != -1 and e != -1) else {}
        return {"english": d.get("english", text), "detected_language": d.get("detected_language", "unknown"),
                "correlation": d.get("correlation", ""), "ai": True}
    except Exception:
        return {"english": text, "detected_language": "unknown", "correlation": "", "ai": True}
