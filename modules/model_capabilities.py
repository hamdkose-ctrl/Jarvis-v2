"""Developer-controlled, model-specific native feature evidence for Router plans.

No network calls, no user-editable capability claims. Only exact model IDs with
official source pages appear in the registry; native API features remain disabled
until their transport adapter is explicitly verified.
Unverified and unknown data cannot turn on native schemas, tool calling
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
#     'context_limit': 32768, 'output_limit': 4096, 'source_url': 'https://...'}
# Only context/output capacities are asserted. Although Groq docs describe
# native structured outputs, our transport has not implemented schema-bearing
# API requests, so NO native JSON/tool capability is advertised here.
CUSTOM_FREE_ACCOUNTS: dict[tuple, dict] = {}  # reviewed developer facts; never user claims
CATALOG: dict[tuple[str, str], dict] = {
    ('cloudflare','@cf/google/gemma-4-26b-a4b-it'):{
        # Adapter is text-only and caps output at4096. Official vision/tool
        # support is not advertised until that wire contract is implemented.
        'features':frozenset(),'context_limit':256000,'output_limit':4096,
        'source_url':'https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/',
    },
    ('gemini', 'gemini-3.5-flash-lite'): {
        'features': frozenset({'verified_vision'}),
        'context_limit': 1048576, 'output_limit': 65536,
        'source_url': 'https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite',
        # Official model card rechecked 14 Nov; the Gemini adapter's image-parts
        # transport is covered separately. No native schema/tool claim is made.
    },
    ('gemini', 'gemini-3.1-flash-lite-preview'): {
        # 22 Kasım: anlama gecikmesi ölçümü (aynı ~21,8k token istem, 3 çağrı):
        # medyan 1240 ms, sapma yok; 3.5-flash-lite aynı testte 1281 ms medyan ve
        # 5293 ms'lik kuyruk üretti. Görsel mod verified_vision: 160x80 PNG
        # ("42") bu modelle doğru okundu (llm._image_transport, 22 Kasım).
        'features': frozenset({'verified_vision'}),
        'context_limit': 1048576, 'output_limit': 65536,
        'source_url': 'https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite-preview',
    },
    ('gemini', 'gemini-3.5-flash'): {
        'features': frozenset(),
        'context_limit': 1048576, 'output_limit': 65536,
        'source_url': 'https://ai.google.dev/gemini-api/docs/models',
    },
    ('groq', 'openai/gpt-oss-120b'): {
        'features': frozenset(),
        'context_limit': 131072, 'output_limit': 65536,
        'source_url': 'https://console.groq.com/docs/model/openai/gpt-oss-120b',
    },
    ('groq', 'openai/gpt-oss-20b'): {
        'features': frozenset(),
        'context_limit': 131072, 'output_limit': 65536,
        'source_url': 'https://console.groq.com/docs/model/openai/gpt-oss-20b',
    },
}


def _valid_entry(raw) -> bool:
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
    feats = raw.get('features')
    if not isinstance(feats, (set,frozenset,tuple,list)) or not set(feats) <= NATIVE_FEATURES:
        return False
    for key in ('context_limit','output_limit'):
        number=raw.get(key)
        if number is not None and (type(number) is not int or number < 1 or number > 2_000_000):
            return False
    return True


def valid_custom_free_evidence(raw, *, now: float) -> bool:
    """Free-account eligibility depends on a time-bound account observation."""
    if not _valid_entry(raw):
        return False
    observed = raw.get('verified_at')
    until = raw.get('expires_at')
    return (type(observed) in (int, float) and type(until) in (int, float)
            and 0 < observed <= now + 60 and observed < until and now < until
            and until - observed <= 31 * 86400)


def evidence(provider: str, model: str) -> dict | None:
    """Return a copy of exact-model claims, never mutable registry data."""
    if provider=='ollama':return local_evidence(model)
    raw = CATALOG.get((provider,model))
    if not _valid_entry(raw):
        return None
    return {'features':frozenset(raw['features']), 'context_limit':raw.get('context_limit'),
            'output_limit':raw.get('output_limit')}


def check(provider: str, model: str, *, native_features=frozenset(),
          min_context_tokens: int | None = None, requested_output: int | None = None) -> dict:
    """Fail closed for *advanced* requirements; baseline validator text is unchanged."""
    requested = frozenset(native_features)
    if not requested <= NATIVE_FEATURES:
        raise ValueError('Bilinmeyen native model özelliği.')
    if min_context_tokens is not None and (
            type(min_context_tokens) is not int or not 1 <= min_context_tokens <= 2_000_000):
        raise ValueError('min_context_tokens geçersiz.')
    raw = evidence(provider,model)
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

# Runtime facts are a short-lived observation, never a model-name/checkbox guess.
_LOCAL_FACTS = {}


def refresh_local(model, config):
    from modules import llm,requests_state
    import requests
    requests_state.check()
    if config.get('backend','ollama')!='ollama':
        return {'ok':False,'reason':'Bu backend native vision yeteneğini doğrulayan bir bilgi uç noktası sunmuyor.'}
    endpoint=str(config['url']).rstrip('/')
    response=requests.post(endpoint+'/api/show',json={'model':model},timeout=llm.transport_timeouts(3,5),allow_redirects=False)
    response.raise_for_status()
    data=response.json()
    capabilities=data.get('capabilities') if isinstance(data,dict) else None
    if not isinstance(capabilities,list) or any(not isinstance(c,str) for c in capabilities):
        raise ValueError('Yerel runtime yetenek bilgisi doğrulanamadı.')
    facts={'features':frozenset({'verified_vision'}) if 'vision' in capabilities else frozenset(),
           'context_limit':None,'output_limit':None,'expires_at':time.time()+300}
    _LOCAL_FACTS[(endpoint,model)]=facts
    return {'ok':True,'model':model,'vision':'verified_vision' in facts['features'],'expires_at':facts['expires_at']}


def local_evidence(model):
    from modules import llm
    config=llm.provider_configuration()
    raw=_LOCAL_FACTS.get((str(config['url']).rstrip('/'),model))
    if not raw or raw['expires_at']<=time.time():return None
    return {k:raw[k] for k in ('features','context_limit','output_limit')}
