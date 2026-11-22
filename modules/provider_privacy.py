"""Provider data-use evidence bundle (Provider Routing Policy v1, P0-2).

Provider-level privacy facts live here, in code, with a source page. They are not written by
users or tools, so nothing at runtime can claim "this provider does not train on my data".
The router uses these facts for data permissions, separately from provider billing and limits.

Nothing here selects a provider. Chains are data for the Router (P0-3), which stays the only
authority; ``llm.py`` and callers never pick a provider.
"""
from __future__ import annotations

ROUTE_PUBLIC_RESEARCH = "PUBLIC_RESEARCH"
ROUTE_PRIVATE_GENERAL = "PRIVATE_GENERAL"
ROUTES = frozenset({ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL})

# Only the Router may use these; order is the fallback order inside one route.
CHAINS: dict[str, tuple[str, ...]] = {
    ROUTE_PUBLIC_RESEARCH: ("gemini", "groq", "cloudflare", "ollama"),
    ROUTE_PRIVATE_GENERAL: ("gemini", "groq", "cloudflare", "ollama"),
}

EXCLUDED_PROVIDERS = frozenset({"nvidia", "nvidia_nim"})


# Official sources last reviewed on 2026-11-19; evidence must be re-verified every 180 days
# (P0-2). Expired or undated evidence is rejected instead of being trusted forever.
EVIDENCE_VERIFIED_AT = "2026-11-19"
EVIDENCE_TTL_DAYS = 180


def _epoch(date_text: str) -> float:
    """ISO tarihi (YYYY-MM-DD, UTC) epoch saniyeye çevirir."""
    from datetime import datetime, timezone
    return datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc).timestamp()


PROVIDER_BUNDLE: dict[str, dict] = {
    "groq": {
        "free_no_card": True,
        "trains_on_data": False,
        "retention": "customer data not retained by default; reliability/abuse-monitoring retention possible; ZDR can be enabled",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "source_url": "https://console.groq.com/docs/your-data",
        "evidence_ref": "console.groq.com/docs/your-data; trust.groq.com/faq (no training on customer data)",
        "verified_at": _epoch(EVIDENCE_VERIFIED_AT),
        "expires_at": _epoch(EVIDENCE_VERIFIED_AT) + EVIDENCE_TTL_DAYS * 86400,
    },
    "cloudflare": {
        "free_no_card": True,
        "trains_on_data": False,
        "retention": "Workers AI does not retain inputs/outputs for standard inference; stateful features you enable may store",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "source_url": "https://developers.cloudflare.com/workers-ai/platform/data-usage/",
        "evidence_ref": "developers.cloudflare.com/workers-ai/platform/data-usage (zero data retention, no training)",
        "verified_at": _epoch(EVIDENCE_VERIFIED_AT),
        "expires_at": _epoch(EVIDENCE_VERIFIED_AT) + EVIDENCE_TTL_DAYS * 86400,
    },
    "gemini": {
        "free_no_card": True,
        "trains_on_data": True,
        "retention": "unpaid services: content may be used and human-reviewed to improve Google products",
        "allowed_routes": (ROUTE_PUBLIC_RESEARCH, ROUTE_PRIVATE_GENERAL),
        "input_restriction": "public research or explicit owner-scoped conversation/selected-content consent",
        "source_url": "https://ai.google.dev/gemini-api/terms",
        "evidence_ref": "ai.google.dev/gemini-api/terms#unpaid-services",
        "verified_at": _epoch(EVIDENCE_VERIFIED_AT),
        "expires_at": _epoch(EVIDENCE_VERIFIED_AT) + EVIDENCE_TTL_DAYS * 86400,
    },
}


def _evidence_fresh(facts: dict, now: float) -> bool:
    """Kanıt hâlâ geçerli mi? Tarihsiz veya süresi geçmiş kanıt kullanılmaz (P0-2)."""
    verified = facts.get("verified_at")
    expires = facts.get("expires_at")
    if type(verified) not in (int, float) or type(expires) not in (int, float):
        return False
    if not (0 < verified < expires):
        return False
    # Süre üst sınırı: kanıt en fazla TTL kadar ileri tarihli olabilir.
    return verified <= now + 60 and now < expires and expires - verified <= EVIDENCE_TTL_DAYS * 86400


def privacy_gate(provider: str, route: str | None = None, *, bundle: dict | None = None,
                 consent_scopes=(), data_scope='conversation', now: float | None = None) -> dict:
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
    import time as _time
    if not _evidence_fresh(facts, _time.time() if now is None else now):
        return _deny("PROVIDER_PRIVACY_EVIDENCE_STALE",
                     "Sağlayıcı gizlilik kanıtı güncel değil; kanıt yenilenmeden bu sağlayıcı kullanılmaz.")
    if type(facts.get("trains_on_data")) is not bool:
        return _deny("PROVIDER_PRIVACY_TRAINING_UNKNOWN", "Verinin eğitimde kullanılıp kullanılmadığı bilinmiyor.")
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
