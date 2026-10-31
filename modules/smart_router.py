"""Budget-aware task routing. Paid providers never belong to the automatic pool."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import re
import threading
import time
import requests
from config import DATA_DIR, load_settings, save_settings
from modules import privacy, requests_state
from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.RLock()
_HEALTH = {}
_LAST = {}
_STORE = DATA_DIR / 'router'
_CLOUD_PROVIDERS = frozenset({'gemini', 'groq', 'openrouter'})
_FREE_PREFERENCES = frozenset({'gemini', 'groq', 'ollama', 'openrouter'})
_PUBLIC_ONLY_PROVIDERS = frozenset({'gemini', 'openrouter'})
_TASK_ORDERS = {
    'vision': ['gemini', 'ollama'],
    'code': ['gemini', 'groq', 'ollama'],
    'analysis': ['gemini', 'groq', 'ollama'],
    'chat': ['groq', 'gemini', 'ollama'],
}
_EVIDENCE_MODELS_MAX = 32


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


def settings(owner):
    defaults={'cloud_free_confirmed':False,'openrouter_model':'openrouter/free','key':'','free_tier_evidence':{}}
    try:
        state=json.loads(owner_path(owner).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaults
    if not isinstance(state,dict): return defaults
    model=state.get('openrouter_model')
    if not isinstance(model,str) or not (model=='openrouter/free' or model.endswith(':free')):
        model='openrouter/free'
    return {'cloud_free_confirmed':state.get('cloud_free_confirmed') is True,
            'openrouter_model':model,
            'key':state.get('key') if isinstance(state.get('key'),str) else '',
            'free_tier_evidence':_safe_evidence_catalog(state.get('free_tier_evidence'))}


def _save_state(owner, state):
    path = owner_path(owner); path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(state), encoding='utf-8'); tmp.replace(path)


def configure(owner, cloud_free_confirmed=None, model=None, key=None):
    with _LOCK:
        return _configure(owner,cloud_free_confirmed,model,key)


def _configure(owner,cloud_free_confirmed=None,model=None,key=None):
    state = settings(owner)
    if cloud_free_confirmed is not None:
        state['cloud_free_confirmed'] = bool(cloud_free_confirmed)
    if model is not None:
        model = model.strip() or 'openrouter/free'
        if model != 'openrouter/free' and not model.endswith(':free'):
            raise ValueError('Otomatik havuz yalnız openrouter/free veya :free modellerini kabul eder.')
        state['openrouter_model'] = model
    if key is not None:
        state['key'] = privacy.protect(key.strip()) if key.strip() else ''
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


def _evidence_gate(owner, provider, model, *, now=None):
    """Strict zero-cost gate. UNKNOWN is never ALLOW."""
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


def api_key(owner):
    protected = settings(owner).get('key', '')
    try:
        return privacy.unprotect(protected) if protected else ''
    except (ValueError, OSError, UnicodeError):
        _record_failure('modules/smart_router.py:api_key')
        return ''


def task_type(prompt, image=False):
    if image: return 'vision'
    p = prompt.casefold()
    if re.search(r'kod|python|javascript|hata|debug|fonksiyon|geliştir|refactor', p): return 'code'
    if len(prompt) > 10000 or re.search(r'belge|pdf|analiz|karşılaştır|araştır|rapor', p): return 'analysis'
    return 'chat'


def _sensitive_prompt(prompt) -> bool:
    """Reuse the existing privacy detector; it is routing evidence, never authority over content."""
    if privacy.mode() == 'gizli':
        return True
    text = str(prompt or '')
    try:
        return privacy.redact(text, force=True) != text
    except Exception:
        _record_failure('modules/smart_router.py:sensitive_prompt')
        return True


def _skip(provider, reason, reason_code, seconds=0, model=''):
    row = {'provider':provider,'reason':reason,'reason_code':reason_code,'seconds':seconds}
    if model:
        row['model'] = model
    return row


def provider_allowed(owner, provider, model=None, *, task=None, sensitive=None):
    """Read-only strict zero-cost and data-policy decision for one provider/model.

    The helper reuses the canonical Router evidence/cooldown policy. It never records
    evidence, changes preference, calls a provider, or grants paid consent.
    """
    from modules import llm
    provider = str(provider or '').strip().casefold()
    if provider not in _FREE_PREFERENCES:
        return {'ok':False,'reason_code':'PROVIDER_TASK_UNSUPPORTED',
                'reason':'Bu sağlayıcı strict zero-cost Router havuzunda değil.','model':str(model or '')}
    if privacy.mode() == 'yerel':
        if provider == 'ollama':
            return {'ok':True,'reason_code':None,'reason':'Yerel mod yalnız yerel sağlayıcıya izin verir.','model':str(model or '')}
        return {'ok':False,'reason_code':'PROVIDER_LOCAL_MODE','reason':'Yerel modda bulut kapalı.','model':str(model or '')}
    sensitive = privacy.mode() == 'gizli' if sensitive is None else bool(sensitive)
    if sensitive and provider in _PUBLIC_ONLY_PROVIDERS:
        return {'ok':False,'reason_code':'PROVIDER_DATA_POLICY_BLOCKED',
                'reason':'Bu sağlayıcı yalnız PUBLIC içerik için kullanılabilir.','model':str(model or '')}
    if task and provider != 'openrouter' and provider not in _TASK_ORDERS.get(task, ()):
        return {'ok':False,'reason_code':'PROVIDER_TASK_UNSUPPORTED','reason':'Bu görev türü desteklenmiyor.','model':str(model or '')}
    if provider == 'ollama':
        return {'ok':True,'reason_code':None,'reason':'Yerel sağlayıcı strict zero-cost havuzunda kullanılabilir.','model':str(model or '')}

    state = settings(owner)
    if not state.get('cloud_free_confirmed'):
        return {'ok':False,'reason_code':'PROVIDER_FREE_ACCOUNT_UNCONFIRMED','reason':'Ücretsiz hesap onayı yok.','model':str(model or '')}
    if provider == 'gemini':
        resolved_model = str(model or llm.active_model(owner) or '')
        has_key = bool(llm.user_key(owner))
    elif provider == 'groq':
        resolved_model = str(model or llm.groq_model() or '')
        has_key = bool(llm.user_groq_key(owner))
    else:
        resolved_model = str(model or state.get('openrouter_model') or 'openrouter/free')
        if resolved_model != 'openrouter/free' and not resolved_model.endswith(':free'):
            return {'ok':False,'reason_code':'PROVIDER_FREE_TIER_NOT_ELIGIBLE',
                    'reason':'OpenRouter otomatik rota yalnız openrouter/free veya :free model kullanabilir.',
                    'model':resolved_model}
        has_key = bool(api_key(owner))
    if not has_key:
        return {'ok':False,'reason_code':'PROVIDER_CONFIGURATION_REQUIRED',
                'reason':'Bu kullanıcı için API anahtarı eksik.','model':resolved_model}
    gate = _evidence_gate(owner, provider, resolved_model)
    if not gate['ok']:
        return {**gate, 'model':resolved_model}
    with _LOCK:
        seconds=max(0,int(_HEALTH.get((owner,provider),{}).get('until',0)-time.monotonic()+.999))
    if seconds:
        return {'ok':False,'reason_code':'PROVIDER_COOLDOWN',
                'reason':'Önceki başarısız çağrı nedeniyle '+str(seconds)+' saniye beklemede.',
                'seconds':seconds,'model':resolved_model}
    return {'ok':True,'reason_code':None,'reason':'Doğrulanmış ücretsiz rota kullanılabilir.',
            'model':resolved_model,'evidence':gate.get('evidence')}


def selection(owner,task,preferred=None, *, sensitive=None):
    if task not in _TASK_ORDERS:
        raise ValueError('Router görev türü geçersiz.')
    preferred = str(preferred or '').strip().casefold()
    if preferred not in _FREE_PREFERENCES:
        preferred = ''
    if privacy.mode()=='yerel':
        skipped=[_skip(p,'Yerel modda bulut kapalı','PROVIDER_LOCAL_MODE') for p in ('gemini','groq')]
        if preferred=='openrouter':
            skipped.append(_skip('openrouter','Yerel modda bulut kapalı','PROVIDER_LOCAL_MODE'))
        return {'candidates':['ollama'],'skipped':skipped}
    sensitive = privacy.mode() == 'gizli' if sensitive is None else bool(sensitive)

    order=list(_TASK_ORDERS[task])
    if preferred == 'openrouter' and not sensitive:
        order.insert(0,'openrouter')
    elif preferred in order and not (sensitive and preferred in _PUBLIC_ONLY_PROVIDERS):
        order.remove(preferred);order.insert(0,preferred)
    universe=['gemini','groq','ollama']
    if preferred=='openrouter':
        universe.append('openrouter')
    selected=[];skipped=[]
    for provider in universe:
        decision=provider_allowed(owner,provider,task=task,sensitive=sensitive)
        model=str(decision.get('model') or '')
        if decision['ok']:
            selected.append(provider)
        else:
            skipped.append(_skip(provider,decision['reason'],decision['reason_code'],
                                 int(decision.get('seconds') or 0),model))
    return {'candidates':[p for p in order if p in selected],'skipped':skipped}


def wait_seconds(owner, task='analysis', preferred=None, *, sensitive=None):
    """Hiç uygun sağlayıcı kalmadıysa ve en az biri bekleme (kota/hata) içindeyse kalan en kısa saniye; yoksa 0."""
    row = selection(owner, task, preferred=preferred, sensitive=sensitive)
    if row['candidates']:
        return 0
    waits = [int(item.get('seconds') or 0) for item in row['skipped'] if item.get('seconds')]
    return min(waits) if waits else 0


def candidates(owner, task, preferred=None, *, sensitive=None):
    return selection(owner,task,preferred=preferred,sensitive=sensitive)['candidates']


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


def _free_emergency(owner, attempted, *, sensitive=False):
    """Optional last-resort free route. It never bypasses local or sensitive-data policy."""
    if privacy.mode()=='yerel' or sensitive or 'openrouter' in attempted:return False
    state=settings(owner)
    model=state.get('openrouter_model') or 'openrouter/free'
    return provider_allowed(owner,'openrouter',model=model,sensitive=False)['ok']


def run(owner, prompt, callback, image=False, preferred=None):
    task = task_type(prompt, image)
    sensitive = _sensitive_prompt(prompt)
    attempts = []
    route = selection(owner,task,preferred=preferred,sensitive=sensitive)
    selected=list(route['candidates'])
    skipped=list(route['skipped'])
    providers=list(selected)
    if _free_emergency(owner,providers,sensitive=sensitive):providers.append('openrouter')
    for provider in providers:
        requests_state.check(); start = time.monotonic()
        try:
            answer = callback(provider)
            requests_state.check()
            if not isinstance(answer,str) or not answer.strip(): raise ValueError('Boş model yanıtı.')
        except requests_state.Cancelled:
            raise
        except Exception as exc:
            _record_failure('modules/smart_router.py:run')
            # Local adapters wrap transport errors; retain only their type, never
            # the raw request/URL/body. Routing and cooldown still use exc.
            transport = (exc.__cause__ if provider == 'ollama' and
                         type(exc).__name__ == 'LocalModelError' and
                         isinstance(exc.__cause__, (requests.Timeout, requests.ConnectionError)) else None)
            attempt={'provider':provider,'ok':False,'error':type(transport or exc).__name__,
                     'kind':failure_kind(exc),'status':failure_status(exc)}
            if provider == 'ollama' and type(exc).__name__ == 'LocalModelError':
                from modules import llm
                if not isinstance(transport, requests.Timeout) and str(exc) == llm.local_hint():
                    attempt['hint'] = 'ollama_missing'
            attempts.append(attempt)
            from modules import llm
            llm.note_route(llm.provider_label(provider) + ' ' + failure_text(transport or exc) + ', sıradakine geçildi', False)
            if type(exc).__name__ != 'ImageCapabilityError':
                with _LOCK: _HEALTH[(owner,provider)] = {'until':time.monotonic()+cooldown(provider,exc),'error':type(exc).__name__}
            continue
        attempts.append({'provider':provider,'ok':True,'seconds':round(time.monotonic()-start,2)})
        with _LOCK:
            _LAST[owner] = {'task':task,'data_class':'sensitive' if sensitive else 'public',
                            'provider':provider,'attempts':attempts,'skipped':skipped}
            _HEALTH.pop((owner,provider),None)
        return answer
    with _LOCK:
        _LAST[owner] = {'task':task,'data_class':'sensitive' if sensitive else 'public',
                        'provider':None,'attempts':attempts,'skipped':skipped}
    from modules import failure_policy
    detail = '; '.join(failure_detail(a) for a in attempts) if attempts else 'Bu çağrıda denenecek sağlayıcı yok; onay, anahtar, free-tier evidence ve bekleme durumunu router durumu ile kontrol et.'
    omitted='; '.join(row['provider']+': '+row['reason'] for row in skipped)
    message='Uygun ücretsiz model yanıt vermedi. '+detail+(' Atlanan sağlayıcılar: '+omitted+'.' if omitted else '')+' Ücretli modele geçilmedi.'
    preferred_row = next((row for row in skipped if row.get('provider') == preferred), None)
    preferred_code = str((preferred_row or {}).get('reason_code') or '')
    if preferred_code == 'PROVIDER_CONFIGURATION_REQUIRED' or preferred_code.startswith('PROVIDER_FREE_'):
        raise failure_policy.ProviderExhaustedError(
            message, reason_code=preferred_code, recovery_class='user_action_required')
    missing_key = not attempts and any(row.get('reason_code')=='PROVIDER_CONFIGURATION_REQUIRED' or 'anahtarı eksik' in row.get('reason','') for row in skipped)
    evidence_code = next((row.get('reason_code') for row in skipped
                          if str(row.get('reason_code','')).startswith('PROVIDER_FREE_TIER_')), None)
    if missing_key:
        raise failure_policy.ProviderExhaustedError(
            message, reason_code='PROVIDER_CONFIGURATION_REQUIRED', recovery_class='user_action_required')
    if not attempts and evidence_code:
        raise failure_policy.ProviderExhaustedError(
            message, reason_code=evidence_code, recovery_class='user_action_required')
    raise failure_policy.ProviderExhaustedError(message)


def openrouter(owner, messages, system, max_tokens, image_path=None):
    key = api_key(owner)
    if not key: raise ValueError('OpenRouter anahtarı yok.')
    model = settings(owner).get('openrouter_model') or 'openrouter/free'
    if model != 'openrouter/free' and not model.endswith(':free'): raise ValueError('Ücretli model engellendi.')
    messages = [dict(m, content=privacy.redact(m['content'])) for m in messages]
    if image_path:
        from PIL import Image
        import io
        with Image.open(image_path) as img:
            img.thumbnail((1600,1600)); output = io.BytesIO(); img.convert('RGB').save(output,format='PNG')
        data = base64.b64encode(output.getvalue()).decode()
        messages[-1]['content'] = [{'type':'text','text':messages[-1]['content']},
          {'type':'image_url','image_url':{'url':'data:image/png;base64,'+data}}]
    if system: messages.insert(0, {'role':'system','content':privacy.redact(system)})
    requests_state.check()
    from modules import usage_meter
    sent = usage_meter.size(messages)
    try:
        response = requests.post('https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization':'Bearer '+key}, json={'model':model,'messages':messages,'max_tokens':max_tokens}, timeout=(5,45))
        response.raise_for_status()
    except requests.RequestException as exc:
        usage_meter.record('openrouter', model, sent, 0, usage_meter.outcome(exc))
        raise
    usage_meter.record('openrouter', model, sent)
    requests_state.check()
    try:
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('empty content')
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError('OpenRouter geçerli bir metin yanıtı döndürmedi.') from exc
    return content


def status(owner):
    state = settings(owner)
    from modules import llm, usage_meter
    with _LOCK:
        cooldowns={p:max(0,round(v['until']-time.monotonic())) for (u,p),v in _HEALTH.items() if u==owner and v['until']>time.monotonic()}
        last=_LAST.get(owner,{})
    def cloud_policy(provider, model, has_key):
        if not state.get('cloud_free_confirmed'):
            return 'Ücretsiz hesap onayı gerekli'
        if not has_key:
            return 'Ücretsiz hesap onaylı; bu kullanıcı için API anahtarı eksik'
        gate=_evidence_gate(owner,provider,model)
        if not gate['ok']:
            return 'Ücretsiz hesap onaylı; '+gate['reason']+' ['+gate['reason_code']+']'
        if provider in cooldowns:
            return f'Kanıtlı ücretsiz rota; son çağrı başarısız, {cooldowns[provider]} saniye beklemede'
        return 'Kanıtlı ücretsiz rota; evidence geçerli ve strict zero-cost seçimde kullanılabilir'
    gemini_model=llm.active_model(owner)
    groq_model=llm.groq_model()
    openrouter_model=state.get('openrouter_model','openrouter/free')
    openrouter_policy=('Yerel modda kullanılmaz' if privacy.mode()=='yerel' else
        cloud_policy('openrouter',openrouter_model,bool(api_key(owner)))+'; PUBLIC-only; ana havuz tükenirse ücretsiz son yedek')
    local_policy='Yerel; PUBLIC/SENSITIVE; görüntü için ayrıca vision modeli gerekir'
    try:
        local_model=llm._ollama_effective_model(llm.provider_configuration(), refresh_missing=False)
    except llm.LocalModelError:
        local_model='—'
        local_policy='Yerel effective model doğrulanamadı; yerel sunucuyu ve kurulu modelleri kontrol et'
    table = [
      {'provider':'gemini','model':gemini_model,'tasks':['chat','code','analysis','vision'],'policy':cloud_policy('gemini',gemini_model,bool(llm.user_key(owner)))+'; PUBLIC-only'},
      {'provider':'groq','model':groq_model,'tasks':['chat','code','analysis'],'policy':cloud_policy('groq',groq_model,bool(llm.user_groq_key(owner)))+'; PUBLIC/SENSITIVE'},
      {'provider':'openrouter','model':openrouter_model,'tasks':['chat','code','analysis','vision'],'policy':openrouter_policy},
      {'provider':'ollama','model':local_model,'tasks':['chat','code','analysis'],'policy':local_policy},
      {'provider':'openai/anthropic','model':'Kullanıcının seçtiği','tasks':[],'policy':'Otomatik havuz dışında; yalnız elle seçim'}]
    return {'key':bool(api_key(owner)), 'cloud_free_confirmed':bool(state.get('cloud_free_confirmed')),
            'model':openrouter_model,'capabilities':table,'last':last,'cooldowns':cooldowns,
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
