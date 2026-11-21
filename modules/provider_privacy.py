"""Provider data-use evidence bundle (Provider Routing Policy v1, P0-2).

Provider-level privacy facts live here, in code, with a source page and an expiry. They are not
written by users or tools, so nothing at runtime can claim "this provider does not train on my data".
The router uses these facts for data permissions, separately from provider billing and limits.

Nothing here selects a provider. Chains are data for the Router (P0-3), which stays the only
authority; ``llm.py`` and callers never pick a provider.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

ROUTE_PUBLIC_RESEARCH = "PUBLIC_RESEARCH"
ROUTE_PRIVATE_GENERAL = "PRIVATE_GENERAL"
ROUTES = frozenset({ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL})

# Only the Router may use these; order is the fallback order inside one route.
CHAINS: dict[str, tuple[str, ...]] = {
    ROUTE_PUBLIC_RESEARCH: ("gemini", "groq", "cloudflare", "ollama"),
    ROUTE_PRIVATE_GENERAL: ("gemini", "groq", "cloudflare", "ollama"),
}

EXCLUDED_PROVIDERS = frozenset({"nvidia", "nvidia_nim"})


def _day(value: str) -> float:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


# Verified findings from 2026-11-19 (official pages re-checked, not re-researched);
# claims unchanged from the 2026-10-31 card. source_url is the official page for each claim.
_VERIFIED_AT = _day("2026-11-19")
_EXPIRES_AT = _day("2026-12-19")

# Verified findings from 2026-10-31 (not re-researched); source_url is the official page for each claim.
PROVIDER_BUNDLE: dict[str, dict] = {
    "groq": {
        "free_no_card": True,
        "trains_on_data": False,
        "retention": "customer data not retained by default; reliability/abuse-monitoring retention possible; ZDR can be enabled",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "source_url": "https://console.groq.com/docs/your-data",
        "evidence_ref": "console.groq.com/docs/your-data; trust.groq.com/faq (no training on customer data)",
        "verified_at": _VERIFIED_AT,
        "expires_at": _EXPIRES_AT,
    },
    "cloudflare": {
        "free_no_card": True,
        "trains_on_data": False,
        "retention": "Workers AI does not retain inputs/outputs for standard inference; stateful features you enable may store",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "source_url": "https://developers.cloudflare.com/workers-ai/platform/data-usage/",
        "evidence_ref": "developers.cloudflare.com/workers-ai/platform/data-usage (zero data retention, no training)",
        "verified_at": _VERIFIED_AT,
        "expires_at": _EXPIRES_AT,
    },
    "gemini": {
        "free_no_card": True,
        "trains_on_data": True,
        "retention": "unpaid services: content may be used and human-reviewed to improve Google products",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "input_restriction": "public research or explicit owner-scoped conversation/selected-content consent",
        "source_url": "https://ai.google.dev/gemini-api/terms",
        "evidence_ref": "ai.google.dev/gemini-api/terms#unpaid-services",
        "verified_at": _VERIFIED_AT,
        "expires_at": _EXPIRES_AT,
    },
}


def privacy_gate(provider: str, route: str | None = None, *, now: float | None = None,
                 bundle: dict | None = None, consent_scopes=(), data_scope='conversation') -> dict:
    """Is ``provider`` privacy-eligible (for ``route``, when given)? Unknown is never eligible."""
    facts_by_provider = PROVIDER_BUNDLE if bundle is None else bundle
    name = provider if type(provider) is str else ""
    if name in EXCLUDED_PROVIDERS:
        return _deny("PROVIDER_PRIVACY_EXCLUDED", "Bu sağlayıcı politika gereği hiçbir rotada kullanılmaz.")
    facts = facts_by_provider.get(name)
    if not isinstance(facts, dict):
        return _deny("PROVIDER_PRIVACY_EVIDENCE_MISSING", "Sağlayıcı için gizlilik kanıtı yok.")
    source = facts.get("source_url")
    if type(source) is not str or not source.startswith("https://") or not facts.get("evidence_ref"):
        return _deny("PROVIDER_PRIVACY_EVIDENCE_MISSING", "Gizlilik kanıtının kaynak adresi eksik.")
    if type(facts.get("trains_on_data")) is not bool:
        return _deny("PROVIDER_PRIVACY_TRAINING_UNKNOWN", "Verinin eğitimde kullanılıp kullanılmadığı bilinmiyor.")
    expires_at, verified_at = facts.get("expires_at"), facts.get("verified_at")
    if type(expires_at) not in (int, float) or type(verified_at) not in (int, float):
        return _deny("PROVIDER_PRIVACY_EVIDENCE_MISSING", "Gizlilik kanıtının zamanı eksik.")
    if expires_at <= (time.time() if now is None else now):
        return _deny("PROVIDER_PRIVACY_EVIDENCE_STALE", "Gizlilik kanıtının süresi geçmiş; yeniden doğrulama gerekli.")
    allowed = facts.get("allowed_routes")
    if not isinstance(allowed, (tuple, list, frozenset)) or not set(allowed) <= ROUTES:
        return _deny("PROVIDER_PRIVACY_EVIDENCE_MISSING", "İzinli rota listesi geçersiz.")
    if route is None:
        # A provider that may train on data is only eligible for an explicit route.
        if facts["trains_on_data"]:
            return _deny("PROVIDER_ROUTE_REQUIRED", "Veriyi eğitimde kullanabilen sağlayıcı için rota belirtilmeli.")
    else:
        if route not in ROUTES or route not in allowed:
            return _deny("PROVIDER_ROUTE_NOT_ALLOWED", "Bu sağlayıcı bu rota için izinli değil.")
        if facts["trains_on_data"] and route != ROUTE_PUBLIC_RESEARCH and data_scope not in consent_scopes:
            return _deny("PROVIDER_ROUTE_NOT_ALLOWED", "Bu veri kapsamı için Gemini kurulum izni kapalı; ücretsiz içerik eğitimde kullanılabilir.")
    return {"ok": True, "reason_code": None, "reason": "Gizlilik kanıtı geçerli.", "facts": dict(facts)}


def _deny(code: str, reason: str) -> dict:
    return {"ok": False, "reason_code": code, "reason": reason}
