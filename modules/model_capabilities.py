"""Developer-controlled, model-specific native feature evidence for Router plans.

No network calls, no user-editable capability claims. Only exact model IDs with
official source pages and bounded expiry appear in the registry; native API
features remain disabled until their transport adapter is explicitly verified.
Unverified, expired and unknown data cannot turn on native schemas, tool calling
or a promised context length. Ordinary text and validator-based JSON parsing do
not require native support and retain their established routes.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from collections.abc import Mapping

NATIVE_FEATURES = frozenset({'native_json_schema', 'native_tool_calling', 'verified_vision'})
# Keyed by (provider, EXACT model id), not by model family/prefix/provider.
# Example SHAPE only, not a claim about any actual model:
# ('provider','exact-id'): {'features': frozenset({'native_json_schema'}),
#     'context_limit': 32768, 'output_limit': 4096, 'source_url': 'https://...',
#     'verified_at': 1794000000, 'expires_at': 1795000000}
_GROQ_REVIEWED_AT = 1794225600  # 9 Nov 2026 12:00 UTC
_GROQ_EXPIRES_AT = 1794830400   # 16 Nov 2026 12:00 UTC
# Only context/output capacities are asserted. Although Groq docs describe
# native structured outputs, our transport has not implemented schema-bearing
# API requests, so NO native JSON/tool capability is advertised here.
CATALOG: dict[tuple[str, str], dict] = {
    ('groq', 'openai/gpt-oss-120b'): {
        'features': frozenset(),
        'context_limit': 131072, 'output_limit': 65536,
        'source_url': 'https://console.groq.com/docs/model/openai/gpt-oss-120b',
        'verified_at': _GROQ_REVIEWED_AT, 'expires_at': _GROQ_EXPIRES_AT,
    },
    ('groq', 'openai/gpt-oss-20b'): {
        'features': frozenset(),
        'context_limit': 131072, 'output_limit': 65536,
        'source_url': 'https://console.groq.com/docs/model/openai/gpt-oss-20b',
        'verified_at': _GROQ_REVIEWED_AT, 'expires_at': _GROQ_EXPIRES_AT,
    },
}


def _valid_entry(raw, *, now: float) -> bool:
    if not isinstance(raw, Mapping):
        return False
    source = raw.get('source_url')
    if not isinstance(source, str) or len(source) > 500:
        return False
    try:
        url = urlsplit(source)
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            return False
    except ValueError:
        return False
    observed = raw.get('verified_at')
    until = raw.get('expires_at')
    if (type(observed) not in (int,float) or type(until) not in (int,float)
            or not 0 < observed <= now + 60 or not observed < until or until <= now
            or until - observed > 31 * 86400):
        return False
    feats = raw.get('features')
    if not isinstance(feats, (set,frozenset,tuple,list)) or not set(feats) <= NATIVE_FEATURES:
        return False
    for key in ('context_limit','output_limit'):
        number=raw.get(key)
        if number is not None and (type(number) is not int or number < 1 or number > 2_000_000):
            return False
    return True


def evidence(provider: str, model: str, *, now: float | None = None) -> dict | None:
    """Return a bounded COPY of current exact-model claims, never mutable registry data."""
    current = time.time() if now is None else now
    raw = CATALOG.get((provider,model))
    if not _valid_entry(raw, now=current):
        return None
    return {'features':frozenset(raw['features']), 'context_limit':raw.get('context_limit'),
            'output_limit':raw.get('output_limit')}


def check(provider: str, model: str, *, native_features=frozenset(),
          min_context_tokens: int | None = None, requested_output: int | None = None,
          now: float | None = None) -> dict:
    """Fail closed for *advanced* requirements; baseline validator text is unchanged."""
    requested = frozenset(native_features)
    if not requested <= NATIVE_FEATURES:
        raise ValueError('Bilinmeyen native model özelliği.')
    if min_context_tokens is not None and (
            type(min_context_tokens) is not int or not 1 <= min_context_tokens <= 2_000_000):
        raise ValueError('min_context_tokens geçersiz.')
    raw = evidence(provider,model,now=now)
    if (requested or min_context_tokens is not None) and raw is None:
        return {'ok':False,'reason_code':'MODEL_CAPABILITY_EVIDENCE_MISSING',
                'reason':'Modelin gelişmiş özelliği veya context uzunluğu doğrulanmamış.'}
    if raw is not None:
        if not requested <= raw['features']:
            return {'ok':False,'reason_code':'MODEL_NATIVE_FEATURE_UNSUPPORTED',
                    'reason':'Seçilen model için istenen yerel API özelliği doğrulanmamış.'}
        if min_context_tokens is not None and (
                raw['context_limit'] is None or raw['context_limit'] < min_context_tokens):
            return {'ok':False,'reason_code':'MODEL_CONTEXT_LIMIT_UNVERIFIED',
                    'reason':'Gereken context penceresi bu model için doğrulanmamış.'}
        if requested_output is not None and raw['output_limit'] is not None                 and requested_output > raw['output_limit']:
            return {'ok':False,'reason_code':'MODEL_OUTPUT_LIMIT_EXCEEDED',
                    'reason':'İstenen çıktı üst sınırı doğrulanmış model sınırını aşıyor.'}
    return {'ok':True,'features':frozenset() if raw is None else raw['features'],
            'context_limit':None if raw is None else raw['context_limit']}
