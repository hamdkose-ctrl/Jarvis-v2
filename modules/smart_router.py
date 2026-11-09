"""Budget-aware task routing. Paid providers never belong to the automatic pool."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
import json
from pathlib import Path
import re
import threading
import time
import requests
from config import DATA_DIR, load_settings, save_settings
from modules import privacy, provider_privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.RLock()
_HEALTH = {}
_LAST = {}
_STORE = DATA_DIR / 'router'
_CLOUD_PROVIDERS = frozenset({'gemini', 'groq', 'cloudflare'})
_EVIDENCE_MODELS_MAX = 32
# Route class of a request is decided by its provenance (privacy_sources); callers never pick a provider.
# Vision still keeps its legacy order until the image path moves to the router chains (P0-3c).
_DEFAULT_ROUTE = provider_privacy.ROUTE_PRIVATE_GENERAL


# Routing is deliberately based on the caller's declared contract, never on words in
# the prompt.  ``selection`` remains as a compatibility/status surface; new model
# calls enter through ``run_request`` below.
@dataclass(frozen=True)
class ModelRequest:
    owner: str
    request_id: str = ''
    needs_call: bool = True
    features: frozenset[str] = frozenset({'text'})
    # These advanced claims require a time-bound, developer-maintained exact-model
    # evidence record; legacy structured_output only means app-side validation.
    native_features: frozenset[str] = frozenset()
    min_context_tokens: int | None = None
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int = 2000
    deadline: float | None = None
    cancelled: Any = None
    route: str | None = None
    exclude_providers: frozenset[str] = frozenset()
    max_network_attempts: int = 2


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    context_limit: int | None = None
    output_limit: int | None = None
    features: frozenset[str] = frozenset({'text'})
    usage_class: str = 'free'


@dataclass(frozen=True)
class RoutePlan:
    candidates: tuple[ModelSpec, ...]
    skipped: tuple[dict, ...]
    max_network_attempts: int


@dataclass
class RouteResult:
    text: str
    model: ModelSpec
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    attempts: list[dict] = field(default_factory=list)


class ProviderAdapter(Protocol):
    """Transport boundary: it receives a decided model and may make one request only."""
    def __call__(self, spec: ModelSpec) -> str: ...


def owner_path(owner):
    if not owner or not re.fullmatch(r'[\w-]{1,100}', owner):
        raise ValueError('Kullanıcı geçersiz.')
    return _STORE / (owner + '.json')


def _safe_evidence_catalog(value) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for provider, models in value.items():
        if provider not in _CLOUD_PROVIDERS or not isinstance(models, dict):
            continue
        safe_models = {}
        for model, row in list(models.items())[:_EVIDENCE_MODELS_MAX]:
            if not isinstance(model, str) or not model or len(model) > 120 or not isinstance(row, dict):
                continue
            safe_models[model] = dict(row)
        if safe_models:
            out[provider] = safe_models
    return out


_STATE_KEYS = ('cloud_free_confirmed', 'free_tier_evidence')


def _read_state(owner):
    """Parsed state dict, {} when the file is missing, None when it is unreadable (corrupt or not a dict)."""
    try:
        state = json.loads(owner_path(owner).read_text(encoding='utf-8'))
    except OSError:
        return {}
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _purge_legacy(owner, state=None):
    """Keep only the known state keys on disk: a removed provider's stored key, model and evidence rows go away.
    Runs under the lock on a fresh read, so a concurrent ``configure`` write is never overwritten by a stale copy."""
    with _LOCK:
        state = _read_state(owner)
        if state is None:
            return _reset_unreadable(owner)
        evidence = state.get('free_tier_evidence')
        stale = isinstance(evidence, dict) and any(name not in _CLOUD_PROVIDERS for name in evidence)
        if not stale and all(name in _STATE_KEYS for name in state):
            return
        clean = {k: v for k, v in state.items() if k in _STATE_KEYS}
        if isinstance(evidence, dict):
            clean['free_tier_evidence'] = _safe_evidence_catalog(evidence)
        try:
            _save_state(owner, clean)
        except OSError:
            _record_failure('modules/smart_router.py:_purge_legacy')


def _reset_unreadable(owner):
    """A corrupt or non-dict state file can still hold a removed provider's key. It can not be parsed, and a
    backup would keep the secret, so it is replaced by the fail-closed default (the owner re-confirms).
    Re-checked under the lock: a file another writer has just made valid is left alone."""
    with _LOCK:
        if _read_state(owner) is not None:
            return
        try:
            _save_state(owner, {'cloud_free_confirmed': False, 'free_tier_evidence': {}})
        except OSError:
            _record_failure('modules/smart_router.py:_reset_unreadable')


def settings(owner):
    defaults={'cloud_free_confirmed':False,'free_tier_evidence':{}}
    state=_read_state(owner)
    if state is None:
        _reset_unreadable(owner)
        return defaults
    if state:
        _purge_legacy(owner)
        state=_read_state(owner) or {}
    return {'cloud_free_confirmed':state.get('cloud_free_confirmed') is True,
            'free_tier_evidence':_safe_evidence_catalog(state.get('free_tier_evidence'))}


def _save_state(owner, state):
    path = owner_path(owner); path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(state), encoding='utf-8'); tmp.replace(path)


def configure(owner, cloud_free_confirmed=None):
    with _LOCK:
        state = settings(owner)
        if cloud_free_confirmed is not None:
            state['cloud_free_confirmed'] = bool(cloud_free_confirmed)
        _save_state(owner, state)
        return status(owner)


def set_free_tier_evidence(owner, *, provider, model, free_tier_verified, source, evidence_ref,
                           verified_at, ttl_seconds, eligibility, quota_state='unknown',
                           quota_remaining=None, hard_stop_guaranteed=False,
                           verification_status='unknown', reason=''):
    """Store bounded provider/model free-tier evidence in the existing per-owner router state.

    This function does not contact a provider and does not infer that a plan is free. The caller must
    supply provenance. TTL expiry is checked lazily at routing time; stale evidence never auto-allows.
    """
    provider = str(provider or '').strip().casefold()
    model = str(model or '').strip()
    if provider not in _CLOUD_PROVIDERS:
        raise ValueError('Free-tier evidence yalnız mevcut cloud sağlayıcıları için kaydedilebilir.')
    if not model or len(model) > 120:
        raise ValueError('Evidence model adı geçersiz.')
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise ValueError('Evidence kaynağı gerekli.')
    if not isinstance(evidence_ref, str) or not evidence_ref.strip() or len(evidence_ref) > 500:
        raise ValueError('Evidence referansı gerekli.')
    if type(verified_at) not in (int, float) or verified_at <= 0:
        raise ValueError('verified_at geçersiz.')
    if type(ttl_seconds) not in (int, float) or ttl_seconds <= 0 or ttl_seconds > 31 * 86400:
        raise ValueError('Evidence TTL geçersiz.')
    if eligibility not in {'eligible', 'not_eligible', 'unknown'}:
        raise ValueError('Evidence eligibility geçersiz.')
    if quota_state not in {'available', 'exhausted', 'not_reported', 'unknown'}:
        raise ValueError('Evidence quota_state geçersiz.')
    if quota_remaining is not None and (type(quota_remaining) not in (int, float) or quota_remaining < 0):
        raise ValueError('Evidence quota_remaining geçersiz.')
    if type(hard_stop_guaranteed) is not bool or type(free_tier_verified) is not bool:
        raise ValueError('Evidence boolean alanı geçersiz.')
    if verification_status not in {'verified', 'unknown', 'rejected'}:
        raise ValueError('Evidence verification_status geçersiz.')
    if not isinstance(reason, str):
        raise ValueError('Evidence reason geçersiz.')
    row = {
        'provider': provider,
        'model': model,
        'free_tier_verified': free_tier_verified,
        'source': source.strip(),
        'evidence_ref': evidence_ref.strip(),
        'verified_at': float(verified_at),
        'expires_at': float(verified_at + ttl_seconds),
        'ttl_seconds': float(ttl_seconds),
        'eligibility': eligibility,
        'quota_state': quota_state,
        'quota_remaining': quota_remaining,
        'hard_stop_guaranteed': hard_stop_guaranteed,
        'verification_status': verification_status,
        'reason': reason.strip()[:300],
    }
    with _LOCK:
        state = settings(owner)
        catalog = _safe_evidence_catalog(state.get('free_tier_evidence'))
        catalog.setdefault(provider, {})[model] = row
        state['free_tier_evidence'] = catalog
        _save_state(owner, state)
    return dict(row)


def free_tier_evidence(owner, provider, model):
    state = settings(owner)
    row = state.get('free_tier_evidence', {}).get(provider, {}).get(model)
    return dict(row) if isinstance(row, dict) else None


def _evidence_gate(owner, provider, model, *, route=None, now=None):
    """Strict zero-cost gate. UNKNOWN is never ALLOW.

    Two independent proofs are required: the provider-level privacy bundle (code, expiring, never
    user-written; ``route`` narrows it) and the per-owner/model free-tier evidence below.
    """
    privacy_gate = provider_privacy.privacy_gate(provider, route, now=now)
    if not privacy_gate['ok']:
        return {'ok':False,'reason_code':privacy_gate['reason_code'],'reason':privacy_gate['reason']}
    row = free_tier_evidence(owner, provider, model)
    if not row or row.get('free_tier_verified') is not True or row.get('verification_status') != 'verified' \
            or not row.get('source') or not row.get('evidence_ref'):
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_EVIDENCE_MISSING',
                'reason':'Geçerli ücretsiz katman kanıtı yok; yeniden doğrulama gerekli.'}
    verified_at, expires_at = row.get('verified_at'), row.get('expires_at')
    if type(verified_at) not in (int, float) or type(expires_at) not in (int, float):
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_EVIDENCE_MISSING',
                'reason':'Ücretsiz katman kanıtının doğrulama zamanı eksik.'}
    if expires_at <= (time.time() if now is None else now):
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_EVIDENCE_STALE',
                'reason':'Ücretsiz katman kanıtının süresi geçmiş; yeniden doğrulama gerekli.'}
    if row.get('eligibility') != 'eligible':
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_NOT_ELIGIBLE',
                'reason':'Bu kullanıcı/model doğrulanmış ücretsiz katman için uygun değil veya uygunluğu bilinmiyor.'}
    if row.get('hard_stop_guaranteed') is not True:
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_HARD_STOP_UNVERIFIED',
                'reason':'Kota bitince ücretlendirmeyi engelleyen hard-stop kanıtı doğrulanmamış.'}
    quota_state = row.get('quota_state')
    remaining = row.get('quota_remaining')
    if quota_state == 'exhausted' or remaining == 0:
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_QUOTA_EXHAUSTED',
                'reason':'Doğrulanmış ücretsiz kota tükenmiş; sıradaki ücretsiz rota denenmeli.'}
    if quota_state not in {'available', 'not_reported'}:
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_QUOTA_UNKNOWN',
                'reason':'Ücretsiz kota durumu bilinmiyor; strict zero-cost modunda yeniden doğrulama gerekli.'}
    return {'ok':True,'reason_code':None,'reason':'Doğrulanmış ücretsiz katman evidence geçerli.','evidence':row}


def task_type(prompt, image=False):
    if image: return 'vision'
    p = prompt.casefold()
    if re.search(r'kod|python|javascript|hata|debug|fonksiyon|geliştir|refactor', p): return 'code'
    if len(prompt) > 10000 or re.search(r'belge|pdf|analiz|karşılaştır|araştır|rapor', p): return 'analysis'
    return 'chat'


def _skip(provider, reason, reason_code, seconds=0, model=''):
    row = {'provider':provider,'reason':reason,'reason_code':reason_code,'seconds':seconds}
    if model:
        row['model'] = model
    return row


def _route_of(route):
    return route if route in provider_privacy.ROUTES else _DEFAULT_ROUTE


def selection(owner,task,route=None):
    from modules import llm, cloudflare_chat, usage_meter
    route=_route_of(route)
    if privacy.mode()=='yerel':
        return {'candidates':['ollama'],'skipped':[
            _skip(p,'Yerel modda bulut kapalı','PROVIDER_LOCAL_MODE') for p in ('gemini','groq','cloudflare')]}
    state=settings(owner)
    if task=='vision':
        order,gate_route=['ollama'],_DEFAULT_ROUTE   # görüntü özel: yalnız yerel
    else:
        order,gate_route=list(provider_privacy.CHAINS[route]),route
    models={'gemini':llm.active_model(owner),'groq':llm.groq_model(),'cloudflare':cloudflare_chat.MODEL}
    selected=[];skipped=[]
    for provider in ('gemini','groq','cloudflare','ollama'):
        reason=None;reason_code=None;seconds=0;model=models.get(provider,'')
        if provider not in order:
            reason='Bu istek türü için izinli değil';reason_code='PROVIDER_ROUTE_NOT_ALLOWED'
        elif provider!='ollama' and not state.get('cloud_free_confirmed'):
            reason='Ücretsiz hesap onayı yok';reason_code='PROVIDER_FREE_ACCOUNT_UNCONFIRMED'
        elif provider=='gemini' and not llm.user_key(owner):
            reason='Bu kullanıcı için API anahtarı eksik';reason_code='PROVIDER_CONFIGURATION_REQUIRED'
        elif provider=='groq' and not llm.user_groq_key(owner):
            reason='Bu kullanıcı için API anahtarı eksik';reason_code='PROVIDER_CONFIGURATION_REQUIRED'
        elif provider=='cloudflare' and not cloudflare_chat.configured(owner):
            reason='Bu kullanıcı için Cloudflare hesap/anahtar eksik';reason_code='PROVIDER_CONFIGURATION_REQUIRED'
        elif provider!='ollama':
            gate=_evidence_gate(owner,provider,model,route=gate_route)
            if not gate['ok']:
                reason=gate['reason'];reason_code=gate['reason_code']
        if reason is None and provider != 'ollama':
            observed = usage_meter.observed_exhaustion(owner, provider, model, now=time.time())
            if observed:
                seconds = observed['seconds']
                reason = ('Sağlayıcının son görülen rate-limit başlığı tükendi; ' +
                          str(seconds) + ' saniye sonra yeniden değerlendirilecek')
                reason_code = 'PROVIDER_OBSERVED_QUOTA_EXHAUSTED'
        if reason is None:
            with _LOCK:seconds=max(0,int(_HEALTH.get((owner,provider),{}).get('until',0)-time.monotonic()+.999))
            if seconds:
                reason='Önceki başarısız çağrı nedeniyle '+str(seconds)+' saniye beklemede';reason_code='PROVIDER_COOLDOWN'
        if reason:skipped.append(_skip(provider,reason,reason_code,seconds,model))
        else:selected.append(provider)
    return {'candidates':[p for p in order if p in selected],'skipped':skipped}


def wait_seconds(owner, task='analysis', route=None):
    """Hiç uygun sağlayıcı kalmadıysa ve en az biri bekleme (kota/hata) içindeyse kalan en kısa saniye; yoksa 0."""
    row = selection(owner, task, route)
    if row['candidates']:
        return 0
    waits = [int(item.get('seconds') or 0) for item in row['skipped'] if item.get('seconds')]
    return min(waits) if waits else 0


def candidates(owner, task, route=None):
    return selection(owner,task,route)['candidates']


def failure_kind(exc):
    from modules import failure_policy
    return failure_policy.legacy_kind(exc)


def failure_status(exc):
    from modules import failure_policy
    return failure_policy.status_code(exc)


def failure_detail(attempt):
    reason = {'key':'kimlik/erişim reddedildi', 'quota':'kota veya hız sınırı'}.get(attempt.get('kind'), 'çağrı başarısız')
    if attempt.get('hint') == 'ollama_missing':
        from modules import llm
        label = llm.local_label()
        reason = ('Ollama yüklü değil ya da çalışmıyor (ollama.com adresinden kurup `ollama serve` ile başlat)' if label == 'Ollama'
                  else label + ' yerel sunucusu çalışmıyor (modeli yükleyip sunucuyu başlat)')
    error = attempt.get('error', '')
    if error in ('Timeout', 'ReadTimeout', 'ConnectTimeout', 'TimeoutError'):
        reason = 'zaman aşımı'
    elif error in ('ConnectionError', 'ConnectionRefusedError', 'ConnectionAbortedError'):
        reason = 'bağlantı kurulamadı veya kesildi'
    code = attempt.get('status')
    return attempt['provider'] + ': ' + reason + ' (' + error + (f', HTTP {code}' if code else '') + ')'


def failure_text(exc):
    from modules import failure_policy
    return failure_policy.short_text(exc)


def cooldown(provider, exc):
    from modules import failure_policy
    return failure_policy.cooldown_seconds(provider, exc)


def _model_for(owner: str, provider: str) -> str:
    """Resolve a model after the provider was admitted; no prompt inspection here."""
    from modules import llm, cloudflare_chat
    if provider == 'gemini':
        return llm.active_model(owner)
    if provider == 'groq':
        return llm.groq_model()
    if provider == 'cloudflare':
        return cloudflare_chat.MODEL
    if provider == 'ollama':
        # The local backend owns effective-model discovery.  The router must not
        # turn an unavailable model into an invented fallback.
        return llm._ollama_effective_model(llm.provider_configuration(), refresh_missing=False)
    return ''


def plan(request: ModelRequest) -> RoutePlan:
    """Make the complete, observable route plan without performing network I/O."""
    if not request.needs_call:
        return RoutePlan((), (), 0)
    from modules import model_capabilities
    # Reject malformed requirements before discovering or contacting any model.
    model_capabilities.check('', '', native_features=request.native_features,
                             min_context_tokens=request.min_context_tokens)
    if request.max_network_attempts < 1 or request.max_network_attempts > 2:
        raise ValueError('Toplam ağ denemesi 1 veya 2 olmalı.')
    unknown = set(request.exclude_providers) - (_CLOUD_PROVIDERS | {'ollama'})
    if unknown:
        raise ValueError('Router dışlama kümesinde bilinmeyen sağlayıcı var.')
    # Vision is an explicitly declared feature, not a prompt classification.
    task = 'vision' if 'vision' in request.features else 'text'
    chosen = selection(request.owner, task, request.route)
    specs = []
    skipped = list(chosen['skipped'])
    for provider in chosen['candidates']:
        if provider in request.exclude_providers:
            skipped.append(_skip(provider, 'Bu çağrı için sağlayıcı dışlandı', 'PROVIDER_CALLER_EXCLUDED'))
            continue
        try:
            model = _model_for(request.owner, provider)
        except Exception:
            _record_failure('modules/smart_router.py:plan_model_discovery')
            # Model discovery itself is not a model invocation.  It remains a
            # transparent unavailable candidate rather than silently choosing one.
            skipped.append(_skip(provider, 'Kullanılabilir model doğrulanamadı', 'MODEL_UNAVAILABLE'))
            continue
        if not model:
            skipped.append(_skip(provider, 'Model yapılandırılmamış', 'MODEL_UNAVAILABLE'))
            continue
        # App-side schema validator is *not* native provider JSON schema support.
        features = frozenset({'text', 'structured_output'})
        if not request.features <= features | {'vision'}:
            skipped.append(_skip(provider, 'Model gerekli özelliği desteklemiyor',
                                 'MODEL_FEATURE_UNSUPPORTED', model=model))
            continue
        assessed = model_capabilities.check(
            provider, model, native_features=request.native_features,
            min_context_tokens=request.min_context_tokens,
            requested_output=request.max_output_tokens)
        if not assessed['ok']:
            skipped.append(_skip(provider, assessed['reason'], assessed['reason_code'], model=model))
            continue
        specs.append(ModelSpec(provider, model, context_limit=assessed['context_limit'],
                               output_limit=request.max_output_tokens,
                               features=features | assessed['features'],
                               usage_class='local' if provider == 'ollama' else 'free'))
    return RoutePlan(tuple(specs), tuple(skipped), request.max_network_attempts)



def _check_request(request: ModelRequest) -> None:
    """Enforce the canonical budget and per-request cancellation/deadline."""
    requests_state.check()
    if request.cancelled is not None:
        is_set = getattr(request.cancelled, 'is_set', None)
        if not callable(is_set):
            raise TypeError('cancelled must provide is_set()')
        if is_set():
            raise requests_state.Cancelled('Model isteği iptal edildi; yanıt uygulanmadı.')
    if request.deadline is not None and time.monotonic() >= request.deadline:
        raise requests_state.LocalDeadline('İstek süre bütçesi doldu; geç yanıt uygulanmadı.')


def run_request(request: ModelRequest, adapter: ProviderAdapter,
                *, validator: Callable[[str], Any] | None = None) -> RouteResult:
    """Execute a plan with one authority for retry, repair and fallback.

    Each adapter invocation is one real network attempt.  A schema rejection is
    recorded as an attempt and consumes the same two-attempt envelope as a retry
    or fallback.  Cooperative cancellation/deadline checks happen before and
    after every adapter return, so a late answer is never adopted.
    """
    _check_request(request)
    route_plan = plan(request)
    attempts: list[dict] = []
    started = time.monotonic()
    for spec in route_plan.candidates:
        if len(attempts) >= route_plan.max_network_attempts:
            break
        _check_request(request)
        try:
            text = adapter(spec)
            _check_request(request)
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Boş model yanıtı.')
            if validator is not None:
                validator(text)
            _check_request(request)
            attempts.append({'provider': spec.provider, 'model': spec.model, 'ok': True,
                             'seconds': round(time.monotonic() - started, 2)})
            with _LOCK:
                _LAST[request.owner] = {'task': 'declared', 'provider': spec.provider,
                                        'model': spec.model, 'attempts': attempts,
                                        'skipped': list(route_plan.skipped)}
                _HEALTH.pop((request.owner, spec.provider), None)
            return RouteResult(text, spec, duration_ms=round((time.monotonic()-started)*1000), attempts=attempts)
        except (requests_state.Cancelled, requests_state.LocalDeadline):
            raise
        except Exception as exc:
            _record_failure('modules/smart_router.py:run_request')
            transport = (exc.__cause__ if spec.provider == 'ollama'
                         and type(exc).__name__ == 'LocalModelError'
                         and isinstance(exc.__cause__, (requests.Timeout, requests.ConnectionError))
                         else None)
            classified = transport or exc
            row = {'provider': spec.provider, 'model': spec.model, 'ok': False,
                   'error': type(classified).__name__, 'kind': failure_kind(classified),
                   'status': failure_status(classified)}
            if spec.provider == 'ollama' and type(exc).__name__ == 'LocalModelError':
                from modules import llm
                if not isinstance(transport, requests.Timeout) and str(exc) == llm.local_hint():
                    row['hint'] = 'ollama_missing'
            attempts.append(row)
            if type(exc).__name__ != 'ImageCapabilityError':
                with _LOCK:
                    _HEALTH[(request.owner, spec.provider)] = {
                        'until': time.monotonic()+cooldown(spec.provider, exc), 'error': type(exc).__name__}
            from modules import llm
            llm.note_route(llm.provider_label(spec.provider) + ' ' + failure_text(classified) + ', sıradakine geçildi', False)
    with _LOCK:
        _LAST[request.owner] = {'task': 'declared', 'provider': None, 'attempts': attempts,
                                'skipped': list(route_plan.skipped)}
    from modules import failure_policy
    detail = '; '.join(failure_detail(row) for row in attempts) if attempts else 'Bu çağrıda denenecek sağlayıcı yok.'
    omitted = '; '.join(row['provider'] + ': ' + row['reason'] for row in route_plan.skipped)
    message = ('Uygun model en çok ' + str(route_plan.max_network_attempts) +
               ' deneme sınırında yanıt veremedi. ' + detail +
               (' Atlanan sağlayıcılar: ' + omitted + '.' if omitted else '') +
               ' Ücretli modele geçilmedi.')
    if not attempts:
        if any(row.get('reason_code') == 'PROVIDER_CONFIGURATION_REQUIRED'
               or 'anahtarı eksik' in str(row.get('reason', '')) for row in route_plan.skipped):
            raise failure_policy.ProviderExhaustedError(
                message, reason_code='PROVIDER_CONFIGURATION_REQUIRED', recovery_class='user_action_required')
        evidence_code = next((row.get('reason_code') for row in route_plan.skipped
                              if str(row.get('reason_code', '')).startswith('PROVIDER_FREE_TIER_')), None)
        if evidence_code:
            raise failure_policy.ProviderExhaustedError(
                message, reason_code=evidence_code, recovery_class='user_action_required')
    raise failure_policy.ProviderExhaustedError(message)


def run(owner, prompt, callback, image=False, route=None, *, exclude_providers=()):
    """Compatibility façade for legacy callers; all attempts still use ``run_request``."""
    request = ModelRequest(owner=owner, route=route,
        features=frozenset({'vision'}) if image else frozenset({'text'}),
        exclude_providers=frozenset(exclude_providers))
    return run_request(request, lambda spec: callback(spec.provider)).text


def status(owner):
    state = settings(owner)
    from modules import llm, usage_meter, cloudflare_chat
    with _LOCK:
        cooldowns={p:max(0,round(v['until']-time.monotonic())) for (u,p),v in _HEALTH.items() if u==owner and v['until']>time.monotonic()}
        last=_LAST.get(owner,{})
    def cloud_policy(provider, model, has_key, route):
        if not state.get('cloud_free_confirmed'):
            return 'Ücretsiz hesap onayı gerekli'
        if not has_key:
            return 'Ücretsiz hesap onaylı; bu kullanıcı için API anahtarı eksik'
        gate=_evidence_gate(owner,provider,model,route=route)
        if not gate['ok']:
            return 'Ücretsiz hesap onaylı; '+gate['reason']+' ['+gate['reason_code']+']'
        observed = usage_meter.observed_exhaustion(owner, provider, model, now=time.time())
        if observed:
            return f'Kanıtlı ücretsiz rota; son görülen kota tükendi, {observed["seconds"]} saniye beklemede'
        if provider in cooldowns:
            return f'Kanıtlı ücretsiz rota; son çağrı başarısız, {cooldowns[provider]} saniye beklemede'
        return 'Kanıtlı ücretsiz rota; evidence geçerli ve strict zero-cost seçimde kullanılabilir'
    gemini_model=llm.active_model(owner)
    groq_model=llm.groq_model()
    local_policy='Yerel; görüntü için ayrıca vision modeli gerekir'
    try:
        local_model=llm._ollama_effective_model(llm.provider_configuration(), refresh_missing=False)
    except llm.LocalModelError:
        local_model='—'
        local_policy='Yerel effective model doğrulanamadı; yerel sunucuyu ve kurulu modelleri kontrol et'
    table = [
      {'provider':'gemini','model':gemini_model,'tasks':['chat','code','analysis'],'policy':'Yalnız herkese açık araştırma; '+cloud_policy('gemini',gemini_model,bool(llm.user_key(owner)),provider_privacy.ROUTE_PUBLIC_RESEARCH)},
      {'provider':'groq','model':groq_model,'tasks':['chat','code','analysis'],'policy':cloud_policy('groq',groq_model,bool(llm.user_groq_key(owner)),provider_privacy.ROUTE_PRIVATE_GENERAL)},
      {'provider':'cloudflare','model':cloudflare_chat.MODEL,'tasks':['chat','code','analysis'],'policy':cloud_policy('cloudflare',cloudflare_chat.MODEL,cloudflare_chat.configured(owner),provider_privacy.ROUTE_PRIVATE_GENERAL)},
      {'provider':'ollama','model':local_model,'tasks':['chat','code','analysis'],'policy':local_policy},
      {'provider':'openai/anthropic','model':'Kullanıcının seçtiği','tasks':[],'policy':'Otomatik havuz dışında; yalnız elle seçim'}]
    return {'cloud_free_confirmed':bool(state.get('cloud_free_confirmed')),
            'capabilities':table,'last':last,'cooldowns':cooldowns,
            'free_tier_evidence':state.get('free_tier_evidence',{}),
            'observed_limits':usage_meter.limits(owner)}


def handle(owner, command):
    c = command.casefold().strip(' .!')
    if c in ('smart router aç','smart router\u2019ı aç','akıllı router aç','otomatik model seçimini aç'):
        from modules import llm
        llm.set_provider('auto'); return 'Smart Router açık. Göreve uygun kanıtlı ücretsiz havuz kullanılıyor.'
    if c in ('router durumu','model yetenekleri','smart router durumu'):
        s = status(owner)
        rows = ['| Sağlayıcı | Model | Görevler | Politika |','|---|---|---|---|']
        for r in s['capabilities']: rows.append('| '+ ' | '.join([r['provider'],r['model'],', '.join(r['tasks']),r['policy']])+' |')
        attempts = s['last'].get('attempts', [])
        trace = '\n'.join(failure_detail(a) if not a['ok'] else a['provider'] + ': yanıt alındı' for a in attempts)
        skipped='; '.join(row['provider']+': '+row['reason'] for row in s['last'].get('skipped',[]))
        summary=('Son seçim: '+str(s['last'].get('provider') or 'Yanıt alınamadı') if s['last'] else
                 'Bu süreçte bu kullanıcı için son çağrı kaydı yok; restart öncesi çağrı burada tutulmaz.')
        if trace:summary+='\nSon çağrı denemeleri:\n'+trace
        if skipped:summary+='\nAtlanan sağlayıcılar: '+skipped
        return summary+'\n\n'+'\n'.join(rows)
    return None
