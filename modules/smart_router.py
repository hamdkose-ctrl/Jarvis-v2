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


def owner_path(owner):
    if not owner or not re.fullmatch(r'[\w-]{1,100}', owner):
        raise ValueError('Kullanıcı geçersiz.')
    return _STORE / (owner + '.json')


def settings(owner):
    defaults={'cloud_free_confirmed':False,'openrouter_model':'openrouter/free','key':''}
    try:
        state=json.loads(owner_path(owner).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return defaults
    if not isinstance(state,dict): return defaults
    model=state.get('openrouter_model')
    if not isinstance(model,str) or not (model=='openrouter/free' or model.endswith(':free')):
        model='openrouter/free'
    return {'cloud_free_confirmed':state.get('cloud_free_confirmed') is True,
            'openrouter_model':model,'key':state.get('key') if isinstance(state.get('key'),str) else ''}


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
    path = owner_path(owner); path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(state), encoding='utf-8'); tmp.replace(path)
    return status(owner)


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


def selection(owner,task):
    from modules import llm
    if privacy.mode()=='yerel':
        return {'candidates':['ollama'],'skipped':[{'provider':p,'reason':'Yerel modda bulut kapalı','seconds':0} for p in ('gemini','groq')]}
    state=settings(owner)
    orders={'vision':['gemini','ollama'],'code':['gemini','groq','ollama'],
            'analysis':['gemini','groq','ollama'],'chat':['groq','gemini','ollama']}
    selected=[];skipped=[];local=privacy.mode()=='yerel'
    for provider in ('gemini','groq','ollama'):
        reason=None;seconds=0
        if local and provider!='ollama':reason='Yerel modda bulut kapalı'
        elif provider not in orders[task]:reason='Bu görev türü desteklenmiyor'
        elif provider!='ollama' and not state.get('cloud_free_confirmed'):reason='Ücretsiz hesap onayı yok'
        elif provider=='gemini' and not llm.user_key(owner):reason='Bu kullanıcı için API anahtarı eksik'
        elif provider=='groq' and not llm.user_groq_key(owner):reason='Bu kullanıcı için API anahtarı eksik'
        else:
            with _LOCK:seconds=max(0,int(_HEALTH.get((owner,provider),{}).get('until',0)-time.monotonic()+.999))
            if seconds:reason='Önceki başarısız çağrı nedeniyle '+str(seconds)+' saniye beklemede'
        if reason:skipped.append({'provider':provider,'reason':reason,'seconds':seconds})
        else:selected.append(provider)
    return {'candidates':[p for p in orders[task] if p in selected],'skipped':skipped}


def candidates(owner, task):
    return selection(owner,task)['candidates']


def failure_kind(exc):
    from modules import failure_policy
    return failure_policy.legacy_kind(exc)


def failure_status(exc):
    from modules import failure_policy
    return failure_policy.status_code(exc)


def failure_detail(attempt):
    reason = {'key':'kimlik/erişim reddedildi', 'quota':'kota veya hız sınırı'}.get(attempt.get('kind'), 'çağrı başarısız')
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


def _free_emergency(owner, attempted):
    """Optional last-resort free route. It never enables paid models or bypasses local privacy mode."""
    if privacy.mode()=='yerel' or 'openrouter' in attempted:return False
    state=settings(owner)
    if not state.get('cloud_free_confirmed') or not api_key(owner):return False
    model=state.get('openrouter_model') or 'openrouter/free'
    return model=='openrouter/free' or model.endswith(':free')


def run(owner, prompt, callback, image=False):
    task = task_type(prompt, image)
    attempts = []
    selected=candidates(owner,task)
    skipped=[row for row in selection(owner,task)['skipped'] if row['provider'] not in selected]
    providers=list(selected)
    if _free_emergency(owner,providers):providers.append('openrouter')
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
            attempts.append({'provider':provider,'ok':False,'error':type(exc).__name__,
                             'kind':failure_kind(exc),'status':failure_status(exc)})
            from modules import llm
            llm.note_route(llm.provider_label(provider) + ' ' + failure_text(exc) + ', sıradakine geçildi', False)
            if type(exc).__name__ != 'ImageCapabilityError':
                with _LOCK: _HEALTH[(owner,provider)] = {'until':time.monotonic()+cooldown(provider,exc),'error':type(exc).__name__}
            continue
        attempts.append({'provider':provider,'ok':True,'seconds':round(time.monotonic()-start,2)})
        with _LOCK:
            _LAST[owner] = {'task':task,'provider':provider,'attempts':attempts,'skipped':skipped}
            _HEALTH.pop((owner,provider),None)
        return answer
    with _LOCK: _LAST[owner] = {'task':task,'provider':None,'attempts':attempts,'skipped':skipped}
    detail = '; '.join(failure_detail(a) for a in attempts) if attempts else 'Bu çağrıda denenecek sağlayıcı yok; onay, anahtar ve bekleme durumunu router durumu ile kontrol et.'
    omitted='; '.join(row['provider']+': '+row['reason'] for row in skipped)
    raise RuntimeError('Uygun ücretsiz model yanıt vermedi. '+detail+(' Atlanan sağlayıcılar: '+omitted+'.' if omitted else '')+' Ücretli modele geçilmedi.')


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
    from modules import llm
    with _LOCK:
        cooldowns={p:max(0,round(v['until']-time.monotonic())) for (u,p),v in _HEALTH.items() if u==owner and v['until']>time.monotonic()}
        last=_LAST.get(owner,{})
    def cloud_policy(provider, has_key):
        if not state.get('cloud_free_confirmed'):
            return 'Ücretsiz hesap onayı gerekli'
        if not has_key:
            return 'Ücretsiz hesap onaylı; bu kullanıcı için API anahtarı eksik'
        if provider in cooldowns:
            return f'Ücretsiz hesap onaylı; son çağrı başarısız, {cooldowns[provider]} saniye beklemede'
        return 'Ücretsiz hesap onaylı; otomatik seçimde kullanılabilir (canlı çağrı sınanmadı)'
    openrouter_policy=('Yerel modda kullanılmaz' if privacy.mode()=='yerel' else
        cloud_policy('openrouter',bool(api_key(owner)))+'; ana havuz tükenirse ücretsiz son yedek')
    table = [
      {'provider':'gemini','model':llm.active_model(owner),'tasks':['chat','code','analysis','vision'],'policy':cloud_policy('gemini',bool(llm.user_key(owner)))},
      {'provider':'groq','model':llm.groq_model(),'tasks':['chat','code','analysis'],'policy':cloud_policy('groq',bool(llm.user_groq_key(owner)))},
      {'provider':'openrouter','model':state.get('openrouter_model','openrouter/free'),'tasks':['chat','code','analysis','vision'],'policy':openrouter_policy},
      {'provider':'ollama','model':llm.provider_configuration()['model'],'tasks':['chat','code','analysis'],'policy':'Yerel; görüntü için ayrıca vision modeli gerekir'},
      {'provider':'openai/anthropic','model':'Kullanıcının seçtiği','tasks':[],'policy':'Otomatik havuz dışında; yalnız elle seçim'}]
    return {'key':bool(api_key(owner)), 'cloud_free_confirmed':bool(state.get('cloud_free_confirmed')),
            'model':state.get('openrouter_model','openrouter/free'),'capabilities':table,'last':last,'cooldowns':cooldowns}


def handle(owner, command):
    c = command.casefold().strip(' .!')
    if c in ('smart router aç','smart router\u2019ı aç','akıllı router aç','otomatik model seçimini aç'):
        from modules import llm
        llm.set_provider('auto'); return 'Smart Router açık. Göreve uygun ücretsiz havuz kullanılıyor.'
    if c in ('router durumu','model yetenekleri','smart router durumu'):
        s = status(owner)
        rows = ['| Sağlayıcı | Model | Görevler | Politika |','|---|---|---|---|']
        for r in s['capabilities']: rows.append('| '+ ' | '.join([r['provider'],r['model'],', '.join(r['tasks']),r['policy']])+' |')
        attempts = s['last'].get('attempts', [])
        trace = '\n'.join(failure_detail(a) if not a['ok'] else a['provider'] + ': yanıt alındı' for a in attempts)
        skipped='; '.join(row['provider']+': '+row['reason'] for row in s['last'].get('skipped',[]))
        return '\n'.join(rows)+('\n\nAtlanan sağlayıcılar: '+skipped if skipped else '')+'\n\nSon seçim: '+str(s['last'].get('provider') or 'Henüz yok') + ('\nSon çağrı denemeleri:\n' + trace if trace else '')
    return None
