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


def candidates(owner, task):
    from modules import llm
    if privacy.mode() == 'yerel': return ['ollama']
    state = settings(owner)
    ready = {'ollama': True,
             'gemini': bool(state.get('cloud_free_confirmed') and llm.user_key(owner)),
             'groq': bool(state.get('cloud_free_confirmed') and llm.user_groq_key(owner))}
    # OpenRouter stays a manual choice only: the automatic pool never sends prompts to a third-party gateway.
    orders = {'vision': ['gemini','ollama'], 'code': ['gemini','groq','ollama'],
              'analysis': ['gemini','groq','ollama'], 'chat': ['groq','gemini','ollama']}
    with _LOCK:
        return [p for p in orders[task] if ready[p] and _HEALTH.get((owner,p), {}).get('until',0) <= time.monotonic()]


def failure_kind(exc):
    """'key', 'quota' or 'other'; looks only at the status code and error wording, nothing is stored."""
    code = getattr(exc, 'code', None)
    text = str(exc)
    if code in (401, 403) or 'yetkisiz' in text or 'API_KEY_INVALID' in text: return 'key'
    if code == 429 or re.search(r'\b429\b|RESOURCE_EXHAUSTED|quota', text, re.I): return 'quota'
    return 'other'


def failure_text(exc):
    return {'key':'anahtarı geçersiz','quota':'kotası dolu'}.get(failure_kind(exc), 'yanıt vermedi')


def cooldown(provider, exc):
    """Seconds to skip a provider after a failure: long for a bad key, medium for quota, short for a local outage."""
    kind = failure_kind(exc)
    if kind == 'key': return 1800
    if kind == 'quota': return 300
    if provider == 'ollama': return 30
    return 60


def run(owner, prompt, callback, image=False):
    task = task_type(prompt, image)
    attempts = []
    for provider in candidates(owner, task):
        requests_state.check(); start = time.monotonic()
        try:
            answer = callback(provider)
            requests_state.check()
            if not isinstance(answer,str) or not answer.strip(): raise ValueError('Boş model yanıtı.')
        except requests_state.Cancelled:
            raise
        except Exception as exc:
            _record_failure('modules/smart_router.py:run')
            # Store only exception types; never keys, prompts or server error bodies.
            attempts.append({'provider':provider,'ok':False,'error':type(exc).__name__})
            from modules import llm
            llm.note_route(llm.provider_label(provider) + ' ' + failure_text(exc) + ', sıradakine geçildi', False)
            if type(exc).__name__ != 'ImageCapabilityError':
                with _LOCK: _HEALTH[(owner,provider)] = {'until':time.monotonic()+cooldown(provider,exc),'error':type(exc).__name__}
            continue
        attempts.append({'provider':provider,'ok':True,'seconds':round(time.monotonic()-start,2)})
        with _LOCK:
            _LAST[owner] = {'task':task,'provider':provider,'attempts':attempts}
            _HEALTH.pop((owner,provider),None)
        return answer
    with _LOCK: _LAST[owner] = {'task':task,'provider':None,'attempts':attempts}
    raise RuntimeError('Uygun ücretsiz model yanıt vermedi. Ayarlar > AI bölümünde Gemini/Groq ücretsiz hesap kutusunu işaretle veya Ollama çalıştır. Ücretli modele geçilmedi.')


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
    response = requests.post('https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization':'Bearer '+key}, json={'model':model,'messages':messages,'max_tokens':max_tokens}, timeout=(5,45))
    response.raise_for_status()
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
    table = [
      {'provider':'gemini','model':llm.active_model(owner),'tasks':['chat','code','analysis','vision'],'policy':'Ücretsiz hesap doğrulaması gerekli'},
      {'provider':'groq','model':llm.groq_model(),'tasks':['chat','code','analysis'],'policy':'Ücretsiz hesap doğrulaması gerekli'},
      {'provider':'openrouter','model':state.get('openrouter_model','openrouter/free'),'tasks':['chat','code','analysis','vision'],'policy':'Otomatik havuz dışında; yalnız elle seçim'},
      {'provider':'ollama','model':llm.provider_configuration()['model'],'tasks':['chat','code','analysis'],'policy':'Yerel; görüntü için ayrıca vision modeli gerekir'},
      {'provider':'openai/anthropic','model':'Kullanıcının seçtiği','tasks':[],'policy':'Otomatik havuz dışında; yalnız elle seçim'}]
    with _LOCK:
        cooldowns={p:max(0,round(v['until']-time.monotonic())) for (u,p),v in _HEALTH.items() if u==owner and v['until']>time.monotonic()}
        last=_LAST.get(owner,{})
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
        return '\n'.join(rows)+'\n\nSon seçim: '+str(s['last'].get('provider') or 'Henüz yok')
    return None
