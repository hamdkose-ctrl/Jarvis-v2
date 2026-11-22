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
from config import DATA_DIR
from modules import privacy, provider_privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.RLock()
_HEALTH = {}
_STORE = DATA_DIR / 'router'
_CLOUD_PROVIDERS = frozenset({'gemini', 'groq', 'cloudflare'})
# Route class of a request is decided by its provenance (privacy_sources); callers never pick a provider.
_DEFAULT_ROUTE = provider_privacy.ROUTE_PRIVATE_GENERAL
PROFILES = frozenset({'brain_understanding','conversation','public_research','long_worker',
                      'vision','local_only','custom_explicit','connection_test'})
DATA_SCOPES = frozenset({'conversation','selected_content','public'})
WORK_CLASSES = frozenset({'interactive','background','explicit_custom'})
POLICY_VERSION = 'jarvis-router.v2'
_ROLE_EVALUATION=ContextVar('router_role_evaluation',default=None)


_ROLE_FINGERPRINT_PATHS=(
    'modules/smart_router.py','modules/brain_model_understanding.py','modules/brain_contracts.py',
    'modules/model_capabilities.py','modules/provider_privacy.py','modules/router_connections.py',
    'modules/provider_protocols.py','modules/llm.py','modules/router_quota.py',
    'tests/data/brain_output_diagnose_holdout.json','scripts/brain_output_diagnose_holdout.py')


def _role_fingerprint(root=None):
    """Bind the Brain role to semantic code bytes only: CRLF/LF checkouts
    (git clone vs GitHub ZIP) must not silently revoke a live acceptance."""
    digest=hashlib.sha256()
    base=Path(root) if root is not None else Path(__file__).resolve().parents[1]
    for name in _ROLE_FINGERPRINT_PATHS:
        digest.update((base/name).read_bytes().replace(b'\r\n',b'\n'))
    return digest.hexdigest()


@contextmanager
def qualification_session(owner,provider,model,connection_id=None):
    """Trusted manual corpus runner only: keep one exact candidate, never a Core permission."""
    token=_ROLE_EVALUATION.set((owner,provider,model,connection_id))
    try:yield
    finally:_ROLE_EVALUATION.reset(token)


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
    deferred_local: bool = False


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


_GEMINI_SCOPES = frozenset({'conversation', 'selected_content'})


def _read_state(owner):
    """Parsed state dict, {} when the file is missing, None when it is unreadable (corrupt or not a dict)."""
    try:
        state = json.loads(owner_path(owner).read_text(encoding='utf-8'))
    except OSError:
        return {}
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def settings(owner):
    with _LOCK:
        state = _read_state(owner)
        raw = state.get('gemini_scopes') if state else None
        scopes = sorted({value for value in raw if isinstance(value, str) and value in _GEMINI_SCOPES}) if isinstance(raw, list) else []
        current = {'gemini_scopes': scopes}
        if state != current and state != {}:
            try:
                _save_state(owner, current)
            except OSError:
                _record_failure('modules/smart_router.py:settings_migration')
        return current


def _save_state(owner, state):
    path = owner_path(owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state), encoding='utf-8')
        tmp.replace(path)


def configure(owner, *, gemini_scopes):
    if not isinstance(gemini_scopes, list) or any(
        not isinstance(value, str) or value not in _GEMINI_SCOPES for value in gemini_scopes
    ):
        raise ValueError('Gemini veri kapsamı geçersiz.')
    _save_state(owner, {'gemini_scopes': sorted(set(gemini_scopes))})
    return {'gemini_scopes': sorted(set(gemini_scopes))}


def _connection_fingerprint(owner,provider):
    from modules import llm,cloudflare_chat
    if provider=='gemini':value=llm.user_key(owner)
    elif provider=='groq':value=llm.user_groq_key(owner)
    else:value=str(cloudflare_chat.user_cloudflare_account(owner) or '')+'|'+str(cloudflare_chat.user_cloudflare_token(owner) or '')
    return hashlib.sha256(str(value or '').encode()).hexdigest()


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
    with _LOCK:
        return max(0,int(max(_HEALTH.get(k,{}).get('until',0) for k in (key,auth))-time.monotonic()+.999))


def _failure_health_key(request,spec,error):
    from modules import failure_policy
    category=failure_policy.classify(error)
    return _health_key(request.owner,spec.provider,'*' if category==failure_policy.AUTH or spec.provider=='ollama' else spec.model,
                       connection_id=spec.connection_id,revision=spec.connection_revision)


def selection(owner,task,route=None, *, data_scope='conversation'):
    from modules import llm
    with llm.owner_context(owner):return _selection(owner,task,route,data_scope=data_scope)


def _ready_key_configured(owner, provider):
    from modules import llm, cloudflare_chat
    if provider == 'gemini':
        return bool(llm.user_key(owner))
    if provider == 'groq':
        return bool(llm.user_groq_key(owner))
    return cloudflare_chat.configured(owner)


def _ready_unavailable(owner, provider, model, order, route, data_scope, scopes):
    from modules import usage_meter
    if provider not in order:
        return _skip(provider, 'Bu istek türü için kullanılmıyor.', 'PROVIDER_ROUTE_NOT_ALLOWED', model=model)
    if not _ready_key_configured(owner, provider):
        return _skip(provider, 'Bu kullanıcı için API bağlantısı eksik.', 'PROVIDER_CONFIGURATION_REQUIRED', model=model)
    gate = provider_privacy.privacy_gate(provider, route, consent_scopes=scopes, data_scope=data_scope)
    if not gate['ok']:
        return _skip(provider, gate['reason'], gate['reason_code'], model=model)
    observed = usage_meter.observed_exhaustion(owner, provider, model, now=time.time(),
                                                credential=_connection_fingerprint(owner, provider))
    if observed:
        return _skip(provider, 'Sağlayıcının bildirdiği kota doldu.', 'PROVIDER_OBSERVED_QUOTA_EXHAUSTED',
                     observed['seconds'], model)
    seconds = _health_wait(owner, provider, model)
    if seconds:
        return _skip(provider, 'Önceki çağrı hatası nedeniyle bağlantı kısa süre beklemede.', 'PROVIDER_COOLDOWN',
                     seconds, model)
    return None


def _ready_route(task, route):
    if task == 'vision':
        return ('gemini', 'ollama'), _DEFAULT_ROUTE
    route = _route_of(route)
    return provider_privacy.CHAINS[route], route


def _selection(owner, task, route=None, *, data_scope='conversation'):
    if privacy.mode() in ('yerel', 'gizli'):
        return {'candidates': ['ollama'], 'skipped': [
            _skip(p, 'Yerel modda bulut kapalı', 'PROVIDER_LOCAL_MODE') for p in ('gemini', 'groq', 'cloudflare')]}
    from modules import llm, cloudflare_chat
    order, gate_route = _ready_route(task, route)
    scopes = settings(owner)['gemini_scopes']
    models = {'gemini': llm.active_model(owner), 'groq': llm.groq_model(), 'cloudflare': cloudflare_chat.MODEL}
    selected, skipped = [], []
    for provider, model in models.items():
        reason = _ready_unavailable(owner, provider, model, order, gate_route, data_scope, scopes)
        if reason:
            skipped.append(reason)
        else:
            selected.append(provider)
    local_wait = _health_wait(owner, 'ollama', '')
    if local_wait:
        skipped.append(_skip('ollama', 'Önceki çağrı hatası nedeniyle bağlantı kısa süre beklemede.',
                             'PROVIDER_COOLDOWN', local_wait))
    else:
        selected.append('ollama')
    return {'candidates': [provider for provider in order if provider in selected], 'skipped': skipped}


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
    reason = {'key':'kimlik/erişim reddedildi', 'quota':'kota veya hız sınırı',
              'request_limit':'bu isteğin boyutu model kapasitesini aşıyor; isteği küçült veya uygun model kullan'}.get(attempt.get('kind'), 'çağrı başarısız')
    if attempt.get('reason_code') == 'PROVIDER_QUOTA_EXHAUSTED':
        reason = 'sağlayıcı kotası doldu'
    if (attempt.get('kind') == 'request_limit' and type(attempt.get('limit')) is int
            and type(attempt.get('requested')) is int):
        reason += f" (bildirilen sınır {attempt['limit']}, istenen {attempt['requested']})"
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


def _binding(request, provider, model):
    from modules import llm
    identity = (llm.provider_configuration() if provider == 'ollama'
                else _connection_fingerprint(request.owner, provider))
    values = (request.owner, provider, model, identity)
    return hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()


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
                    and _capability_admitted(request,spec,row)
                    and not _health_wait(request.owner,spec.provider,spec.model,connection_id=spec.connection_id,revision=spec.connection_revision)
                    and (not row.get('free_pool') or router_connections.free_pool_eligible(request.owner,row))
                    and privacy.mode()!='gizli' and (privacy.mode()!='yerel' or router_connections.is_local(row['base_url'])))
        except (ValueError,OSError):return False
    if spec.provider != 'ollama' and privacy.mode() in ('yerel', 'gizli'):
        return False
    if not spec.binding:
        return not _health_wait(request.owner, spec.provider, spec.model)
    from modules import llm
    try:
        if spec.model != _model_for(request.owner, spec.provider):
            return False
    except (llm.LocalModelError, OSError, ValueError):
        return False
    if spec.binding != _binding(request, spec.provider, spec.model) or not _capability_admitted(request, spec):
        return False
    if spec.provider == 'ollama':
        return not _health_wait(request.owner, spec.provider, spec.model)
    order, route = _ready_route('vision' if 'vision' in request.features else 'text', request.route)
    scopes = settings(request.owner)['gemini_scopes']
    return _ready_unavailable(request.owner, spec.provider, spec.model, order, route, request.data_scope, scopes) is None


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
    deferred_local = False
    for provider in chosen['candidates']:
        if provider in request.exclude_providers:
            skipped.append(_skip(provider, 'Bu çağrı için sağlayıcı dışlandı', 'PROVIDER_CALLER_EXCLUDED'))
            continue
        if provider == 'ollama' and specs and task == 'text' and evaluation is None:
            deferred_local = True
            continue
        spec, reason = _ready_spec(request, provider, vision=task == 'vision')
        if reason:
            skipped.append(reason)
            continue
        if request.profile=='brain_understanding' and evaluation is not None and evaluation!=(request.owner,provider,spec.model,None):continue
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
    return RoutePlan(tuple(specs[:2]), tuple(skipped), request.max_network_attempts,
                     alternatives=tuple(specs[2:]), deferred_local=deferred_local)


def _ready_spec(request, provider, *, vision):
    """Resolve one ready model at the point where the route needs it."""
    from modules import model_capabilities

    try:
        model = _model_for(request.owner, provider)
    except Exception:
        _record_failure('modules/smart_router.py:plan_model_discovery')
        return None, _skip(provider, 'Kullanılabilir model doğrulanamadı', 'MODEL_UNAVAILABLE')
    if not model:
        return None, _skip(provider, 'Model yapılandırılmamış', 'MODEL_UNAVAILABLE')
    features = frozenset({'text', 'structured_output'})
    if not request.features <= features | {'vision'}:
        return None, _skip(provider, 'Model gerekli özelliği desteklemiyor',
                           'MODEL_FEATURE_UNSUPPORTED', model=model)
    required = request.native_features | ({'verified_vision'} if vision else set())
    assessed = model_capabilities.check(provider, model, native_features=required,
                                        min_context_tokens=request.min_context_tokens,
                                        requested_output=request.max_output_tokens)
    if not assessed['ok']:
        return None, _skip(provider, assessed['reason'], assessed['reason_code'], model=model)
    return ModelSpec(provider, model, context_limit=assessed['context_limit'],
                     output_limit=request.max_output_tokens, features=features | assessed['features'],
                     usage_class='local' if provider == 'ollama' else 'free',
                     binding=_binding(request, provider, model)), None


def qualification_candidate(owner,*,connection_id=None,local=False,provider=None):
    request=ModelRequest(owner=owner,profile='custom_explicit' if connection_id else 'conversation',
        connection_id=connection_id,selection_mode='configured' if connection_id else 'local_only' if local else 'free',
        data_scope='conversation',max_output_tokens=2048,features=frozenset({'text','structured_output'}))
    candidates=plan(request).candidates
    if provider is not None:candidates=[c for c in candidates if c.provider==provider]
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


def _rejected_before_generation(attempts, limit):
    """Recognize the ready-pool case where both providers refused generation."""
    if limit != 2 or len(attempts) != 2:
        return False
    first, second = attempts
    return (
        first.get('provider') == 'gemini' and first.get('kind') == 'quota' and first.get('status') == 429
        and second.get('provider') == 'groq' and second.get('kind') == 'request_limit' and second.get('status') == 413
    )


class _AttemptTimeout(RuntimeError):
    """Tek sağlayıcı denemesi kendi süre sınırını aştı; sıradaki sağlayıcı denenir.

    İstek bütçesi (requests_state.LocalDeadline) ile karıştırılmaz: burada tur
    iptal edilmez, yalnız yavaş sağlayıcı bırakılır. Sağlayıcı bu yüzden sağlık
    cezası almaz (geçici yavaşlık, kalıcı hata değil).
    """

    reason_code = 'PROVIDER_ATTEMPT_TIMEOUT'


def attempt_timeout_seconds() -> float | None:
    """Ayarlanabilir deneme sınırı; 0/boş ise kapalı (eski davranış)."""
    try:
        from config import load_settings
        raw = load_settings().get('attempt_timeout_s', 3.0)
    except Exception:
        return None
    if raw in (None, '', 0, '0', False):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if 0.5 <= value <= 20 else None


def _next_candidate_ready(request: ModelRequest, candidates, index: int) -> bool:
    """Sıradaki aday gerçekten kullanılabilir mi?

    Canlı hata (22 Kasım 13:31): 3 sn sınırı gemini'yi bıraktı, groq kota,
    cloudflare zaman aşımı verdi ve tur tamamen düştü. Yavaş sağlayıcı ancak
    YERİNE GEÇECEK sağlıklı bir aday varsa bırakılır.
    """
    if index + 1 >= len(candidates):
        return False
    nxt = candidates[index + 1]
    if not _ready_key_configured(request.owner, nxt.provider):
        return False
    if _health_wait(request.owner, nxt.provider, nxt.model):
        return False
    from modules import usage_meter
    if usage_meter.observed_exhaustion(request.owner, nxt.provider, nxt.model, now=time.time(),
                                       credential=_connection_fingerprint(request.owner, nxt.provider)):
        return False
    return True


def _call_with_attempt_timeout(request: ModelRequest, adapter: ProviderAdapter, *, enabled: bool):
    """Etkileşimli turda tek sağlayıcı denemesini sınırlar; alternatif yoksa beklemez."""
    # Kapsam bilerek dar: yalnız konuşma cevabı. Anlama (brain_understanding)
    # kendi 30 sn'lik bütçesini ve büyük istemini korur; uzun işler hiç kısılmaz.
    if not enabled or request.profile != 'conversation' or request.work_class != 'interactive':
        return adapter()
    limit = attempt_timeout_seconds()
    if limit is None:
        return adapter()
    from modules import requests_state
    kalan = requests_state.budget_remaining()
    if kalan is not None and kalan <= limit + 0.25:
        return adapter()          # dış bütçe zaten daha sıkı; onu bozmayız
    import requests as _requests
    basladi = time.monotonic()
    try:
        with requests_state.budget(limit):
            return adapter()
    except requests_state.Cancelled:
        raise
    except requests_state.LocalDeadline as exc:
        # Yalnız GERÇEKTEN bizim deneme sınırımız dolduysa yavaş sağlayıcı bırakılır.
        # Dış istek bütçesinden gelen iptal/zaman aşımı aynen yukarı çıkar.
        if time.monotonic() - basladi >= limit * 0.9:
            raise _AttemptTimeout('Sağlayıcı denemesi süre sınırını aştı.') from exc
        raise
    except Exception as exc:
        # SDK'ya özgü zaman aşımı/bağlantı tipleri de olabilir: sınırı biz kestiysek
        # bu bir sağlayıcı hatası değildir, sağlayıcı ceza almamalı.
        if time.monotonic() - basladi >= limit * 0.9:
            raise _AttemptTimeout('Sağlayıcı denemesi süre sınırını aştı.') from exc
        raise


def _run_request(request: ModelRequest, adapter: ProviderAdapter,
                *, validator: Callable[[str], Any] | None = None, attempts=None, record=None) -> RouteResult:
    """Execute a plan with one authority for retry, repair and fallback.

    Each adapter invocation is one real network attempt.  A schema rejection is
    recorded as an attempt and consumes the same two-attempt envelope as a retry
    or fallback. Gemini 429 followed by Groq 413 leaves one ready fallback
    because neither generated an answer. Cancellation/deadline checks happen before and
    after every adapter return, so a late answer is never adopted.
    """
    from modules import router_quota, failure_policy
    _check_request(request)
    route_plan = plan(request)
    attempts = [] if attempts is None else attempts
    skipped_now = list(route_plan.skipped)
    if record is not None:
        record.update(plan_id=route_plan.plan_id,skipped=skipped_now,planned=[{'provider':s.provider,'model':s.model} for s in route_plan.candidates])
    started = time.monotonic()
    candidates=route_plan.candidates+route_plan.alternatives
    if len(candidates) == 1 and validator is not None and not route_plan.deferred_local:
        candidates = candidates + candidates

    def eligible_candidates():
        yield from candidates
        if route_plan.deferred_local and (len(attempts) < route_plan.max_network_attempts
                or _rejected_before_generation(attempts, route_plan.max_network_attempts)):
            _check_request(request)
            spec, reason = _ready_spec(request, 'ollama', vision='vision' in request.features)
            if reason:
                skipped_now.append(reason)
                if len(candidates) == 1 and validator is not None:
                    yield candidates[0]
            else:
                yield spec

    request_rejected = set()
    for spec in eligible_candidates():
        ready_fallback = _rejected_before_generation(attempts, route_plan.max_network_attempts)
        if len(attempts) >= route_plan.max_network_attempts and not ready_fallback:
            break
        if ready_fallback and (spec.connection_id or spec.provider not in ('cloudflare', 'ollama')):
            continue
        with ExitStack() as admission_stack:
            _check_request(request)
            if spec in request_rejected:
                skipped_now.append(_skip(spec.provider,'Aynı istek bu modelin boyut sınırına sığmadı; tekrar gönderilmedi.',
                                         'PROVIDER_REQUEST_TOO_LARGE',model=spec.model))
                continue
            if not _current_admission(request,spec):
                skipped_now.append(_skip(spec.provider,'Bağlantı/veri izni değişti; gönderilmedi.','PROVIDER_ADMISSION_CHANGED',model=spec.model))
                continue
            attempt_id=request.call_id+':'+str(len(attempts)+1)
            try:
                if spec.connection_id or spec.provider == 'ollama':
                    admission_stack.enter_context(router_quota.admission(request,spec,directory=_STORE))
                if spec.connection_id:
                    router_quota.reserve_custom(request.owner,spec.connection_id,spec.connection_revision,directory=_STORE,attempt_id=attempt_id,cost_bound=request.cost_upper_bound_microusd)
            except (router_quota.ReservationUnavailable,router_quota.ReservationExhausted) as exc:
                # This skipped provider made no actual HTTP attempt. Never bypass a
                # configured limit merely because its local SQLite store is locked.
                skipped_now.append(_skip(spec.provider,str(exc),exc.reason_code,
                                         seconds=exc.retry_after,model=spec.model))
                continue
            _check_request(request)
            attempt={'provider':spec.provider,'model':spec.model,'attempt_id':attempt_id,'ok':False,'state':'started'}
            if spec.provider in _CLOUD_PROVIDERS and spec.binding:
                attempt['binding'] = spec.binding
            attempts.append(attempt)
            # Sıradaki aday var mı? Ancak o zaman yavaş sağlayıcı bırakılabilir.
            try:
                _pos = next(i for i, item in enumerate(candidates) if item is spec)
            except StopIteration:
                _pos = len(candidates) - 1
            alternatif = _next_candidate_ready(request, candidates, _pos) or bool(route_plan.deferred_local)
            try:
                from modules import usage_meter
                with usage_meter.capture_attempt(request.owner,request.request_id,attempt_id) as measured:
                    response = _call_with_attempt_timeout(
                        request, lambda: adapter(spec), enabled=alternatif)
                raw_usage=response.usage if isinstance(response,AdapterResponse) else measured['usage']
                attempt['usage']={k:raw_usage.get(k) if type(raw_usage.get(k)) is int and raw_usage[k]>=0 else None for k in ('input_tokens','output_tokens','reasoning_tokens','cached_tokens','total_tokens')}
                if spec.connection_id:
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
                request_limit = isinstance(exc, failure_policy.ProviderRequestLimitError)
                row = {'provider': spec.provider, 'model': spec.model, 'ok': False,'attempt_id':attempt_id,
                       'error': type(classified).__name__,
                       'kind': 'response_validation' if validation_error else failure_kind(classified),
                       'status': failure_status(classified)}
                if request_limit:
                    request_rejected.add(spec)
                    row.update(reason_code='PROVIDER_REQUEST_TOO_LARGE',limit_kind=exc.limit_kind,
                               limit=exc.limit,requested=exc.requested)
                if spec.provider == 'ollama' and type(exc).__name__ == 'LocalModelError':
                    from modules import llm
                    if not isinstance(transport, requests.Timeout) and str(exc) == llm.local_hint():
                        row['hint'] = 'ollama_missing'
                if row['kind'] == 'quota':
                    row['reason_code'] = failure_policy.reason_code(classified)
                if isinstance(classified, _AttemptTimeout):
                    # Kullanıcıya "zaman aşımı" olarak görünsün; sağlayıcı hatası değil.
                    row['kind'] = 'timeout'
                    row['error'] = 'Timeout'
                attempt.update(row,state='failed')
                if (not validation_error and not request_limit
                        and not isinstance(classified, _AttemptTimeout)
                        and type(exc).__name__ != 'ImageCapabilityError'):
                    with _LOCK:
                        _HEALTH[_failure_health_key(request,spec,exc)] = {
                            'until': time.monotonic()+cooldown(spec.provider, exc), 'error': type(exc).__name__}
                from modules import llm
                detail = 'yanıt sözleşmesini karşılamadı' if validation_error else failure_text(classified)
                llm.note_route(llm.provider_label(spec.provider) + ' ' + detail + ', sıradakine geçildi', False)
    from modules import failure_policy
    detail = '; '.join(failure_detail(row) for row in attempts) if attempts else 'Bu çağrıda denenecek sağlayıcı yok.'
    omitted = '; '.join(row['provider'] + ': ' + row['reason'] for row in skipped_now)
    message = ('Uygun modelden yanıt alınamadı. ' + detail +
               (' Atlanan sağlayıcılar: ' + omitted + '.' if omitted else ''))
    if not attempts:
        if any(row.get('reason_code') == 'PROVIDER_CONFIGURATION_REQUIRED'
               or 'anahtarı eksik' in str(row.get('reason', '')) for row in skipped_now):
            raise failure_policy.ProviderExhaustedError(
                message, reason_code='PROVIDER_CONFIGURATION_REQUIRED', recovery_class='user_action_required')
    if attempts and all(row.get('kind') == 'request_limit' for row in attempts):
        raise failure_policy.ProviderExhaustedError(message,reason_code='PROVIDER_REQUEST_TOO_LARGE',
                                                   recovery_class='request_change_required')
    if {row.get('kind') for row in attempts} == {'quota', 'request_limit'}:
        raise failure_policy.ProviderExhaustedError(message, reason_code='PROVIDER_QUOTA_AND_REQUEST_TOO_LARGE',
                                                   recovery_class='fallback_possible')
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


def check_ready_connection(owner, provider):
    from modules import failure_policy, llm
    if not isinstance(provider, str) or provider not in _CLOUD_PROVIDERS:
        raise ValueError('Hazır bağlantı geçersiz.')
    request = ModelRequest(
        owner=owner, profile='connection_test', route=provider_privacy.ROUTE_PUBLIC_RESEARCH,
        data_scope='public', selection_mode='free', max_output_tokens=256,
        max_network_attempts=1, exclude_providers=frozenset((_CLOUD_PROVIDERS | {'ollama'}) - {provider}),
        deadline=time.monotonic() + 12,
    )
    try:
        with requests_state.budget(12):
            result = run_request(request, lambda spec: llm.dispatch(request, spec, 'Reply with OK.', ''))
    except failure_policy.ProviderExhaustedError as exc:
        current = ready_status(owner)
        state = current['ready_connections'][provider]
        msg = str(exc) if state['state'] == 'unchecked' else state['message']
        return {'ok': False, 'msg': msg, 'status': current}
    except requests_state.LocalDeadline:
        return {'ok': False, 'msg': 'Bağlantı zamanında yanıt vermedi.', 'status': ready_status(owner)}
    return {'ok': True, 'msg': f'{llm.provider_label(provider)} yanıt verdi. Model {result.model.model}.',
            'status': ready_status(owner)}


def _ready_connection_status(owner, provider, model, scopes, recent):
    from modules import usage_meter
    configured = _ready_key_configured(owner, provider)
    if not configured:
        return {'configured': False, 'state': 'missing', 'model': model, 'message': 'API bilgisi eksik.'}
    signature = _binding(ModelRequest(owner=owner), provider, model)
    last = next((attempt for trace in recent for attempt in reversed(trace.get('attempts', []))
                 if attempt.get('binding') == signature and attempt.get('provider') == provider
                 and attempt.get('state') in ('completed', 'failed')), None)
    gate = provider_privacy.privacy_gate(provider, provider_privacy.ROUTE_PUBLIC_RESEARCH,
                                         consent_scopes=scopes, data_scope='public')
    if privacy.mode() in ('yerel', 'gizli'):
        state, message = 'disabled', 'Gizlilik modu bulut bağlantısını kapatıyor.'
    elif not gate['ok']:
        state, message = 'disabled', gate['reason']
    elif observed := usage_meter.observed_exhaustion(owner, provider, model, now=time.time(),
                                                     credential=_connection_fingerprint(owner, provider)):
        state, message = 'quota', f"Sağlayıcının bildirdiği kota doldu. {observed['seconds']} saniye kaldı."
    elif last and last.get('reason_code') == 'PROVIDER_QUOTA_EXHAUSTED':
        state, message = 'quota', 'Son çağrıda sağlayıcı kotanın dolduğunu bildirdi.'
    elif last and last.get('kind') == 'quota':
        state, message = 'quota', 'Son çağrı sağlayıcının hız sınırına takıldı.'
    elif last and last.get('ok'):
        state, message = 'ok', 'API yanıt verdi.'
    elif last:
        state, message = 'error', failure_detail(last)
    else:
        state, message = 'unchecked', 'Anahtar kayıtlı. Henüz yanıt alınmadı.'
    return {'configured': configured, 'state': state, 'model': model, 'message': message}


def _status(owner):
    from modules import llm, usage_meter
    state, recent = _ready_status(owner)
    ready = state['ready_connections']
    try:
        local_model = llm._ollama_effective_model(llm.provider_configuration(), refresh_missing=False)
    except llm.LocalModelError:
        local_model = '—'
    capabilities = [{'provider': provider, 'model': row['model'], 'tasks': ['chat', 'code', 'analysis'],
                     'policy': row['message']} for provider, row in ready.items()]
    capabilities.append({'provider': 'ollama', 'model': local_model, 'tasks': ['chat', 'code', 'analysis'],
                         'policy': 'Yerel bağlantı' if local_model != '—' else 'Yerel model doğrulanamadı.'})
    return {
        **state, 'policy_version': POLICY_VERSION,
        'connection_states': {provider: row['configured'] for provider, row in ready.items()},
        'capabilities': capabilities, 'last': recent[0] if recent else {}, 'traces': recent[:12],
        'observed_limits': usage_meter.limits(owner),
    }


def ready_status(owner):
    from modules import llm
    with llm.owner_context(owner):
        state, _ = _ready_status(owner)
        return state


def _ready_status(owner):
    from modules import llm, cloudflare_chat, router_connections, router_quota
    scopes = settings(owner)['gemini_scopes']
    recent = router_quota.recent_traces(owner, directory=_STORE, limit=50)
    models = {'gemini': llm.active_model(owner), 'groq': llm.groq_model(), 'cloudflare': cloudflare_chat.MODEL}
    ready = {provider: _ready_connection_status(owner, provider, model, scopes, recent)
             for provider, model in models.items()}
    last_reply = next(({'provider': row['provider'], 'model': row['model']}
                       for row in recent if row.get('profile') == 'conversation'
                       and row.get('state') == 'completed' and row.get('provider') and row.get('model')), None)
    return {
        'owner': owner, 'gemini_scopes': scopes, 'ready_connections': ready, 'last_reply': last_reply,
        'custom_connections': router_connections.snapshot(owner),
    }, recent


def handle(owner, command):
    c = command.casefold().strip(' .!')
    if c in ('smart router aç','smart router\u2019ı aç','akıllı router aç','otomatik model seçimini aç'):
        from modules import llm
        llm.set_provider('auto'); return 'Otomatik model seçimi açık.'
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
