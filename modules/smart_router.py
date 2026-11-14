"""Budget-aware task routing. Paid providers never belong to the automatic pool."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from contextlib import contextmanager,ExitStack
from contextvars import ContextVar
from typing import Any, Callable, Protocol
import json
import hashlib
from pathlib import Path
import re
import threading
import time
import uuid
import requests
from config import DATA_DIR, load_settings, save_settings
from modules import privacy, provider_privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.RLock()
_HEALTH = {}
_STORE = DATA_DIR / 'router'
_CLOUD_PROVIDERS = frozenset({'gemini', 'groq', 'cloudflare'})
_EVIDENCE_MODELS_MAX = 32
# Route class of a request is decided by its provenance (privacy_sources); callers never pick a provider.
_DEFAULT_ROUTE = provider_privacy.ROUTE_PRIVATE_GENERAL
PROFILES = frozenset({'brain_understanding','conversation','public_research','long_worker',
                      'vision','local_only','custom_explicit'})
DATA_SCOPES = frozenset({'conversation','selected_content','public'})
WORK_CLASSES = frozenset({'interactive','background','explicit_custom'})
POLICY_VERSION = 'jarvis-router.v2'
_ROLE_EVALUATION=ContextVar('router_role_evaluation',default=None)


def _role_fingerprint():
    root=Path(__file__).resolve().parents[1]
    digest=hashlib.sha256()
    for name in ('smart_router.py','brain_model_understanding.py','brain_contracts.py','model_capabilities.py',
                 'provider_privacy.py','router_connections.py','provider_protocols.py','llm.py','router_quota.py'):
        digest.update((root/'modules'/name).read_bytes())
    digest.update((root/'tests/data/brain_output_diagnose_holdout.json').read_bytes())
    digest.update((root/'scripts/brain_output_diagnose_holdout.py').read_bytes())
    return digest.hexdigest()


@contextmanager
def qualification_session(owner,provider,model,connection_id=None):
    """Trusted manual corpus runner only: keep one exact candidate, never a Core permission."""
    token=_ROLE_EVALUATION.set((owner,provider,model,connection_id))
    try:yield
    finally:_ROLE_EVALUATION.reset(token)


def _brain_role_allowed(request,spec):
    if request.profile!='brain_understanding':return True
    target=(request.owner,spec.provider,spec.model,spec.connection_id)
    if _ROLE_EVALUATION.get()==target:return True
    from modules import router_quota
    return router_quota.role_qualified(request.owner,spec.provider,spec.model,spec.connection_id,
        fingerprint=_role_fingerprint(),binding=spec.binding or str(spec.connection_revision),directory=_STORE)


# Routing is deliberately based on the caller's declared contract, never on words in
# the prompt.  ``selection`` remains as a compatibility/status surface; new model
# calls enter through ``run_request`` below.
@dataclass(frozen=True)
class ModelRequest:
    owner: str
    request_id: str = ''
    call_id: str = ''
    profile: str = 'conversation'
    data_scope: str = 'conversation'
    work_class: str = 'interactive'
    connection_id: str | None = None
    selection_mode: str = 'configured'
    needs_call: bool = True
    features: frozenset[str] = frozenset({'text'})
    # These advanced claims require a time-bound, developer-maintained exact-model
    # evidence record; legacy structured_output only means app-side validation.
    native_features: frozenset[str] = frozenset()
    min_context_tokens: int | None = None
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int = 2000
    # Upper bound of provider input + maximum output tokens, furnished by a
    # trusted developer adapter; not inferred from user text or token estimates.
    token_budget: int | None = None
    cost_upper_bound_microusd: int | None = None
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
    binding: str = ''
    protocol: str = 'native'
    connection_id: str | None = None
    connection_revision: int | None = None


@dataclass(frozen=True)
class RoutePlan:
    candidates: tuple[ModelSpec, ...]
    skipped: tuple[dict, ...]
    max_network_attempts: int
    plan_id: str = field(default_factory=lambda:uuid.uuid4().hex)
    policy_version: str = POLICY_VERSION
    alternatives: tuple[ModelSpec,...] = ()


@dataclass
class RouteResult:
    text: str
    model: ModelSpec
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    attempts: list[dict] = field(default_factory=list)
    request_id: str = ''
    plan_id: str = ''
    finish_reason: str | None = None
    first_token_ms: int | None = None
    validation_status: str = 'text_complete'


@dataclass(frozen=True)
class AdapterResponse:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None


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


_STATE_KEYS = ('cloud_free_confirmed', 'free_tier_evidence', 'gemini_scopes','application_limits','account_scopes')
_APPLICATION_DEFAULTS={'daily_requests':200,'max_parallel':2,'interactive_reserved':1,'interactive_daily_reserve':20}


def _application_limits(value):
    if not isinstance(value,dict) or set(value)-set(_APPLICATION_DEFAULTS):raise ValueError('Uygulama model sınırları geçersiz.')
    out={**_APPLICATION_DEFAULTS,**value}
    if 'interactive_daily_reserve' not in value:out['interactive_daily_reserve']=min(20,out['daily_requests'])
    if (any(type(v) is not int for v in out.values()) or not 1<=out['daily_requests']<=500000
            or not 0<=out['interactive_daily_reserve']<=out['daily_requests']
            or not 1<=out['max_parallel']<=8 or not 0<=out['interactive_reserved']<out['max_parallel']):
        raise ValueError('Uygulama istek/eşzamanlılık sınırı geçersiz.')
    return out


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
    defaults={'cloud_free_confirmed':False,'free_tier_evidence':{},'gemini_scopes':[],
              'application_limits':dict(_APPLICATION_DEFAULTS),'account_scopes':{}}
    state=_read_state(owner)
    if state is None:
        _reset_unreadable(owner)
        return defaults
    if state:
        _purge_legacy(owner)
        state=_read_state(owner) or {}
    return {'cloud_free_confirmed':state.get('cloud_free_confirmed') is True,
            'free_tier_evidence':_safe_evidence_catalog(state.get('free_tier_evidence')),
            'gemini_scopes':[v for v in state.get('gemini_scopes',[]) if v in ('conversation','selected_content')]
                if isinstance(state.get('gemini_scopes'),list) else [],
            'application_limits':_application_limits(state.get('application_limits',{})),
            'account_scopes':dict(state.get('account_scopes',{})) if isinstance(state.get('account_scopes'),dict) else {}}


def _save_state(owner, state):
    path = owner_path(owner); path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(state), encoding='utf-8'); tmp.replace(path)


def configure(owner, cloud_free_confirmed=None, *, gemini_scopes=None,application_limits=None,account_scopes=None):
    with _LOCK:
        state = settings(owner)
        if cloud_free_confirmed is not None:
            state['cloud_free_confirmed'] = bool(cloud_free_confirmed)
        if gemini_scopes is not None:
            if not isinstance(gemini_scopes,list) or any(type(v) is not str or v not in ('conversation','selected_content') for v in gemini_scopes):
                raise ValueError('Gemini veri kapsamı geçersiz.')
            state['gemini_scopes']=sorted(set(gemini_scopes))
        if application_limits is not None:state['application_limits']=_application_limits(application_limits)
        if account_scopes is not None:
            if (not isinstance(account_scopes,dict) or set(account_scopes)-_CLOUD_PROVIDERS
                    or any(not isinstance(v,str) or not re.fullmatch(r'[\w.:-]{1,100}',v) for v in account_scopes.values())):
                raise ValueError('Hesap/proje kota kapsamı geçersiz.')
            state['account_scopes']=dict(account_scopes)
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
        'connection_fingerprint':_connection_fingerprint(owner,provider),
    }
    with _LOCK:
        state = settings(owner)
        catalog = _safe_evidence_catalog(state.get('free_tier_evidence'))
        catalog.setdefault(provider, {})[model] = row
        state['free_tier_evidence'] = catalog
        _save_state(owner, state)
    return dict(row)


def _connection_fingerprint(owner,provider):
    from modules import llm,cloudflare_chat
    if provider=='gemini':value=llm.user_key(owner)
    elif provider=='groq':value=llm.user_groq_key(owner)
    else:value=str(cloudflare_chat.user_cloudflare_account(owner) or '')+'|'+str(cloudflare_chat.user_cloudflare_token(owner) or '')
    return hashlib.sha256(str(value or '').encode()).hexdigest()


def confirm_free_account(owner,provider,*,free_plan_confirmed=False,no_paid_billing=False):
    """Explicit setup attestation + reviewed model terms, never a fictitious billing API check."""
    from modules import llm,cloudflare_chat
    if free_plan_confirmed is not True or no_paid_billing is not True:
        raise ValueError('Ücretsiz plan ve ücretli faturalama kapalı tercihi gerekli.')
    # Official pricing/model cards reviewed14Nov2026. Expiry belongs to those
    # facts, not an auto-renewed claim about the user's current account.
    expires=1795824000.0;now=time.time()
    if now>=expires:raise ValueError('Resmî ücretsiz model koşulları yeniden incelenmeli.')
    if provider=='gemini':
        models=[m for m in llm.model_names(owner) if m in ('gemini-3.5-flash-lite','gemini-3.5-flash')]
        has_key=bool(llm.user_key(owner));source='https://ai.google.dev/gemini-api/docs/pricing'
    elif provider=='groq':
        models=[m for m in llm.GROQ_MODELS if m in ('openai/gpt-oss-120b','openai/gpt-oss-20b','qwen/qwen3.8-27b')]
        has_key=bool(llm.user_groq_key(owner));source='https://console.groq.com/docs/rate-limits ; https://console.groq.com/docs/billing-faqs'
    elif provider=='cloudflare':
        models=[cloudflare_chat.MODEL];has_key=cloudflare_chat.configured(owner)
        source='https://developers.cloudflare.com/workers-ai/platform/pricing/'
    else:raise ValueError('Hazır ücretsiz sağlayıcı geçersiz.')
    if not has_key or not models:raise ValueError('Bu kullanıcıda anahtar veya incelenmiş exact model yok.')
    for model in models:
        old=free_tier_evidence(owner,provider,model) or {}
        if (old.get('verification_status')=='rejected' or old.get('eligibility')=='not_eligible'
                or old.get('quota_state')=='exhausted' or old.get('quota_remaining')==0):
            raise ValueError('Mevcut olumsuz hesap/kota kanıtı korunuyor; yeniden beyanla silinmedi.')
    configure(owner,True)
    for model in models:
        set_free_tier_evidence(owner,provider=provider,model=model,free_tier_verified=True,
            source='user-attested Free/no-paid-billing + reviewed official model terms (not account API verification)',
            evidence_ref=source,verified_at=now,ttl_seconds=min(7*86400,expires-now),eligibility='eligible',
            quota_state='not_reported',quota_remaining=None,hard_stop_guaranteed=True,verification_status='verified',
            reason='Account plan attested by this owner. Token/neuron remaining and exact project limits are not inferred.')
    return {'provider':provider,'models':models,'expires_at':min(now+7*86400,expires),
            'account_verification':'user_attested','quota_remaining':None}


def free_tier_evidence(owner, provider, model):
    state = settings(owner)
    row = state.get('free_tier_evidence', {}).get(provider, {}).get(model)
    return dict(row) if isinstance(row, dict) else None


def _evidence_gate(owner, provider, model, *, route=None, now=None, data_scope='conversation'):
    """Strict zero-cost gate. UNKNOWN is never ALLOW.

    Two independent proofs are required: the provider-level privacy bundle (code, expiring, never
    user-written; ``route`` narrows it) and the per-owner/model free-tier evidence below.
    """
    privacy_gate = provider_privacy.privacy_gate(provider, route, now=now,
        consent_scopes=settings(owner)['gemini_scopes'],data_scope=data_scope)
    if not privacy_gate['ok']:
        return {'ok':False,'reason_code':privacy_gate['reason_code'],'reason':privacy_gate['reason']}
    row = free_tier_evidence(owner, provider, model)
    if not row or row.get('free_tier_verified') is not True or row.get('verification_status') != 'verified' \
            or not row.get('source') or not row.get('evidence_ref'):
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_EVIDENCE_MISSING',
                'reason':'Geçerli ücretsiz katman kanıtı yok; yeniden doğrulama gerekli.'}
    if row.get('connection_fingerprint')!=_connection_fingerprint(owner,provider):
        return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_ACCOUNT_CHANGED',
                'reason':'Anahtar/hesap değişti; eski ücretsiz hesap kanıtı yeni bağlantıya taşınmadı.'}
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




def _skip(provider, reason, reason_code, seconds=0, model=''):
    row = {'provider':provider,'reason':reason,'reason_code':reason_code,'seconds':seconds}
    if model:
        row['model'] = model
    return row


def _route_of(route):
    return route if route in provider_privacy.ROUTES else _DEFAULT_ROUTE


def _health_key(owner,provider,model,*,connection_id=None,revision=None):
    from modules import llm
    # Key rotation/model/endpoint changes do not inherit another credential's fault.
    if connection_id:
        identity=connection_id+':'+str(revision)
    else:
        identity=_connection_fingerprint(owner,provider) if provider!='ollama' else hashlib.sha256(json.dumps(llm.provider_configuration(),sort_keys=True).encode()).hexdigest()
    return (owner,provider,model,identity)


def _health_wait(owner,provider,model,**connection):
    key=_health_key(owner,provider,model,**connection)
    auth=_health_key(owner,provider,'*',**connection)
    project=settings(owner)['account_scopes'].get(provider)
    quota=('project:'+project,provider,model,'quota') if project else key
    with _LOCK:
        return max(0,int(max(_HEALTH.get(k,{}).get('until',0) for k in (key,auth,quota))-time.monotonic()+.999))


def _failure_health_key(request,spec,error):
    from modules import failure_policy
    category=failure_policy.classify(error)
    project=settings(request.owner)['account_scopes'].get(spec.provider)
    if project and category in (failure_policy.RATE_LIMIT,failure_policy.QUOTA_EXHAUSTED):
        return ('project:'+project,spec.provider,spec.model,'quota')
    return _health_key(request.owner,spec.provider,'*' if category==failure_policy.AUTH or spec.provider=='ollama' else spec.model,
                       connection_id=spec.connection_id,revision=spec.connection_revision)


def selection(owner,task,route=None, *, data_scope='conversation'):
    from modules import llm
    with llm.owner_context(owner):return _selection(owner,task,route,data_scope=data_scope)


def _selection(owner,task,route=None, *, data_scope='conversation'):
    from modules import llm, cloudflare_chat, usage_meter
    route=_route_of(route)
    if privacy.mode() in ('yerel','gizli'):
        return {'candidates':['ollama'],'skipped':[
            _skip(p,'Yerel modda bulut kapalı','PROVIDER_LOCAL_MODE') for p in ('gemini','groq','cloudflare')]}
    state=settings(owner)
    if task=='vision':
        order,gate_route=['gemini','ollama'],_DEFAULT_ROUTE
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
            gate=_evidence_gate(owner,provider,model,route=gate_route,data_scope=data_scope)
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
            seconds=_health_wait(owner,provider,model)
            if seconds:
                reason='Önceki başarısız çağrı nedeniyle '+str(seconds)+' saniye beklemede';reason_code='PROVIDER_COOLDOWN'
        if reason:skipped.append(_skip(provider,reason,reason_code,seconds,model))
        else:selected.append(provider)
    return {'candidates':[p for p in order if p in selected],'skipped':skipped}


def wait_seconds(owner, task='long_worker', route=None):
    """Known wait only when the real typed plan has no usable candidate."""
    from modules import llm
    profile=task if task in PROFILES else 'long_worker'
    with llm.owner_context(owner):
        request=ModelRequest(owner=owner,profile=profile,route=route,data_scope='selected_content',
            work_class='background',selection_mode='local_only' if llm.provider()=='ollama' else 'configured')
        row=plan(request)
    if row.candidates:return 0
    waits=[int(item.get('seconds') or 0) for item in row.skipped if item.get('seconds')]
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
    from modules import failure_policy,llm
    if failure_policy.classify(exc)==failure_policy.QUOTA_EXHAUSTED:return 3600
    if failure_policy.classify(exc)==failure_policy.RATE_LIMIT:
        delay=getattr(exc,'retry_after',None)
        if delay is None and provider=='gemini':delay=llm._gemini_retry_after(exc)
        try:return max(1,min(86400,int(float(delay)))) if delay is not None else 300
        except (ValueError,TypeError):pass
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


def _binding(request,provider,model):
    from modules import llm,cloudflare_chat
    state=settings(request.owner)
    values={'owner':request.owner,'model':model,'selected':_model_for(request.owner,provider),
            'free':state['cloud_free_confirmed'],
            'evidence':state['free_tier_evidence'].get(provider,{}).get(model)}
    values['account_scope']=state['account_scopes'].get(provider)
    key=llm.user_key(request.owner) if provider=='gemini' else llm.user_groq_key(request.owner) if provider=='groq' else cloudflare_chat.user_cloudflare_token(request.owner) if provider=='cloudflare' else ''
    values['connection']=hashlib.sha256(str(key or '').encode()).hexdigest()
    if provider=='gemini':values['scopes']=state['gemini_scopes']
    return hashlib.sha256(json.dumps(values,sort_keys=True,allow_nan=False).encode()).hexdigest()


def _capability_admitted(request,spec,row=None):
    from modules import model_capabilities,router_connections
    assessed=model_capabilities.check(row['base_url'] if row else spec.provider,spec.model,
        native_features=request.native_features|({'verified_vision'} if 'vision' in request.features else set()),
        min_context_tokens=request.min_context_tokens,requested_output=request.max_output_tokens)
    if assessed['ok']:return True
    return bool(row and 'vision' in request.features and not request.native_features
        and request.min_context_tokens is None and router_connections.vision_ready(request.owner,row))


def _current_admission(request,spec):
    if spec.connection_id:
        from modules import router_connections
        try:
            row,_=router_connections.resolve(request.owner,spec.connection_id,revision=spec.connection_revision)
            return (row['model']==spec.model and request.data_scope in row.get('data_scopes',[])
                    and _brain_role_allowed(request,spec) and _capability_admitted(request,spec,row)
                    and not _health_wait(request.owner,spec.provider,spec.model,connection_id=spec.connection_id,revision=spec.connection_revision)
                    and (not row.get('free_pool') or router_connections.free_pool_eligible(request.owner,row))
                    and privacy.mode()!='gizli' and (privacy.mode()!='yerel' or router_connections.is_local(row['base_url'])))
        except (ValueError,OSError):return False
    if spec.provider!='ollama' and privacy.mode() in ('yerel','gizli'):
        return False
    if _health_wait(request.owner,spec.provider,spec.model):return False
    if not spec.binding:return True  # explicitly injected plans used by transport boundary tests
    if spec.binding!=_binding(request,spec.provider,spec.model) or not _capability_admitted(request,spec):return False
    if spec.provider=='ollama':return _brain_role_allowed(request,spec)
    chosen=selection(request.owner,'vision' if 'vision' in request.features else 'text',request.route,data_scope=request.data_scope)
    if spec.provider not in chosen['candidates'] or not _brain_role_allowed(request,spec):return False
    return _evidence_gate(request.owner,spec.provider,spec.model,route=_route_of(request.route),
                          data_scope=request.data_scope)['ok']


def _custom_plan(request):
    if request.selection_mode in ('free','local_only'):return None
    from modules import router_connections,model_capabilities
    rows=router_connections.records(request.owner)
    ident=request.connection_id
    if ident is None:
        matches=[r['id'] for r in rows.values() if r.get('enabled') and not r.get('free_pool') and r.get('role')==request.profile]
        if len(matches)>1:raise ValueError('Bu rol için birden fazla etkin özel bağlantı var.')
        ident=matches[0] if matches else None
    if ident is None:
        if request.profile=='custom_explicit':
            return RoutePlan((),(_skip('custom','Özel bağlantı seçilmedi.','PROVIDER_CONFIGURATION_REQUIRED'),),1)
        return None
    try:
        row,_secret=router_connections.resolve(request.owner,ident)
        if request.data_scope not in row.get('data_scopes',[]):raise ValueError('Özel API için bu veri kapsamı açık değil.')
        if request.profile!='custom_explicit' and row['role']!=request.profile:raise ValueError('Bağlantı bu role ait değil.')
        if privacy.mode()=='gizli' or (privacy.mode()=='yerel' and not router_connections.is_local(row['base_url'])):
            raise ValueError('Gizlilik modu özel bağlantıya izin vermiyor.')
        if request.max_output_tokens>row['max_output_tokens']:raise ValueError('Çağrı çıktı bütçesi özel bağlantı sınırını aşıyor.')
        assessed=model_capabilities.check(row['base_url'],row['model'],native_features=request.native_features |
            ({'verified_vision'} if 'vision' in request.features else set()),
            min_context_tokens=request.min_context_tokens,requested_output=request.max_output_tokens)
        if not assessed['ok'] and 'vision' in request.features and not request.native_features and request.min_context_tokens is None and router_connections.vision_ready(request.owner,row):
            assessed={'ok':True,'features':frozenset({'verified_vision'}),'context_limit':None}
        if not assessed['ok']:raise ValueError(assessed['reason'])
        spec=ModelSpec('custom',row['model'],context_limit=assessed['context_limit'],output_limit=request.max_output_tokens,
            features=frozenset({'text','structured_output'})|assessed['features'],usage_class=row['billing'],
            connection_id=ident,connection_revision=row['revision'],protocol=row['protocol'])
        if _health_wait(request.owner,spec.provider,spec.model,connection_id=ident,revision=row['revision']):raise ValueError('Bu bağlantı/model son hata nedeniyle beklemede.')
        if not _brain_role_allowed(request,spec):raise ValueError('Bu exact bağlantı/modelin Brain rolü canlı kabul bekliyor.')
        return RoutePlan((spec,),(),request.max_network_attempts)
    except (ValueError,OSError) as exc:
        return RoutePlan((),(_skip('custom',str(exc),'PROVIDER_CUSTOM_CONFIGURATION_REQUIRED'),),1)


def plan(request: ModelRequest) -> RoutePlan:
    from modules import llm
    owner_path(request.owner)
    with llm.owner_context(request.owner):return _plan_request(request)


def _plan_request(request: ModelRequest) -> RoutePlan:
    """Make the complete, observable route plan without performing network I/O."""
    if not request.needs_call:
        return RoutePlan((), (), 0)
    evaluation=_ROLE_EVALUATION.get()
    if request.profile=='brain_understanding' and evaluation is not None and evaluation[0]==request.owner:
        request=replace(request,connection_id=evaluation[3],selection_mode='configured' if evaluation[3]
                        else 'local_only' if evaluation[1]=='ollama' else 'free')
    from modules import model_capabilities
    # Reject malformed requirements before discovering or contacting any model.
    model_capabilities.check('', '', native_features=request.native_features,
                             min_context_tokens=request.min_context_tokens)
    if request.token_budget is not None and (
            type(request.token_budget) is not int
            or type(request.max_output_tokens) is not int
            or request.token_budget < request.max_output_tokens
            or request.token_budget > 2_000_000):
        raise ValueError('Toplam token üst sınırı geçersiz veya çıktı bütçesinden küçük.')
    if request.max_network_attempts < 1 or request.max_network_attempts > 2:
        raise ValueError('Toplam ağ denemesi 1 veya 2 olmalı.')
    unknown = set(request.exclude_providers) - (_CLOUD_PROVIDERS | {'ollama'})
    if unknown:
        raise ValueError('Router dışlama kümesinde bilinmeyen sağlayıcı var.')
    custom=_custom_plan(request)
    if custom is not None:return custom
    # Vision is an explicitly declared feature, not a prompt classification.
    if (request.profile not in PROFILES or request.data_scope not in DATA_SCOPES or request.work_class not in WORK_CLASSES
            or request.selection_mode not in ('configured','free','local_only')):
        raise ValueError('Router çağrı profili/veri kapsamı geçersiz.')
    task = 'vision' if 'vision' in request.features else 'text'
    chosen = selection(request.owner, task, request.route,data_scope=request.data_scope)
    if request.profile=='local_only' or request.selection_mode=='local_only':
        chosen={'candidates':[p for p in chosen['candidates'] if p=='ollama'],
                'skipped':chosen['skipped']}
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
            provider, model, native_features=request.native_features | ({'verified_vision'} if task=='vision' else set()),
            min_context_tokens=request.min_context_tokens,
            requested_output=request.max_output_tokens)
        if not assessed['ok']:
            skipped.append(_skip(provider, assessed['reason'], assessed['reason_code'], model=model))
            continue
        spec=ModelSpec(provider, model, context_limit=assessed['context_limit'],
                               output_limit=request.max_output_tokens,
                               features=features | assessed['features'],
                               usage_class='local' if provider == 'ollama' else 'free',
                               binding=_binding(request,provider,model))
        evaluation=_ROLE_EVALUATION.get()
        if request.profile=='brain_understanding' and evaluation is not None and evaluation!=(request.owner,provider,model,None):continue
        if not _brain_role_allowed(request,spec):
            skipped.append(_skip(provider,'Bu exact modelin Brain rolü canlı kabul bekliyor.','MODEL_ROLE_UNQUALIFIED',model=model));continue
        specs.append(spec)
    if request.profile!='local_only' and request.selection_mode!='local_only':
        from modules import router_connections
        for row in router_connections.records(request.owner).values():
            if not (row.get('enabled') and row.get('free_pool') and row['role']==request.profile):continue
            if not router_connections.free_pool_eligible(request.owner,row):
                skipped.append(_skip('custom','Özel ücretsiz havuz için hesap/model/veri kanıtı eksik.','CUSTOM_FREE_EVIDENCE_MISSING',model=row['model']));continue
            explicit=_custom_plan(replace(request,connection_id=row['id'],selection_mode='configured'))
            if explicit is not None:
                skipped.extend(explicit.skipped)
                index=next((i for i,s in enumerate(specs) if s.provider=='ollama'),len(specs))
                specs[index:index]=explicit.candidates
    return RoutePlan(tuple(specs[:2]), tuple(skipped), request.max_network_attempts,alternatives=tuple(specs[2:]))


def qualification_candidate(owner,*,connection_id=None,local=False):
    request=ModelRequest(owner=owner,profile='custom_explicit' if connection_id else 'conversation',
        connection_id=connection_id,selection_mode='configured' if connection_id else 'local_only' if local else 'free',
        data_scope='conversation',max_output_tokens=2048,features=frozenset({'text','structured_output'}))
    candidates=plan(request).candidates
    if not candidates:raise ValueError('Rol ölçümü için uygun exact bağlantı/model yok.')
    return candidates[0]



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


class ResponseValidationError(ValueError):
    """A received response did not satisfy the caller's application contract."""


def _run_request(request: ModelRequest, adapter: ProviderAdapter,
                *, validator: Callable[[str], Any] | None = None, attempts=None, record=None) -> RouteResult:
    """Execute a plan with one authority for retry, repair and fallback.

    Each adapter invocation is one real network attempt.  A schema rejection is
    recorded as an attempt and consumes the same two-attempt envelope as a retry
    or fallback.  Cooperative cancellation/deadline checks happen before and
    after every adapter return, so a late answer is never adopted.
    """
    from modules import router_quota
    _check_request(request)
    route_plan = plan(request)
    attempts = [] if attempts is None else attempts
    skipped_now = list(route_plan.skipped)
    if record is not None:
        record.update(plan_id=route_plan.plan_id,skipped=skipped_now,planned=[{'provider':s.provider,'model':s.model} for s in route_plan.candidates])
    started = time.monotonic()
    candidates=route_plan.candidates+route_plan.alternatives
    if len(candidates)==1 and validator is not None:candidates=candidates+candidates
    for spec in candidates:
        if len(attempts) >= route_plan.max_network_attempts:
            break
        with ExitStack() as admission_stack:
            _check_request(request)
            if not _current_admission(request,spec):
                skipped_now.append(_skip(spec.provider,'Bağlantı/veri izni değişti; gönderilmedi.','PROVIDER_ADMISSION_CHANGED',model=spec.model))
                continue
            attempt_id=request.call_id+':'+str(len(attempts)+1)
            try:
                admission_stack.enter_context(router_quota.admission(request,spec,directory=_STORE))
                if spec.connection_id:
                    router_quota.reserve_custom(request.owner,spec.connection_id,spec.connection_revision,directory=_STORE,attempt_id=attempt_id,cost_bound=request.cost_upper_bound_microusd,request=request)
                else:
                    router_quota.reserve(request.owner,spec.provider,spec.model,directory=_STORE,
                                         token_budget=request.token_budget,quota_scope=router_quota.account_scope(request,spec),
                                         application_limit=router_quota.request_ceiling(request),attempt_id=attempt_id)
            except (router_quota.ReservationUnavailable,router_quota.ReservationExhausted) as exc:
                # This skipped provider made no actual HTTP attempt. Never bypass a
                # configured limit merely because its local SQLite store is locked.
                skipped_now.append(_skip(spec.provider,str(exc),exc.reason_code,
                                         seconds=exc.retry_after,model=spec.model))
                continue
            _check_request(request)
            attempt_id=request.call_id+':'+str(len(attempts)+1)
            attempt={'provider':spec.provider,'model':spec.model,'attempt_id':attempt_id,'ok':False,'state':'started'}
            attempts.append(attempt)
            try:
                from modules import usage_meter
                with usage_meter.capture_attempt(request.owner,request.request_id,attempt_id) as measured:
                    response = adapter(spec)
                raw_usage=response.usage if isinstance(response,AdapterResponse) else measured['usage']
                attempt['usage']={k:raw_usage.get(k) if type(raw_usage.get(k)) is int and raw_usage[k]>=0 else None for k in ('input_tokens','output_tokens','reasoning_tokens','cached_tokens','total_tokens')}
                router_quota.reconcile(request.owner,attempt_id,raw_usage,directory=_STORE)
                _check_request(request)
                reported=response if isinstance(response,AdapterResponse) else AdapterResponse(response,
                    usage=dict(measured['usage']),finish_reason=measured['finish_reason'])
                text=reported.text
                if reported.finish_reason in ('length','max_tokens','MAX_TOKENS','incomplete'):
                    raise ResponseValidationError('Model yanıtı çıktı sınırında kesildi.')
                if not isinstance(text, str) or not text.strip():
                    raise ValueError('Boş model yanıtı.')
                usage={key:reported.usage.get(key) for key in ('input_tokens','output_tokens','reasoning_tokens','cached_tokens')}
                if reported.usage.get('total_tokens') is not None:usage['total_tokens']=reported.usage['total_tokens']
                if any(v is not None and (type(v) is not int or v<0) for v in usage.values()):
                    raise ResponseValidationError('Model kullanım sayacı geçersiz.')
                if validator is not None:
                    try:
                        validator(text)
                    except (requests_state.Cancelled, requests_state.LocalDeadline):
                        raise
                    except Exception as exc:
                        _record_failure('modules/smart_router.py:response_validation')
                        raise ResponseValidationError('Model yanıtı istenen sözleşmeyi karşılamadı.') from exc
                _check_request(request)
                attempt.update(ok=True,state='completed',seconds=round(time.monotonic()-started,2))
                with _LOCK:
                    _HEALTH.pop(_health_key(request.owner,spec.provider,spec.model,connection_id=spec.connection_id,revision=spec.connection_revision),None)
                return RouteResult(text, spec, usage=usage,duration_ms=round((time.monotonic()-started)*1000),
                                   attempts=attempts,request_id=request.request_id,plan_id=route_plan.plan_id,
                                   finish_reason=reported.finish_reason,validation_status='validated' if validator else 'text_complete')
            except (requests_state.Cancelled, requests_state.LocalDeadline) as exc:
                attempt.update(state='unknown',kind='cancelled' if isinstance(exc,requests_state.Cancelled) else 'local_timeout',error=type(exc).__name__)
                raise
            except Exception as exc:
                _record_failure('modules/smart_router.py:run_request')
                transport = (exc.__cause__ if spec.provider == 'ollama'
                             and type(exc).__name__ == 'LocalModelError'
                             and isinstance(exc.__cause__, (requests.Timeout, requests.ConnectionError))
                             else None)
                classified = transport or exc
                validation_error = isinstance(exc, ResponseValidationError)
                row = {'provider': spec.provider, 'model': spec.model, 'ok': False,'attempt_id':attempt_id,
                       'error': type(classified).__name__,
                       'kind': 'response_validation' if validation_error else failure_kind(classified),
                       'status': failure_status(classified)}
                if spec.provider == 'ollama' and type(exc).__name__ == 'LocalModelError':
                    from modules import llm
                    if not isinstance(transport, requests.Timeout) and str(exc) == llm.local_hint():
                        row['hint'] = 'ollama_missing'
                attempt.update(row,state='failed')
                if not validation_error and type(exc).__name__ != 'ImageCapabilityError':
                    with _LOCK:
                        _HEALTH[_failure_health_key(request,spec,exc)] = {
                            'until': time.monotonic()+cooldown(spec.provider, exc), 'error': type(exc).__name__}
                from modules import llm
                detail = 'yanıt sözleşmesini karşılamadı' if validation_error else failure_text(classified)
                llm.note_route(llm.provider_label(spec.provider) + ' ' + detail + ', sıradakine geçildi', False)
    from modules import failure_policy
    detail = '; '.join(failure_detail(row) for row in attempts) if attempts else 'Bu çağrıda denenecek sağlayıcı yok.'
    omitted = '; '.join(row['provider'] + ': ' + row['reason'] for row in skipped_now)
    message = ('Uygun model en çok ' + str(route_plan.max_network_attempts) +
               ' deneme sınırında yanıt veremedi. ' + detail +
               (' Atlanan sağlayıcılar: ' + omitted + '.' if omitted else '') +
               ' Ücretli modele geçilmedi.')
    if not attempts:
        if any(row.get('reason_code') == 'PROVIDER_CONFIGURATION_REQUIRED'
               or 'anahtarı eksik' in str(row.get('reason', '')) for row in skipped_now):
            raise failure_policy.ProviderExhaustedError(
                message, reason_code='PROVIDER_CONFIGURATION_REQUIRED', recovery_class='user_action_required')
        evidence_code = next((row.get('reason_code') for row in skipped_now
                              if str(row.get('reason_code', '')).startswith('PROVIDER_FREE_TIER_')), None)
        if evidence_code:
            raise failure_policy.ProviderExhaustedError(
                message, reason_code=evidence_code, recovery_class='user_action_required')
    raise failure_policy.ProviderExhaustedError(message)


def run_request(request: ModelRequest, adapter: ProviderAdapter,
                *, validator: Callable[[str], Any] | None = None) -> RouteResult:
    from modules import llm
    requests_state.request_identity(request.owner)
    with llm.owner_context(request.owner):return _run_owned_request(request,adapter,validator=validator)


def _run_owned_request(request: ModelRequest, adapter: ProviderAdapter,
                *, validator: Callable[[str], Any] | None = None) -> RouteResult:
    from modules import router_quota
    owner_path(request.owner)
    if request.profile not in PROFILES or request.data_scope not in DATA_SCOPES or request.work_class not in WORK_CLASSES:
        raise ValueError('Router çağrı profili/veri kapsamı geçersiz.')
    ident=request.request_id or requests_state.request_identity(request.owner) or uuid.uuid4().hex
    if not isinstance(ident,str) or not re.fullmatch(r'[\w.:-]{1,160}',ident):
        raise ValueError('Model istek kimliği geçersiz.')
    request=replace(request,request_id=ident,call_id=uuid.uuid4().hex)
    record={'request_id':ident,'call_id':request.call_id,'profile':request.profile,'policy_version':POLICY_VERSION,
            'attempts':[],'state':'started','updated':time.time(),'reservation':{'token_upper_bound':request.token_budget,'cost_upper_bound_microusd':request.cost_upper_bound_microusd}}
    router_quota.write_trace(request.owner,record,directory=_STORE)
    try:
        result=_run_request(request,adapter,validator=validator,attempts=record['attempts'],record=record)
        record.update(state='completed',usage=result.usage,plan_id=result.plan_id,
                      provider=result.model.provider,model=result.model.model,duration_ms=result.duration_ms,
                      finish_reason=result.finish_reason,validation_status=result.validation_status,first_token_ms=result.first_token_ms)
        return result
    except Exception as exc:
        _record_failure('modules/smart_router.py:request')
        record['state']='cancelled' if isinstance(exc,requests_state.Cancelled) else 'failed'
        record['error']=type(exc).__name__
        raise
    finally:
        record['updated']=time.time()
        router_quota.write_trace(request.owner,record,directory=_STORE)


def trace(owner,request_id):
    from modules import router_quota
    owner_path(owner)
    return router_quota.read_trace(owner,request_id,directory=_STORE)




def status(owner):
    from modules import llm
    with llm.owner_context(owner):return _status(owner)


def _status(owner):
    state = settings(owner)
    from modules import llm, usage_meter, cloudflare_chat,router_quota
    recent=router_quota.recent_traces(owner,directory=_STORE)
    last=recent[0] if recent else {}
    cooldowns={p:wait for p,m in [('gemini',llm.active_model(owner)),('groq',llm.groq_model()),('cloudflare',cloudflare_chat.MODEL)]
               if (wait:=_health_wait(owner,p,m))}
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
      {'provider':'gemini','model':gemini_model,'tasks':['chat','code','analysis'],'policy':'Konuşma/seçilmiş içerik owner iznine bağlı; '+cloud_policy('gemini',gemini_model,bool(llm.user_key(owner)),provider_privacy.ROUTE_PUBLIC_RESEARCH)},
      {'provider':'groq','model':groq_model,'tasks':['chat','code','analysis'],'policy':cloud_policy('groq',groq_model,bool(llm.user_groq_key(owner)),provider_privacy.ROUTE_PRIVATE_GENERAL)},
      {'provider':'cloudflare','model':cloudflare_chat.MODEL,'tasks':['chat','code','analysis'],'policy':cloud_policy('cloudflare',cloudflare_chat.MODEL,cloudflare_chat.configured(owner),provider_privacy.ROUTE_PRIVATE_GENERAL)},
      {'provider':'ollama','model':local_model,'tasks':['chat','code','analysis'],'policy':local_policy}]
    from modules import router_connections
    return {'cloud_free_confirmed':bool(state.get('cloud_free_confirmed')),
            'gemini_scopes':state['gemini_scopes'], 'policy_version':POLICY_VERSION,
            'application_limits':state['application_limits'],'account_scopes':state['account_scopes'],
            'custom_connections':router_connections.snapshot(owner),
            'connection_states':{'gemini':bool(llm.user_key(owner)),'groq':bool(llm.user_groq_key(owner)),'cloudflare':cloudflare_chat.configured(owner)},
            'profiles':[{'profile':p,'primary':'Gemini','fallback':'Uygun Groq / metin için Cloudflare / yeterli yerel'}
                        for p in ('brain_understanding','conversation','public_research','long_worker','vision')],
            'capabilities':table,'last':last,'traces':recent,'cooldowns':cooldowns,
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
                 'Bu kullanıcı için kayıtlı model çağrısı yok.')
        if trace:summary+='\nSon çağrı denemeleri:\n'+trace
        if skipped:summary+='\nAtlanan sağlayıcılar: '+skipped
        return summary+'\n\n'+'\n'.join(rows)
    return None
